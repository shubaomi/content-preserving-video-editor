from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from build_real_project_validation import build_receipt  # noqa: E402
from director_contracts import sha256_file  # noqa: E402
from motion_contracts import validate_real_project_validation  # noqa: E402


class BuildRealProjectValidationTests(unittest.TestCase):
    def test_builder_materializes_hashes_media_and_all_requirement_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            files = {}
            for name, content in {
                "source.mp4": b"source",
                "baseline.mp4": b"baseline",
                "candidate.mp4": b"candidate",
                "rights.md": b"authorized",
                "qa.json": b"{}",
                "project.yaml": b"schema_version: 10\n",
            }.items():
                path = root / name
                path.write_bytes(content)
                files[name] = path
            probes = {
                str(files[name].resolve()): {
                    "duration_seconds": 75.0, "width": 1920, "height": 1080,
                }
                for name in ("source.mp4", "baseline.mp4", "candidate.mp4")
            }
            spec = {
                "validation_id": "landscape-1",
                "created_at": "2026-08-11T20:50:00Z",
                "canary_role": "landscape_screen",
                "project_id": "project-1",
                "source": {"path": str(files["source.mp4"]), "purpose": "real source"},
                "rights": {
                    "status": "authorized", "basis": "owner authorization",
                    "evidence": {"path": str(files["rights.md"]), "purpose": "rights"},
                },
                "identity_mode": "third_party",
                "baseline": {"path": str(files["baseline.mp4"]), "purpose": "baseline"},
                "candidate": {"path": str(files["candidate.mp4"]), "purpose": "candidate"},
                "requirement_results": [{
                    "requirement_id": f"RQ-{index:03d}",
                    "gate_owner": "automated", "status": "pass",
                    "reason": "current gate passed",
                    "evidence": [{"path": str(files["qa.json"]), "purpose": "QA"}],
                } for index in range(1, 21)],
                "metrics": {
                    "semantic_correct_rate": 1.0, "geometry_correct_rate": 1.0,
                    "caption_sync_pass": True, "audio_audibility_pass": True,
                    "correction_minutes": 10.0,
                    "baseline_candidate_preference": "candidate",
                    "publish_willingness": "yes", "render_wall_seconds": 20.0,
                    "estimated_cost": 0.0, "cost_currency": "USD",
                },
                "user_decisions": [{
                    "criterion": "sample_quality", "decision": "approved",
                    "reviewer": "HongRun", "reviewed_at": "2026-08-11T20:50:00Z",
                    "reason": "candidate is clearer",
                }, {
                    "criterion": "publishability", "decision": "approved",
                    "reviewer": "HongRun", "reviewed_at": "2026-08-11T20:50:00Z",
                    "reason": "ready to publish",
                }],
                "overall_status": "pass",
                "maturity_recommendation": "real_project_validated",
            }
            output = root / "receipt.json"
            receipt = build_receipt(
                spec=spec,
                output=output,
                configuration_path=files["project.yaml"],
                implementation={
                    "git_commit": "a" * 40,
                    "source_tree_sha256": "b" * 64,
                    "schema_version": 10,
                },
                media_probe=lambda path: probes[str(path)],
            )
            self.assertTrue(output.is_file())
            self.assertEqual(receipt["configuration_sha256"], sha256_file(files["project.yaml"]))
            self.assertEqual(receipt["candidate"]["sha256"], sha256_file(files["candidate.mp4"]))
            self.assertEqual(receipt["requirement_results"][0]["evidence"][0]["sha256"],
                             sha256_file(files["qa.json"]))
            self.assertEqual(validate_real_project_validation(
                receipt, media_probe=lambda path: probes[str(path)],
                configuration_path=files["project.yaml"],
            ), [])

    def test_builder_fails_closed_before_writing_when_evidence_is_missing(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            source = root / "source.mp4"
            baseline = root / "baseline.mp4"
            candidate = root / "candidate.mp4"
            rights = root / "rights.md"
            config = root / "project.yaml"
            for path in (source, baseline, candidate, rights, config):
                path.write_bytes(path.name.encode("utf-8"))
            missing = root / "missing-qa.json"
            spec = {
                "validation_id": "landscape-missing-evidence",
                "created_at": "2026-08-11T20:50:00Z",
                "canary_role": "landscape_screen",
                "project_id": "project-1",
                "source": {"path": str(source), "purpose": "source"},
                "rights": {
                    "status": "authorized", "basis": "owner authorization",
                    "evidence": {"path": str(rights), "purpose": "rights"},
                },
                "identity_mode": "third_party",
                "baseline": {"path": str(baseline), "purpose": "baseline"},
                "candidate": {"path": str(candidate), "purpose": "candidate"},
                "requirement_results": [{
                    "requirement_id": "RQ-001", "gate_owner": "automated",
                    "status": "pass", "evidence": [{
                        "path": str(missing), "purpose": "missing QA",
                    }],
                }],
                "metrics": {}, "user_decisions": [],
                "overall_status": "pass",
                "maturity_recommendation": "real_project_validated",
            }
            output = root / "receipt.json"
            with self.assertRaisesRegex(ValueError, "file is missing"):
                build_receipt(
                    spec=spec,
                    output=output,
                    configuration_path=config,
                    implementation={
                        "git_commit": "a" * 40,
                        "source_tree_sha256": "b" * 64,
                        "schema_version": 10,
                    },
                    media_probe=lambda _path: {
                        "duration_seconds": 75.0, "width": 1920, "height": 1080,
                    },
                )
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
