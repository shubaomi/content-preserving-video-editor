from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cover_editorial import CoverEditorialError, build_cover_editorial_plan  # noqa: E402


class CoverEditorialTests(unittest.TestCase):
    def _semantic_brief(self, root: Path, *, with_direction: bool = True) -> Path:
        brief = {
            "schema_version": 2,
            "events": [{
                "id": "event-1",
                "transcript_quote": "真正重要的是用证据约束封面",
                "viewer_takeaway": "封面需要内容证据而不是随机装饰",
            }],
        }
        if with_direction:
            brief["cover_direction"] = {
                "headline": "用证据做封面",
                "highlight_terms": ["证据"],
                "eyebrow": "AI 视频工作流",
                "subtitle": "稳定比随机惊喜更重要",
                "tone": "tutorial",
                "evidence_event_ids": ["event-1"],
                "visual_concept": "创作者讲解封面工作流，旁边展示主题卡片",
                "subject_side": "right",
                "visual_route": "real_person_ip_hybrid",
            }
        path = root / "semantic-brief.json"
        path.write_text(json.dumps(brief, ensure_ascii=False), encoding="utf-8")
        return path

    def _references(self, root: Path) -> tuple[list[str], list[str], str]:
        paths: list[str] = []
        for index in range(3):
            path = root / f"identity-{index}.png"
            Image.new("RGB", (120, 120), (80 + index * 20, 90, 100)).save(path)
            paths.append(str(path))
        ip = root / "ip.png"
        Image.new("RGBA", (160, 160), (25, 120, 90, 255)).save(ip)
        return paths[:2], paths[2:], str(ip)

    def test_builds_evidence_bound_hybrid_plan_with_distinct_templates(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            identity, expression, ip = self._references(root)
            semantic = self._semantic_brief(root)
            output = root / "cover-editorial-plan.json"
            project = {
                "video_id": "sample",
                "title": "Fallback title",
                "cover": {
                    "identity_references": identity,
                    "expression_references": expression,
                    "editorial": {
                        "enabled": True,
                        "mode": "auto",
                        "template_families": [
                            "bright_tech_tutorial",
                            "dark_high_energy",
                            "thought_leadership_ip",
                        ],
                        "supporting_assets": [{
                            "path": ip,
                            "role": "personal_ip",
                            "purpose": "explain the evidence-backed workflow",
                            "rights_basis": "project-owned personal IP",
                        }],
                    },
                    "variants": {
                        "A": {"strategy": "topic clarity"},
                        "B": {"strategy": "human curiosity"},
                    },
                },
            }

            plan = build_cover_editorial_plan(
                project=project,
                project_root=root,
                semantic_brief=semantic,
                output=output,
            )

            self.assertEqual(plan["route"], "real_person_ip_hybrid")
            self.assertEqual(plan["headline"]["text"], "用证据做封面")
            self.assertEqual(plan["headline"]["highlight_terms"], ["证据"])
            self.assertEqual(plan["evidence"]["event_ids"], ["event-1"])
            self.assertNotEqual(
                plan["variants"]["A"]["template_family"],
                plan["variants"]["B"]["template_family"],
            )
            self.assertEqual(plan["variants"]["A"]["text_side"], "top-left")
            self.assertTrue(plan["supporting_assets"][0]["available"])
            self.assertTrue(plan["supporting_assets"][0]["sha256"])
            self.assertEqual(json.loads(output.read_text(encoding="utf-8")), plan)

    def test_rejects_semantic_direction_without_valid_event_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            identity, expression, _ = self._references(root)
            semantic = self._semantic_brief(root)
            data = json.loads(semantic.read_text(encoding="utf-8"))
            data["cover_direction"]["evidence_event_ids"] = ["missing-event"]
            semantic.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            with self.assertRaisesRegex(CoverEditorialError, "evidence_event_ids"):
                build_cover_editorial_plan(
                    project={"cover": {
                        "identity_references": identity,
                        "expression_references": expression,
                        "editorial": {"enabled": True},
                    }},
                    project_root=root,
                    semantic_brief=semantic,
                    output=root / "plan.json",
                )

    def test_auto_route_can_prefer_an_authentic_frame_without_rewriting_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            identity, expression, _ = self._references(root)
            frame = root / "authentic-frame.png"
            Image.new("RGB", (1080, 1920), "#304050").save(frame)
            semantic = self._semantic_brief(root)
            data = json.loads(semantic.read_text(encoding="utf-8"))
            data["cover_direction"]["visual_route"] = "auto"
            semantic.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            plan = build_cover_editorial_plan(
                project={"cover": {
                    "identity_references": identity,
                    "expression_references": expression,
                    "editorial": {
                        "enabled": True,
                        "prefer_authentic_frame": True,
                        "authentic_frames": [str(frame)],
                    },
                }},
                project_root=root,
                semantic_brief=semantic,
                output=root / "plan.json",
            )

            self.assertEqual(plan["route"], "authentic_frame_editorial")
            self.assertEqual(plan["authentic_frames"][0]["path"], str(frame.resolve()))
            self.assertTrue(plan["authentic_frames"][0]["sha256"])


if __name__ == "__main__":
    unittest.main()
