from __future__ import annotations

import sys
import tempfile
import unittest
import json
import hashlib
import os
import subprocess
from pathlib import Path
from PIL import Image


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director_contracts import sha256_file  # noqa: E402
from portrait_motion_recipes import (  # noqa: E402
    build_portrait_renderer_payload,
    load_portrait_recipe_registry,
    recipe_fingerprint,
)
from validate_portrait_components_runtime import (  # noqa: E402
    CAPTURE_TOOL,
    PHASES,
    SEEK_SEQUENCE,
    _materialize_http_assets,
    _renderer_payload_errors,
    _fixture_html,
    capture,
    validate_portrait_runtime_evidence,
)


class PortraitComponentsRuntimeTests(unittest.TestCase):
    def _compiled_payload(self) -> tuple[object, dict]:
        from tests import test_portrait_motion_recipes as fixture_module

        fixture = fixture_module.PortraitMotionRecipeTests("run")
        fixture.setUp()
        payload = build_portrait_renderer_payload(
            fixture.compile(), load_portrait_recipe_registry(),
            project_root=fixture.root / "hf-project",
        )
        return fixture, payload

    @unittest.skipUnless(os.name == "nt", "NTFS junction regression is Windows-specific")
    def test_runtime_capture_rejects_assets_junction_without_external_writes(self) -> None:
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside_folder:
            output = Path(folder) / "runtime"
            output.mkdir()
            outside = Path(outside_folder).resolve()
            junction = output / "assets"
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                capture_output=True, text=True, check=False,
            )
            if result.returncode != 0:
                self.skipTest(f"cannot create NTFS junction: {result.stderr or result.stdout}")
            gsap = Path(folder) / "gsap.min.js"
            gsap.write_text("window.gsap={};", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "redirected"):
                capture(output, hyperframes_gsap=gsap)
            self.assertEqual(list(outside.iterdir()), [])

    @unittest.skipUnless(os.name == "nt", "NTFS junction regression is Windows-specific")
    def test_runtime_capture_rejects_output_root_junction(self) -> None:
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside_folder:
            junction = Path(folder) / "runtime"
            outside = Path(outside_folder).resolve()
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                capture_output=True, text=True, check=False,
            )
            if result.returncode != 0:
                self.skipTest(f"cannot create NTFS junction: {result.stderr or result.stdout}")
            with self.assertRaisesRegex(ValueError, "root is redirected"):
                capture(junction)
            self.assertEqual(list(outside.iterdir()), [])

    def _passing_runtime_evidence(
        self, root: Path, payload: dict, payload_path: Path,
    ) -> dict:
        registry = {
            row["recipe_id"]: row for row in load_portrait_recipe_registry()["recipes"]
        }
        component_assets = []
        for source in (
            ROOT / "references" / "hyperframes-portrait-components-v2.js",
            ROOT / "references" / "hyperframes-portrait-components-v2.css",
        ):
            component_assets.append({
                "path": str(source.resolve()), "sha256": sha256_file(source),
            })
        recipes = []
        for index, event in enumerate(payload["events"]):
            phase_rows = []
            hold_path = root / f"{index:03d}-hold.png"
            for phase in PHASES:
                snapshot = hold_path if phase == "hold" else root / f"{index:03d}-{phase}.png"
                Image.new("RGB", (540, 960), (10 + index, 24, 24)).save(snapshot)
                specifics = {
                    "gesture_points": None,
                    "semantic_asset_hash": None,
                    "semantic_asset_loaded": None,
                    "semantic_asset_protocol": None,
                    "semantic_asset_current_src": None,
                    "subject_evidence": None,
                    "chapter_boundary": None,
                    "source_camera_active": "false",
                }
                bindings = event["bindings"]
                if event["recipeId"] == "PBM-03":
                    specifics["gesture_points"] = str(len(bindings["gestureBinding"]["points"]))
                if event["recipeId"] in {"PBM-02", "PBM-05"}:
                    specifics["subject_evidence"] = bindings["subjectBinding"]["evidence_id"]
                if event["recipeId"] == "PBM-05":
                    specifics["source_camera_active"] = "true"
                if event["recipeId"] == "PBM-06":
                    specifics["semantic_asset_hash"] = bindings["assetRef"]["sha256"]
                    specifics["semantic_asset_loaded"] = True
                    specifics["semantic_asset_protocol"] = "http:"
                    specifics["semantic_asset_current_src"] = (
                        "http://127.0.0.1:12345/" + bindings["assetUrl"].removeprefix("./")
                    )
                if event["recipeId"] == "PBM-07":
                    specifics["chapter_boundary"] = bindings["chapterBoundaryBinding"]["evidence_id"]
                phase_rows.append({
                    "phase": phase, "event_phase": phase,
                    "recipe": event["recipeId"],
                    "opacity": 0.0 if phase == "post_exit" else 1.0,
                    "primary_bbox": {"x": 20, "y": 20, "width": 100, "height": 40},
                    "painted_bbox": {"x": 20, "y": 20, "width": 100, "height": 40},
                    "inside_canvas": True, "caption_clear": True,
                    "visible_copy": list(event["visibleCopy"]),
                    "recipe_specific": specifics,
                    "snapshot": {"path": str(snapshot.resolve()), "sha256": sha256_file(snapshot)},
                })
            repeated = root / f"{index:03d}-hold-repeat.png"
            Image.open(hold_path).save(repeated)
            recipes.append({
                "event_id": event["eventId"], "recipe_id": event["recipeId"],
                "fingerprints": recipe_fingerprint(registry[event["recipeId"]]),
                "phases": phase_rows,
                "seek_sequence": list(SEEK_SEQUENCE),
                "seek_repeat_snapshot": {
                    "path": str(repeated.resolve()), "sha256": sha256_file(repeated),
                },
                "seek_repeat_hold_sha256": sha256_file(repeated),
                "seek_repeat_reference_sha256": sha256_file(hold_path),
                "seek_repeat_mae": 0.0, "seek_repeat_matches": True,
            })
        negative = []
        cases_by_recipe = {
            "PBM-02": ("missing", "wrong_kind", "stale_hash", "out_of_window"),
            "PBM-03": ("missing", "wrong_kind", "stale_hash", "out_of_window"),
            "PBM-05": ("missing", "wrong_kind", "stale_hash", "out_of_window"),
            "PBM-06": ("missing", "stale_hash"),
            "PBM-07": ("missing", "wrong_kind", "stale_hash", "out_of_window"),
        }
        for event in payload["events"]:
            negative.extend({
                "event_id": event["eventId"], "recipe_id": event["recipeId"],
                "case": case, "rejected": True, "error": "rejected",
            } for case in cases_by_recipe.get(event["recipeId"], ()))
        return {
            "schema_version": 2, "status": "pass",
            "capture_tool": {"path": str(CAPTURE_TOOL), "sha256": sha256_file(CAPTURE_TOOL)},
            "renderer_payload": {
                "path": str(payload_path.resolve()), "sha256": sha256_file(payload_path),
            },
            "component_assets": component_assets,
            "recipes": recipes,
            "required_binding_negative_checks": negative,
            "errors": [],
            "claims": {
                "hyperframes_timeline_registered": True,
                "seek_safety_verified": True,
                "required_recipe_bindings_fail_closed": True,
                "compiler_renderer_payload_consumed": True,
            },
        }

    def test_hyperframes_fixture_registers_real_gsap_timeline(self) -> None:
        fixture, payload = self._compiled_payload()
        self.addCleanup(fixture.tearDown)
        html = _fixture_html(timeline_enabled=True, renderer_payload=payload)
        self.assertIn("assets/gsap.min.js", html)
        self.assertIn("window.__timelines['portrait-fixture']=master", html)
        self.assertIn("gsap.timeline({paused:true})", html)
        self.assertIn("window.fixtureSeek", html)
        self.assertIn("master.seek(offsets[eventId]+time,false)", html)
        self.assertNotIn("fixtureShow", html)
        self.assertNotIn(".call(", html)
        self.assertNotIn("data-no-timeline", html)
        self.assertIn('data-duration="18"', html)

    def test_fixture_exercises_required_recipe_bindings(self) -> None:
        fixture, payload = self._compiled_payload()
        self.addCleanup(fixture.tearDown)
        html = _fixture_html(timeline_enabled=True, renderer_payload=payload)
        self.assertIn("fixtureRequiredBindingErrors", html)
        self.assertIn("wrong_kind", html)
        self.assertIn("stale_hash", html)
        self.assertIn("out_of_window", html)
        for recipe_id in ("PBM-02", "PBM-03", "PBM-05", "PBM-06", "PBM-07"):
            self.assertIn(f'"recipeId":"{recipe_id}"', html)

    def test_fixture_consumes_compiler_renderer_payload_without_hand_authored_bindings(self) -> None:
        fixture, payload = self._compiled_payload()
        self.addCleanup(fixture.tearDown)
        html = _fixture_html(timeline_enabled=True, renderer_payload=payload)
        self.assertIn("window.fixturePayload", html)
        self.assertIn(payload["payload_sha256"], html)
        self.assertNotIn("function bindingsFor", html)
        for row in payload["events"]:
            self.assertIn(row["eventId"], html)

    def test_missing_gsap_is_unverified_not_a_false_seek_pass(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            result = capture(Path(temporary))
            self.assertEqual(result["status"], "unverified")
            self.assertFalse(result["claims"]["seek_safety_verified"])
            self.assertIn("GSAP", " ".join(result["errors"]))

    def test_gsap_capture_requires_a_compiler_renderer_payload(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            gsap = root / "gsap.min.js"
            gsap.write_text("window.gsap={};", encoding="utf-8")
            result = capture(root / "out", hyperframes_gsap=gsap)
            self.assertEqual(result["status"], "unverified")
            self.assertIn("renderer payload", " ".join(result["errors"]).lower())

    def test_runtime_fixture_materializes_http_semantic_asset_path(self) -> None:
        fixture, payload = self._compiled_payload()
        self.addCleanup(fixture.tearDown)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload_path = root / "portrait-renderer-payload.json"
            payload_path.write_text(json.dumps(payload), encoding="utf-8")
            _materialize_http_assets(root / "runtime", payload)
            event = next(row for row in payload["events"] if row["recipeId"] == "PBM-06")
            copied = root / "runtime" / event["bindings"]["assetUrl"].removeprefix("./")
            self.assertTrue(copied.is_file())
            self.assertEqual(sha256_file(copied), event["bindings"]["assetRef"]["sha256"])

    def test_handwritten_runtime_evidence_cannot_impersonate_browser_capture(self) -> None:
        fixture, payload = self._compiled_payload()
        self.addCleanup(fixture.tearDown)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload_path = root / "portrait-renderer-payload.json"
            payload_path.write_text(json.dumps(payload), encoding="utf-8")
            evidence = self._passing_runtime_evidence(root, payload, payload_path)
            self.assertTrue(validate_portrait_runtime_evidence(evidence, payload_path))

    def test_runtime_evidence_rejects_missing_phase_and_stale_snapshot(self) -> None:
        fixture, payload = self._compiled_payload()
        self.addCleanup(fixture.tearDown)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload_path = root / "portrait-renderer-payload.json"
            payload_path.write_text(json.dumps(payload), encoding="utf-8")
            evidence = self._passing_runtime_evidence(root, payload, payload_path)
            evidence["recipes"][0]["phases"].pop()
            self.assertTrue(validate_portrait_runtime_evidence(evidence, payload_path))
            evidence = self._passing_runtime_evidence(root, payload, payload_path)
            Path(evidence["recipes"][0]["phases"][0]["snapshot"]["path"]).write_bytes(b"stale")
            self.assertTrue(validate_portrait_runtime_evidence(evidence, payload_path))

    def test_runtime_evidence_rejects_forged_visible_copy_and_recipe_semantics(self) -> None:
        fixture, payload = self._compiled_payload()
        self.addCleanup(fixture.tearDown)
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            payload_path = root / "portrait-renderer-payload.json"
            payload_path.write_text(json.dumps(payload), encoding="utf-8")
            evidence = self._passing_runtime_evidence(root, payload, payload_path)
            evidence["recipes"][0]["phases"][0]["visible_copy"] = ["伪造"]
            self.assertTrue(validate_portrait_runtime_evidence(evidence, payload_path))
            evidence = self._passing_runtime_evidence(root, payload, payload_path)
            pbm03 = next(row for row in evidence["recipes"] if row["recipe_id"] == "PBM-03")
            next(phase for phase in pbm03["phases"] if phase["phase"] == "hold")["recipe_specific"]["gesture_points"] = "999"
            self.assertTrue(validate_portrait_runtime_evidence(evidence, payload_path))

    def test_renderer_payload_rejects_unbound_http_asset_url(self) -> None:
        fixture, payload = self._compiled_payload()
        self.addCleanup(fixture.tearDown)
        event = next(row for row in payload["events"] if row["recipeId"] == "PBM-06")
        event["bindings"]["assetUrl"] = "./assets/portrait-brand-v2/media/does-not-exist.png"
        event["expectedBindings"] = json.loads(json.dumps(event["bindings"]))
        payload["payload_sha256"] = hashlib.sha256(json.dumps({
            key: value for key, value in payload.items() if key != "payload_sha256"
        }, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
        self.assertTrue(_renderer_payload_errors(payload))

    def test_malformed_renderer_payload_fails_closed(self) -> None:
        malformed = {
            "schema_version": 1,
            "component_api": "hongrun-portrait-components-v2",
            "events": [{
                "eventId": "event-e1", "semanticEventId": "e1",
                "recipeId": "PBM-01", "bindings": [],
                "expectedBindings": {}, "authorityDigests": {},
            }],
        }
        malformed["payload_sha256"] = hashlib.sha256(json.dumps(
            malformed, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode()).hexdigest()
        self.assertTrue(_renderer_payload_errors(malformed))
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "payload.json"
            path.write_text(json.dumps(malformed), encoding="utf-8")
            self.assertTrue(validate_portrait_runtime_evidence({}, path))

    def test_component_source_contains_recipe_specific_runtime_bindings(self) -> None:
        javascript = (ROOT / "references" / "hyperframes-portrait-components-v2.js").read_text(encoding="utf-8")
        for marker in (
            "gestureBinding.points", "sourceTargetId", "pbm-semantic-asset",
            "chapterBoundaryBinding", "pbm-subject-depth", "pbm-resolution-bloom",
        ):
            self.assertIn(marker, javascript)
