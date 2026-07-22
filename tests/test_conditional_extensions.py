from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from conditional_extensions import _validate_output, route_extensions, run_extension_adapters  # noqa: E402
from director_adapters import AdapterRunner  # noqa: E402


class ConditionalExtensionTests(unittest.TestCase):
    def test_each_conditional_backend_has_a_domain_output_contract(self) -> None:
        valid = {
            "b_roll": ({"events": [{"event_id": "e1", "target_frame_match": True,
                                      "asset_frame_match": True, "integration_mode": "pip",
                                      "safety": {name: True for name in
                                                 ("caption", "face", "hands", "product", "text", "logo")}}]},
                       {"event_ids": ["e1"]}),
            "multicam": ({"alignment": {"method": "audio_correlation", "verified": True},
                           "sources": [{"offset_seconds": 0, "evidence": "wave-a"},
                                       {"offset_seconds": 0.2, "evidence": "wave-b"}],
                           "cut_points": [{"verified": True}]}, {}),
            "voice_isolation": ({"impairment_evidence": True, "speech_preserved": True,
                                  "output_sha256": "a" * 64,
                                  "quality": {"before_intelligibility": 0.6,
                                              "after_intelligibility": 0.8}}, {}),
            "localization": ({"terminology": [], "segments": [{"source_start": 0,
                                                                  "source_end": 1,
                                                                  "translated_text": "hello",
                                                                  "reflection_passed": True,
                                                                  "alignment_passed": True}]}, {}),
        }
        for name, (payload, route) in valid.items():
            with self.subTest(name=name):
                self.assertEqual(_validate_output(name, payload, route), [])
                self.assertTrue(_validate_output(name, {}, route))

    def test_all_extensions_are_disabled_by_default(self) -> None:
        routes = route_extensions({}, {}, {})
        self.assertTrue(all(row["status"] == "disabled" for row in routes.values()))

    def test_enabled_extensions_still_require_content_evidence(self) -> None:
        project = {"extensions": {
            "b_roll": {"enabled": True}, "multicam": {"enabled": True},
            "voice_isolation": {"enabled": True}, "localization": {"enabled": True},
        }}
        routes = route_extensions(project, {}, {"events": []})
        self.assertEqual(routes["b_roll"]["status"], "not_applicable")
        self.assertEqual(routes["multicam"]["status"], "action_required")
        self.assertEqual(routes["voice_isolation"]["status"], "not_applicable")
        self.assertEqual(routes["localization"]["status"], "action_required")

    def test_configured_adapter_runs_and_unconfigured_adapter_is_truthful(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "broll.json"
            payload = {"events": [{"event_id": "e1", "target_frame_match": True,
                                     "asset_frame_match": True, "integration_mode": "pip",
                                     "safety": {"caption": True, "face": True, "hands": True,
                                                "product": True, "text": True, "logo": True}}]}
            command = [sys.executable, "-c", (
                "import pathlib; pathlib.Path(r'%s').write_text(%r)" %
                (output, json.dumps(payload))
            )]
            project = {"extensions": {"b_roll": {
                "enabled": True, "command": command, "outputs": [str(output)],
            }}}
            brief = {"events": [{"id": "e1", "form": "b_roll",
                                  "target_frame_evidence": ["frame.png"]}]}
            routes = route_extensions(project, {}, brief)
            report = run_extension_adapters(
                project=project, routes=routes, inputs=[], root=root,
                runner=AdapterRunner(root / "state.json"), execute=True,
            )
            self.assertEqual(report["extensions"]["b_roll"]["status"], "complete")
            self.assertTrue(output.is_file())

    def test_empty_extension_output_cannot_claim_completion(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            output = root / "broll.json"
            command = [sys.executable, "-c", (
                "from pathlib import Path; Path(r'%s').write_text('{}')" % output
            )]
            project = {"extensions": {"b_roll": {
                "enabled": True, "command": command, "outputs": [str(output)],
            }}}
            brief = {"events": [{"id": "e1", "form": "b_roll"}]}
            routes = route_extensions(project, {}, brief)
            report = run_extension_adapters(
                project=project, routes=routes, inputs=[], root=root,
                runner=AdapterRunner(root / "state.json"), execute=True,
            )
            self.assertEqual(report["extensions"]["b_roll"]["status"], "unavailable")
            self.assertTrue(report["extensions"]["b_roll"]["validation_errors"])


if __name__ == "__main__":
    unittest.main()
