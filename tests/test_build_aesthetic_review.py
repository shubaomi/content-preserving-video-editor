from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from aesthetic_qa import validate  # noqa: E402
from build_aesthetic_review import build_review  # noqa: E402
from director_contracts import sha256_file  # noqa: E402


class BuildAestheticReviewTests(unittest.TestCase):
    def test_builds_only_from_hash_bound_user_approval_and_receipts(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "sample.mp4"
            candidate.write_bytes(b"candidate")
            caption = root / "caption-sync.json"
            caption.write_text("{}", encoding="utf-8")
            mix = root / "mix-audibility.json"
            mix.write_text("{}", encoding="utf-8")
            storyboard = root / "storyboard.json"
            storyboard.write_text(json.dumps({"events": [{
                "id": "render-e1",
                "semantic_event_id": "semantic-e1",
                "start": 1.0,
                "end": 4.0,
                "approved_visible_copy": ["核心"],
                "visual_structure": {
                    "dom_structure": "one semantic card",
                    "information_hierarchy": "concept then explanation",
                    "layout_archetype": "semantic comparison",
                    "animation_choreography": "enter hold exit",
                    "use_case": "clarify concept",
                },
            }]}), encoding="utf-8")
            receipt_dir = root / "receipts"
            receipt_dir.mkdir()
            observations = []
            for phase in ("entrance", "mid", "pre_exit", "post_exit"):
                image = root / f"{phase}.png"
                Image.new("RGB", (640, 360), "white").save(image)
                observations.append({
                    "phase": phase,
                    "snapshot": {"path": str(image), "sha256": sha256_file(image)},
                    "visible": phase != "post_exit",
                    "overlay_bbox": {
                        "x": 0.1, "y": 0.1, "width": 0.4, "height": 0.2,
                    } if phase != "post_exit" else {
                        "x": 0, "y": 0, "width": 0, "height": 0,
                    },
                    "crop_status": "inside" if phase != "post_exit" else "not_applicable",
                    "caption_overlap_ratio": 0,
                    "composite_contrast_ratio": 12.0 if phase != "post_exit" else 0,
                })
            receipt = receipt_dir / "semantic-e1.json"
            receipt.write_text(json.dumps({
                "event_id": "semantic-e1",
                "renderer": {"width": 640, "height": 360},
                "phase_observations": observations,
                "strict_check": {"exit_code": 0},
                "status": "pass",
            }), encoding="utf-8")
            basis = root / "user-review.json"
            basis.write_text(json.dumps({
                "schema_version": 1,
                "authority": "user",
                "status": "approved",
                "reviewer": "HongRun",
                "approval_evidence": "User approved the landscape canary",
                "reviewed_media": {"path": str(candidate), "sha256": sha256_file(candidate)},
                "composite_style": {
                    "foreground_rgb": [23, 32, 51],
                    "panel_rgb": [253, 253, 253],
                    "panel_alpha": 0.96,
                },
                "evidence_files": {
                    "caption_sync": str(caption),
                    "audio_mix": str(mix),
                },
            }), encoding="utf-8")
            output = root / "aesthetic-review.json"

            with patch("build_aesthetic_review._full_decode_passes", return_value=True):
                review = build_review(
                    storyboard_path=storyboard,
                    receipt_dir=receipt_dir,
                    review_basis_path=basis,
                    output=output,
                )

            self.assertTrue(output.is_file())
            self.assertEqual(review["review_authority"]["authority"], "user")
            self.assertEqual(validate(
                review,
                json.loads(storyboard.read_text(encoding="utf-8")),
                keyframe_receipt_paths={"semantic-e1": receipt},
                decision_complete=True,
            ), [])

    def test_rejects_agent_authored_or_stale_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            candidate = root / "sample.mp4"
            candidate.write_bytes(b"candidate")
            basis = root / "review.json"
            basis.write_text(json.dumps({
                "authority": "agent",
                "status": "approved",
                "reviewed_media": {"path": str(candidate), "sha256": sha256_file(candidate)},
            }), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "authority=user"):
                build_review(
                    storyboard_path=root / "missing.json",
                    receipt_dir=root / "missing",
                    review_basis_path=basis,
                    output=root / "out.json",
                )
