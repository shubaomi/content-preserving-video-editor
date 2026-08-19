from __future__ import annotations

import json
import hashlib
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from nle_layer_materializer import (  # noqa: E402
    NleLayerMaterializationError,
    hyperframes_frame_rate_argument,
    build_event_overlay_project,
    validate_motion_layer_manifest,
    validate_alpha_evidence,
)
import nle_layer_materializer as materializer  # noqa: E402


class NleLayerMaterializerTests(unittest.TestCase):
    def _alpha_receipt(
        self, root: Path, video: Path, *, width: int = 20, height: int = 20,
        duration: float = 2.0,
    ) -> tuple[Path, dict[str, object]]:
        evidence_root = root / "evidence"
        evidence_root.mkdir(parents=True, exist_ok=True)
        midpoint = evidence_root / "midpoint.png"
        post_exit = evidence_root / "post-exit.png"
        middle = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        for x in range(width // 4, 3 * width // 4):
            for y in range(height // 4, 3 * height // 4):
                middle.putpixel((x, y), (10, 220, 200, 255))
        middle.save(midpoint)
        Image.new("RGBA", (width, height), (0, 0, 0, 0)).save(post_exit)
        composites = []
        for name, background in materializer._composite_backgrounds(width, height).items():
            path = evidence_root / f"composite-{name}.png"
            background.alpha_composite(middle)
            background.convert("RGB").save(path)
            composites.append({"kind": name, "path": path.name,
                               "sha256": hashlib.sha256(path.read_bytes()).hexdigest()})
        probe: dict[str, object] = {
            "codec_name": "prores", "profile": "4444",
            "width": width, "height": height, "pixel_format": "yuva444p10le",
            "frame_rate": 25.0, "duration_seconds": duration, "alpha_mode": None,
        }
        evidence = {
            "schema_version": 1, "kind": "nle_motion_alpha_evidence", "status": "pass",
            "video_sha256": hashlib.sha256(video.read_bytes()).hexdigest(), "probe": probe,
            "midpoint": {"path": midpoint.name,
                         "sha256": hashlib.sha256(midpoint.read_bytes()).hexdigest(),
                         "width": width, "height": height, "minimum_alpha": 0,
                         "maximum_alpha": 255, "visible_ratio": 0.25},
            "post_exit": {"path": post_exit.name,
                          "sha256": hashlib.sha256(post_exit.read_bytes()).hexdigest(),
                          "width": width, "height": height, "minimum_alpha": 0,
                          "maximum_alpha": 0, "visible_ratio": 0.0},
            "composites": composites,
        }
        evidence["integrity_sha256"] = materializer._stable_hash(evidence)
        path = evidence_root / "alpha-evidence.json"
        path.write_text(json.dumps(evidence), encoding="utf-8")
        return path, probe

    def test_hyperframes_frame_rate_uses_integer_or_exact_ntsc_rational(self) -> None:
        self.assertEqual(hyperframes_frame_rate_argument(25.0), "25")
        self.assertEqual(hyperframes_frame_rate_argument(30000 / 1001), "30000/1001")
        with self.assertRaisesRegex(NleLayerMaterializationError, "frame rate"):
            hyperframes_frame_rate_argument(float("nan"))

    def _project(self, root: Path) -> Path:
        project = root / "hyperframes"
        assets = project / "assets"
        assets.mkdir(parents=True)
        (assets / "component.js").write_text("export const ok=true;", encoding="utf-8")
        (assets / "candidate-source.mp4").write_bytes(b"source-video")
        (assets / "event-cutaway.webm").write_bytes(b"event-media")
        payload = {
            "schema_version": 1,
            "component_api": "hongrun-portrait-components-v2",
            "events": [{
                "recipeId": "PBM-01",
                "eventId": "render:one",
                "semanticEventId": "semantic:one",
                "contractId": "portrait:one",
                "contractSha256": "1" * 64,
                "visibleCopy": ["重点"],
                "supportingLayers": ["ambient_light_field"],
                "sourceWindow": {"start_seconds": 10.0, "end_seconds": 12.0},
                "outputWindow": {"start_seconds": 3.0, "end_seconds": 5.0},
                "bindings": {}, "expectedBindings": {}, "authorityDigests": {},
            }],
        }
        payload["payload_sha256"] = "pending"
        (project / "renderer-payload.json").write_text(
            json.dumps(payload, ensure_ascii=False), encoding="utf-8",
        )
        (project / "index.html").write_text(
            """<!doctype html><html><head></head><body>\n"
            "<div id=\"root\" data-duration=\"8.000\">\n"
            "<video id=\"a-roll\" src=\"assets/candidate-source.mp4\"></video>\n"
            "<audio id=\"a-roll-audio\" src=\"assets/candidate-source.mp4\"></audio>\n"
            "</div><script>const payload={\"events\":[]};\nconst master={};</script>"
            "</body></html>""",
            encoding="utf-8",
        )
        return project

    def test_event_project_is_transparent_single_event_and_zero_based(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project = self._project(root)
            output = root / "generated" / "event-one"
            event = json.loads((project / "renderer-payload.json").read_text(encoding="utf-8"))["events"][0]

            result = build_event_overlay_project(
                source_project=project,
                output_project=output,
                event=event,
                authorized_root=root,
            )

            html = (output / "index.html").read_text(encoding="utf-8")
            payload = json.loads((output / "renderer-payload.json").read_text(encoding="utf-8"))
            self.assertNotIn("candidate-source.mp4", html)
            self.assertIn("background:transparent!important", html)
            self.assertEqual(payload["events"][0]["outputWindow"], {
                "start_seconds": 0.0, "end_seconds": 2.0,
            })
            self.assertEqual(result["duration_seconds"], 2.0)
            self.assertFalse((output / "assets" / "candidate-source.mp4").exists())
            self.assertTrue((output / "assets" / "event-cutaway.webm").is_file())

    def test_manifest_rejects_stale_alpha_evidence_and_missing_source_archive(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = root / "motion-layer-manifest.json"
            manifest.write_text(json.dumps({
                "schema_version": 1,
                "kind": "nle_motion_layer_materialization",
                "status": "pass",
                "source_project": {"path": str(root / "source"), "tree_sha256": "0" * 64},
                "renderer_payload": {"path": str(root / "payload.json"), "sha256": "0" * 64},
                "source_project_archive": {"path": str(root / "source.zip"), "sha256": "0" * 64},
                "events": [],
                "implementation_sha256": "0" * 64,
                "integrity_sha256": "0" * 64,
            }), encoding="utf-8")

            errors = validate_motion_layer_manifest(manifest)
            self.assertTrue(any("source project" in error for error in errors))
            self.assertTrue(any("archive" in error for error in errors))

    def test_manifest_rejects_renderer_inventory_and_source_archive_substitution(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = self._project(root)
            payload = json.loads((source / "renderer-payload.json").read_text(encoding="utf-8"))
            event = payload["events"][0]
            output = root / "output"; output.mkdir()
            overlay = output / "overlay.mov"; overlay.write_bytes(b"alpha-video")
            evidence, probe = self._alpha_receipt(output, overlay)
            archive = output / "source.zip"
            materializer._archive_project(source, archive)
            expected_payload_hash, start, end = materializer._expected_event_payload(payload, event)
            manifest = {
                "schema_version": 1, "kind": "nle_motion_layer_materialization",
                "status": "pass",
                "source_project": {"path": str(source),
                                   "tree_sha256": materializer.source_project_tree_sha256(source)},
                "renderer_payload": {"path": str(source / "renderer-payload.json"),
                                     "sha256": materializer.sha256_file(source / "renderer-payload.json")},
                "source_project_archive": {"path": archive.name,
                                           "sha256": materializer.sha256_file(archive)},
                "events": [{
                    "semantic_event_id": event["semanticEventId"],
                    "render_event_id": event["eventId"],
                    "payload_sha256": expected_payload_hash,
                    "timeline": {"start_seconds": start, "end_seconds": end,
                                 "frame_rate": 25.0},
                    "overlay": {"path": overlay.name,
                                "sha256": materializer.sha256_file(overlay)},
                    "alpha_evidence": {"path": str(evidence.relative_to(output)),
                                       "sha256": materializer.sha256_file(evidence)},
                    "video": {"codec_name": "prores", "profile": "4444",
                              "width": 20, "height": 20,
                              "pixel_format": "yuva444p10le", "alpha_status": "verified",
                              "decode_receipt": {"path": str(evidence.relative_to(output)),
                                                 "sha256": materializer.sha256_file(evidence)}},
                }],
                "implementation_sha256": materializer.sha256_file(materializer._IMPLEMENTATION),
            }
            manifest["integrity_sha256"] = materializer._stable_hash(manifest)
            manifest_path = output / "motion-layer-manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            with patch("nle_layer_materializer._probe_video", return_value=probe):
                self.assertEqual(validate_motion_layer_manifest(manifest_path), [])

                manifest["events"][0]["semantic_event_id"] = "forged"
                manifest["integrity_sha256"] = materializer._stable_hash(manifest)
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                self.assertTrue(any("inventory" in error for error in
                                    validate_motion_layer_manifest(manifest_path)))

                manifest["events"][0]["semantic_event_id"] = event["semanticEventId"]
                with zipfile.ZipFile(archive, "w") as forged:
                    forged.writestr("unrelated.txt", b"not the source project")
                manifest["source_project_archive"]["sha256"] = materializer.sha256_file(archive)
                manifest["integrity_sha256"] = materializer._stable_hash(manifest)
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                self.assertTrue(any("archive differs" in error for error in
                                    validate_motion_layer_manifest(manifest_path)))

    def test_alpha_evidence_is_recomputed_from_current_video_and_images(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            video = root / "overlay.mov"; video.write_bytes(b"alpha-video")
            midpoint = root / "midpoint.png"
            post_exit = root / "post-exit.png"
            image = Image.new("RGBA", (20, 20), (0, 0, 0, 0))
            for x in range(5, 15):
                for y in range(5, 15):
                    image.putpixel((x, y), (10, 220, 200, 255))
            image.save(midpoint)
            Image.new("RGBA", (20, 20), (0, 0, 0, 0)).save(post_exit)
            composites = []
            for name, background in materializer._composite_backgrounds(20, 20).items():
                path = root / f"composite-{name}.png"
                background.alpha_composite(image)
                background.convert("RGB").save(path)
                composites.append({"kind": name, "path": path.name,
                                   "sha256": __import__("hashlib").sha256(path.read_bytes()).hexdigest()})
            evidence = {
                "schema_version": 1, "kind": "nle_motion_alpha_evidence", "status": "pass",
                "video_sha256": __import__("hashlib").sha256(video.read_bytes()).hexdigest(),
                "probe": {"width": 20, "height": 20, "pixel_format": "yuva444p10le",
                          "codec_name": "prores", "profile": "4444",
                          "frame_rate": 25.0, "duration_seconds": 1.0, "alpha_mode": None},
                "midpoint": {"path": midpoint.name,
                             "sha256": __import__("hashlib").sha256(midpoint.read_bytes()).hexdigest(),
                             "width": 20, "height": 20, "minimum_alpha": 0,
                             "maximum_alpha": 255, "visible_ratio": 0.25},
                "post_exit": {"path": post_exit.name,
                              "sha256": __import__("hashlib").sha256(post_exit.read_bytes()).hexdigest(),
                              "width": 20, "height": 20, "minimum_alpha": 0,
                              "maximum_alpha": 0, "visible_ratio": 0.0},
                "composites": composites,
            }
            evidence["integrity_sha256"] = __import__("hashlib").sha256(json.dumps(
                evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            evidence_path = root / "alpha-evidence.json"
            evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
            expected_video = {"codec_name": "prores", "profile": "4444",
                              "width": 20, "height": 20,
                              "pixel_format": "yuva444p10le", "alpha_status": "verified"}
            with patch("nle_layer_materializer._probe_video", return_value=evidence["probe"]):
                self.assertEqual(validate_alpha_evidence(
                    evidence_path, overlay=video, expected_video=expected_video,
                    expected_duration=1.0, expected_frame_rate=25.0,
                ), [])
                evidence["midpoint"]["visible_ratio"] = 0.9
                evidence["integrity_sha256"] = __import__("hashlib").sha256(json.dumps(
                    {key: value for key, value in evidence.items() if key != "integrity_sha256"},
                    ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")).hexdigest()
                evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
                self.assertTrue(any("midpoint" in error for error in validate_alpha_evidence(
                    evidence_path, overlay=video, expected_video=expected_video,
                    expected_duration=1.0, expected_frame_rate=25.0,
                )))

    def test_event_project_rejects_malformed_or_out_of_range_window(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            project = self._project(root)
            event = json.loads((project / "renderer-payload.json").read_text(encoding="utf-8"))["events"][0]
            event["outputWindow"] = {"start_seconds": True, "end_seconds": 1.0}
            with self.assertRaisesRegex(NleLayerMaterializationError, "window"):
                build_event_overlay_project(
                    source_project=project,
                    output_project=root / "generated",
                    event=event,
                    authorized_root=root,
                )

    @unittest.skipUnless(os.name == "nt", "NTFS junction regression is Windows-specific")
    def test_source_and_output_junctions_are_rejected_without_external_writes(self) -> None:
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside_folder:
            root = Path(folder)
            outside = Path(outside_folder)
            actual = self._project(outside)
            source_link = root / "source-link"
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(source_link), str(actual)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                self.skipTest("unable to create an NTFS junction")
            event = json.loads((actual / "renderer-payload.json").read_text(encoding="utf-8"))["events"][0]
            with self.assertRaisesRegex(NleLayerMaterializationError, "redirected"):
                build_event_overlay_project(
                    source_project=source_link, output_project=root / "generated" / "event",
                    event=event, authorized_root=root,
                )

            local = self._project(root / "local")
            output_parent = root / "generated"
            target_outside = outside / "escaped"
            target_outside.mkdir()
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(output_parent), str(target_outside)],
                capture_output=True, text=True,
            )
            if result.returncode != 0:
                self.skipTest("unable to create an output NTFS junction")
            local_event = json.loads((local / "renderer-payload.json").read_text(encoding="utf-8"))["events"][0]
            with self.assertRaises((NleLayerMaterializationError, materializer.SafeGeneratedOutputError)):
                build_event_overlay_project(
                    source_project=local, output_project=output_parent / "event",
                    event=local_event, authorized_root=root,
                )
            self.assertEqual(list(target_outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
