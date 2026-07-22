from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cover_quality import evaluate_cover_candidate  # noqa: E402
from director_contracts import sha256_file  # noqa: E402


class CoverQualityTests(unittest.TestCase):
    def _fixture(self, root: Path) -> tuple[Path, Path, Path]:
        image = root / "cover.jpg"
        Image.new("RGB", (1080, 1920), "#17202a").save(image, quality=95)
        plan = root / "plan.json"
        plan.write_text(json.dumps({
            "schema_version": 1,
            "headline": {"text": "稳定生成主题封面", "highlight_terms": ["稳定"]},
            "evidence": {"event_ids": ["event-1"], "quotes": ["稳定生成主题封面"]},
            "variants": {"A": {"template_family": "dark_high_energy"}},
            "supporting_assets": [],
        }, ensure_ascii=False), encoding="utf-8")
        manifest = root / "cover.manifest.json"
        manifest.write_text(json.dumps({
            "schema_version": 4,
            "output": str(image.resolve()),
            "editorial_plan": str(plan.resolve()),
            "editorial_plan_sha256": sha256_file(plan),
            "variant": "A",
            "template_family": "dark_high_energy",
            "typography": {
                "method": "Pillow local deterministic text",
                "title": "稳定生成主题封面",
                "highlight_terms": ["稳定"],
                "line_count": 2,
                "lines": ["稳定生成", "主题封面"],
                "minimum_thumbnail_font_px": 13.0,
            },
            "layout": {
                "safe_bounds": [90, 110, 990, 1810],
                "decorative_bounds": [40, 100, 680, 900],
                "boxes": {
                    "title": [100, 240, 720, 500],
                    "label": [100, 160, 380, 220],
                },
                "subject_box": [740, 260, 1030, 1500],
            },
            "topic_evidence": {"event_ids": ["event-1"]},
        }, ensure_ascii=False), encoding="utf-8")
        return image, plan, manifest

    def test_passes_safe_exact_local_typography_and_writes_thumbnail(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image, plan, manifest = self._fixture(root)
            thumbnail = root / "thumbnail.jpg"
            report_path = root / "cover-qa.json"

            report = evaluate_cover_candidate(
                image=image,
                manifest_path=manifest,
                plan_path=plan,
                variant="A",
                output=report_path,
                thumbnail=thumbnail,
            )

            self.assertTrue(report["automated_passed"])
            self.assertEqual(report["identity_user_approval"], "pending")
            self.assertTrue(thumbnail.is_file())
            self.assertEqual(json.loads(report_path.read_text(encoding="utf-8")), report)

    def test_blocks_out_of_bounds_or_subject_colliding_title(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image, plan, manifest = self._fixture(root)
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["layout"]["boxes"]["title"] = [700, 220, 1100, 620]
            manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            report = evaluate_cover_candidate(
                image=image,
                manifest_path=manifest,
                plan_path=plan,
                variant="A",
                output=root / "qa.json",
                thumbnail=root / "thumb.jpg",
            )

            self.assertFalse(report["automated_passed"])
            self.assertFalse(report["checks"]["all_layout_boxes_inside_safe_bounds"])
            self.assertFalse(report["checks"]["title_avoids_subject"])

    def test_blocks_decorative_panel_that_intrudes_into_subject(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image, plan, manifest = self._fixture(root)
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["layout"]["decorative_bounds"] = [40, 100, 820, 1000]
            manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            report = evaluate_cover_candidate(
                image=image, manifest_path=manifest, plan_path=plan, variant="A",
                output=root / "qa.json", thumbnail=root / "thumb.jpg",
            )

            self.assertFalse(report["automated_passed"])
            self.assertFalse(report["checks"]["decoration_avoids_subject"])

    def test_blocks_highlight_phrase_split_across_lines(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            image, plan, manifest = self._fixture(root)
            plan_data = json.loads(plan.read_text(encoding="utf-8"))
            plan_data["headline"]["highlight_terms"] = ["主题"]
            plan.write_text(json.dumps(plan_data, ensure_ascii=False), encoding="utf-8")
            data = json.loads(manifest.read_text(encoding="utf-8"))
            data["editorial_plan_sha256"] = sha256_file(plan)
            data["typography"]["highlight_terms"] = ["主题"]
            data["typography"]["lines"] = ["稳定生成主", "题封面"]
            manifest.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

            report = evaluate_cover_candidate(
                image=image, manifest_path=manifest, plan_path=plan, variant="A",
                output=root / "qa.json", thumbnail=root / "thumb.jpg",
            )

            self.assertFalse(report["automated_passed"])
            self.assertFalse(report["checks"]["highlight_terms_are_not_split"])


if __name__ == "__main__":
    unittest.main()
