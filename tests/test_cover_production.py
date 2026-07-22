from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cover_production import CoverProductionActionRequired, produce_cover  # noqa: E402
from director_adapters import AdapterRunner  # noqa: E402


class CoverProductionTests(unittest.TestCase):
    def test_missing_reference_guided_bases_returns_truthful_action_request(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            refs = []
            for index in range(3):
                path = root / f"ref-{index}.jpg"
                Image.new("RGB", (100, 100), "white").save(path)
                refs.append(str(path))
            with self.assertRaises(CoverProductionActionRequired) as caught:
                produce_cover(
                    project={"title": "Topic", "cover": {
                        "enabled": True, "identity_references": refs[:2],
                        "expression_references": refs[2:], "variants": {},
                    }}, project_root=root, semantic_brief=root / "semantic.json",
                    output=root / "cover.jpg", work_dir=root / "work",
                    runner=AdapterRunner(root / "state.json"), execute_external=False,
                )
            packet = caught.exception.packet
            self.assertEqual(packet["generation_mode"], "reference_guided_regeneration")
            self.assertEqual(packet["variant_count"], 2)
            self.assertTrue(packet["no_pasted_cutout"])

    def test_existing_reviewed_bases_run_typography_ab_and_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            refs = []
            for index in range(3):
                path = root / f"ref-{index}.jpg"
                Image.new("RGB", (120, 120), (80 + index * 20, 80, 80)).save(path)
                refs.append(str(path))
            base_a = root / "base-a.png"
            base_b = root / "base-b.png"
            Image.new("RGB", (1080, 1920), "#102030").save(base_a)
            Image.new("RGB", (1080, 1920), "#e0b070").save(base_b)
            semantic = root / "semantic.json"
            semantic.write_text(json.dumps({"topic": "test"}), encoding="utf-8")
            output = root / "exports" / "cover.jpg"
            artifacts = produce_cover(
                project={"title": "Auditable workflow", "cover": {
                    "enabled": True, "identity_references": refs[:2],
                    "expression_references": refs[2:], "label": "CREATOR LAB",
                    "variants": {
                        "A": {"clean_base": str(base_a), "strategy": "topic clarity",
                              "text_side": "top-left", "agent_identity_reviewed": True,
                              "agent_expression_reviewed": True},
                        "B": {"clean_base": str(base_b), "strategy": "human curiosity",
                              "text_side": "top-right", "agent_identity_reviewed": True,
                              "agent_expression_reviewed": True},
                    },
                }}, project_root=root, semantic_brief=semantic, output=output,
                work_dir=root / "work", runner=AdapterRunner(root / "state.json"),
                execute_external=True,
            )
            self.assertTrue(output.is_file())
            self.assertTrue((output.with_suffix(".manifest.json")).is_file())
            self.assertTrue(any(path.name == "cover-ab-report.json" for path in artifacts))

    def test_enhanced_editorial_path_produces_plan_template_qa_and_hash_bound_promotion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            refs = []
            for index in range(3):
                path = root / f"ref-{index}.jpg"
                Image.new("RGB", (160, 160), (70 + index * 25, 85, 95)).save(path)
                refs.append(str(path))
            ip = root / "ip.png"
            Image.new("RGBA", (180, 180), (242, 184, 45, 255)).save(ip)
            base_a = root / "base-a.png"
            base_b = root / "base-b.png"
            Image.new("RGB", (1080, 1920), "#dce8e2").save(base_a)
            Image.new("RGB", (1080, 1920), "#15202b").save(base_b)
            semantic = root / "semantic.json"
            semantic.write_text(json.dumps({
                "schema_version": 2,
                "events": [{
                    "id": "event-1",
                    "transcript_quote": "封面需要主题证据与稳定排版",
                    "viewer_takeaway": "稳定封面来自分层工作流",
                }],
                "cover_direction": {
                    "headline": "稳定生成主题封面",
                    "highlight_terms": ["稳定", "主题"],
                    "eyebrow": "AI 视频工作流",
                    "subtitle": "真人、主题和排版分层生产",
                    "tone": "tutorial",
                    "evidence_event_ids": ["event-1"],
                    "visual_concept": "真人讲解，个人IP辅助展示封面流程",
                    "subject_side": "right",
                    "visual_route": "real_person_ip_hybrid",
                },
            }, ensure_ascii=False), encoding="utf-8")
            output = root / "exports" / "cover.jpg"

            artifacts = produce_cover(
                project={"title": "Fallback", "cover": {
                    "enabled": True,
                    "identity_references": refs[:2],
                    "expression_references": refs[2:],
                    "editorial": {
                        "enabled": True,
                        "template_families": [
                            "bright_tech_tutorial", "dark_high_energy", "thought_leadership_ip",
                        ],
                        "supporting_assets": [{
                            "path": str(ip), "role": "personal_ip",
                            "purpose": "explain the cover workflow",
                            "rights_basis": "project-owned personal IP",
                        }],
                    },
                    "variants": {
                        "A": {"clean_base": str(base_a), "strategy": "topic clarity",
                              "agent_identity_reviewed": True, "agent_expression_reviewed": True},
                        "B": {"clean_base": str(base_b), "strategy": "human curiosity",
                              "agent_identity_reviewed": True, "agent_expression_reviewed": True},
                    },
                }},
                project_root=root,
                semantic_brief=semantic,
                output=output,
                work_dir=root / "work",
                runner=AdapterRunner(root / "adapter-state.json"),
                execute_external=True,
            )

            names = {path.name for path in artifacts}
            self.assertIn("cover-editorial-plan.json", names)
            self.assertIn("cover-a-qa.json", names)
            self.assertIn("cover-b-qa.json", names)
            report = json.loads((root / "work" / "cover-ab-report.json").read_text(encoding="utf-8"))
            self.assertTrue(report["checks"]["variant_a_automated_qa"])
            self.assertTrue(report["checks"]["variant_b_automated_qa"])
            manifest = json.loads(output.with_suffix(".manifest.json").read_text(encoding="utf-8"))
            self.assertTrue(manifest["selection"]["quality_report"])
            self.assertEqual(len(manifest["selection"]["quality_report_sha256"]), 64)

    def test_enhanced_path_does_not_reuse_a_stale_existing_cover_by_path_only(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "exports" / "cover.jpg"
            output.parent.mkdir(parents=True)
            Image.new("RGB", (1080, 1920), "#102030").save(output)
            output.with_suffix(".manifest.json").write_text(json.dumps({
                "schema_version": 3,
                "output": str(output),
                "generation_mode": "reference_guided_regeneration",
            }), encoding="utf-8")
            semantic = root / "semantic.json"
            semantic.write_text(json.dumps({
                "schema_version": 2,
                "events": [{"id": "e1", "transcript_quote": "新的主题证据"}],
                "cover_direction": {
                    "headline": "新的主题封面", "highlight_terms": ["主题"],
                    "visual_concept": "新的主题场景", "evidence_event_ids": ["e1"],
                },
            }, ensure_ascii=False), encoding="utf-8")

            with self.assertRaises(CoverProductionActionRequired) as caught:
                produce_cover(
                    project={"cover": {"editorial": {"enabled": True}}},
                    project_root=root,
                    semantic_brief=semantic,
                    output=output,
                    work_dir=root / "work",
                    runner=AdapterRunner(root / "state.json"),
                    execute_external=False,
                )

            self.assertTrue(any("stale" in item for item in caught.exception.packet["missing"]))

    def test_authentic_frame_route_preserves_source_frame_provenance_without_identity_refs(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            frame = root / "authentic.png"
            Image.new("RGB", (1080, 1920), "#708078").save(frame)
            semantic = root / "semantic.json"
            semantic.write_text(json.dumps({
                "schema_version": 2,
                "events": [{"id": "e1", "transcript_quote": "真实表达本身就是最好的证据"}],
                "cover_direction": {
                    "headline": "真实表达更可信", "highlight_terms": ["真实"],
                    "visual_concept": "保留视频中的自然表达瞬间", "evidence_event_ids": ["e1"],
                    "subject_side": "right", "visual_route": "authentic_frame_editorial",
                },
            }, ensure_ascii=False), encoding="utf-8")
            output = root / "exports" / "cover.jpg"

            produce_cover(
                project={"cover": {
                    "enabled": True,
                    "editorial": {
                        "enabled": True,
                        "authentic_frames": [str(frame)],
                        "template_families": ["cinematic_editorial", "bright_tech_tutorial"],
                    },
                    "variants": {
                        "A": {"strategy": "authentic clarity", "agent_identity_reviewed": True,
                              "agent_expression_reviewed": True},
                        "B": {"strategy": "authentic curiosity", "agent_identity_reviewed": True,
                              "agent_expression_reviewed": True},
                    },
                }},
                project_root=root, semantic_brief=semantic, output=output,
                work_dir=root / "work", runner=AdapterRunner(root / "state.json"),
                execute_external=True,
            )

            manifest = json.loads(output.with_suffix(".manifest.json").read_text(encoding="utf-8"))
            self.assertEqual(manifest["generation_mode"], "authentic_frame_editorial")
            self.assertEqual(manifest["authentic_frames"], [str(frame.resolve())])
            self.assertTrue(manifest["identity_qa"]["authentic_source_pixels"])
            report = json.loads((root / "work" / "cover-ab-report.json").read_text(encoding="utf-8"))
            self.assertTrue(report["checks"]["same_authorized_identity_references"])


if __name__ == "__main__":
    unittest.main()
