from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from editable_delivery import (  # noqa: E402
    EditableDeliveryError,
    build_editable_delivery,
    validate_editable_delivery,
)


class EditableDeliveryTests(unittest.TestCase):
    def _inputs(self, root: Path) -> dict[str, Path]:
        automatic = root / "exports" / "final.mp4"
        candidate = root / "work" / "full-hyperframes.mp4"
        srt = root / "edit" / "master.srt"
        ass = root / "work" / "caption-treatment" / "master.ass"
        plan = root / "work" / "caption-treatment" / "plan.json"
        project = root / "hyperframes-full"
        for path, value in (
            (automatic, b"captioned-master"),
            (candidate, b"caption-free-candidate"),
        ):
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(value)
        srt.parent.mkdir(parents=True, exist_ok=True)
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n字幕\n", encoding="utf-8")
        ass.parent.mkdir(parents=True, exist_ok=True)
        ass.write_text("[Script Info]\n[Events]\nDialogue: 0,0:00:00.00,0:00:01.00,CaptionBase,,0,0,0,,字幕\n", encoding="utf-8")
        plan.write_text(json.dumps({"schema_version": 1}), encoding="utf-8")
        project.mkdir(parents=True, exist_ok=True)
        (project / "index.html").write_text("<main data-composition-id='main'></main>", encoding="utf-8")
        (project / "storyboard.json").write_text(json.dumps({"events": []}), encoding="utf-8")
        return {
            "automatic_master": automatic,
            "caption_free_candidate": candidate,
            "caption_srt": srt,
            "caption_ass": ass,
            "caption_style_plan": plan,
            "hyperframes_project": project,
        }

    def test_builds_standard_repair_kit_with_editable_caption_assets(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs = self._inputs(root)
            manifest = build_editable_delivery(
                output_root=root / "work" / "director" / "editable-delivery",
                authorized_root=root,
                **inputs,
            )

            payload = json.loads(manifest.read_text(encoding="utf-8"))
            self.assertEqual(payload["status"], "ready")
            self.assertFalse(payload["interoperability"]["burned_master_text_editable"])
            self.assertFalse(payload["interoperability"]["native_editor_draft_generated"])
            self.assertEqual(Path(payload["captions"]["srt"]["path"]).name, "master.srt")
            self.assertEqual(Path(payload["captions"]["ass"]["path"]).name, "master.ass")
            self.assertEqual(validate_editable_delivery(manifest), [])

    def test_hash_drift_or_reusing_captioned_master_as_candidate_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            inputs = self._inputs(root)
            with self.assertRaisesRegex(EditableDeliveryError, "distinct"):
                build_editable_delivery(
                    output_root=root / "work" / "director" / "editable-delivery",
                    authorized_root=root,
                    **{**inputs, "caption_free_candidate": inputs["automatic_master"]},
                )
            manifest = build_editable_delivery(
                output_root=root / "work" / "director" / "editable-delivery",
                authorized_root=root,
                **inputs,
            )
            Path(json.loads(manifest.read_text(encoding="utf-8"))["captions"]["srt"]["path"]).write_text(
                "changed", encoding="utf-8",
            )
            self.assertTrue(any("srt" in error and "stale" in error
                                for error in validate_editable_delivery(manifest)))

    @unittest.skipUnless(os.name == "nt", "Windows Junction regression")
    def test_output_root_junction_cannot_escape_project(self) -> None:
        import subprocess

        with tempfile.TemporaryDirectory() as temp, tempfile.TemporaryDirectory() as outside_temp:
            root = Path(temp)
            outside = Path(outside_temp)
            inputs = self._inputs(root)
            output = root / "work" / "director" / "editable-delivery"
            output.parent.mkdir(parents=True, exist_ok=True)
            subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(output), str(outside)],
                check=True, capture_output=True, text=True,
            )
            with self.assertRaises(EditableDeliveryError):
                build_editable_delivery(
                    output_root=output, authorized_root=root, **inputs,
                )
            self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
