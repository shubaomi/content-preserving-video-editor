from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director_contracts import sha256_file  # noqa: E402
from motion_contracts import validate_real_project_validation  # noqa: E402


class RealProjectValidationTests(unittest.TestCase):
    def _receipt(self, root: Path) -> tuple[dict, dict[str, dict]]:
        files: dict[str, Path] = {}
        for name, content in {
            "source.mp4": b"real-source",
            "baseline.mp4": b"baseline-media",
            "candidate.mp4": b"candidate-media",
            "rights.txt": b"authorized test fixture",
            "automated.json": b"{}",
        }.items():
            path = root / name
            path.write_bytes(content)
            files[name] = path

        media_probe = {
            str(files["source.mp4"].resolve()): {
                "duration_seconds": 75.0, "width": 1920, "height": 1080,
            },
            str(files["baseline.mp4"].resolve()): {
                "duration_seconds": 75.0, "width": 1920, "height": 1080,
            },
            str(files["candidate.mp4"].resolve()): {
                "duration_seconds": 75.0, "width": 1920, "height": 1080,
            },
        }

        def artifact(name: str, purpose: str) -> dict:
            path = files[name].resolve()
            return {
                "artifact_type": "rights_record" if name == "rights.txt" else "qa_report",
                "path": str(path),
                "sha256": sha256_file(path),
                "purpose": purpose,
            }

        def media(name: str, purpose: str) -> dict:
            path = files[name].resolve()
            return {
                "artifact_type": "video_mp4",
                "path": str(path),
                "sha256": sha256_file(path),
                "purpose": purpose,
                **media_probe[str(path)],
            }

        qa = artifact("automated.json", "automated gate evidence")
        receipt = {
            "schema_version": "1.0.0",
            "validation_id": "real-landscape-1",
            "created_at": "2026-08-11T04:00:00-07:00",
            "producer": "content-preserving-video-editor",
            "media_kind": "real",
            "canary_role": "landscape_screen",
            "project_id": "landscape-canary",
            "source": media("source.mp4", "authorized real source"),
            "rights": {
                "status": "authorized",
                "basis": "The source owner authorized editing and review.",
                "evidence": artifact("rights.txt", "authorization record"),
            },
            "identity_mode": "third_party",
            "implementation": {
                "git_commit": "a" * 40,
                "source_tree_sha256": "b" * 64,
                "schema_version": 10,
            },
            "configuration_sha256": "c" * 64,
            "baseline": media("baseline.mp4", "matched baseline sample"),
            "candidate": media("candidate.mp4", "current workflow candidate"),
            "requirement_results": [
                {
                    "requirement_id": f"RQ-{index:03d}",
                    "gate_owner": "automated",
                    "status": "pass",
                    "reason": "current automated gate passed",
                    "evidence": [dict(qa)],
                }
                for index in range(1, 21)
            ],
            "metrics": {
                "semantic_correct_rate": 0.98,
                "geometry_correct_rate": 0.97,
                "caption_sync_pass": True,
                "audio_audibility_pass": True,
                "correction_minutes": 12.0,
                "baseline_candidate_preference": "candidate",
                "publish_willingness": "yes",
                "render_wall_seconds": 180.0,
                "estimated_cost": 0.0,
                "cost_currency": "USD",
            },
            "user_decisions": [
                {
                    "criterion": criterion,
                    "decision": "approved" if criterion in {"sample_quality", "publishability"}
                    else "not_applicable",
                    "reviewer": "HongRun",
                    "reviewed_at": "2026-08-11T04:30:00-07:00",
                    "reason": "paired review completed" if criterion in {
                        "sample_quality", "publishability",
                    } else "not in this identity-neutral package",
                }
                for criterion in (
                    "sample_quality", "publishability", "brand_taste", "likeness",
                    "cover_click_appeal",
                )
            ],
            "overall_status": "pass",
            "maturity_recommendation": "real_project_validated",
        }
        return receipt, media_probe

    def test_pass_requires_real_hash_bound_media_all_requirements_and_user_decisions(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            receipt, probes = self._receipt(Path(temp))
            self.assertEqual(
                validate_real_project_validation(receipt, media_probe=lambda path: probes[str(path)]),
                [],
            )

    def test_tampered_evidence_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            receipt, probes = self._receipt(Path(temp))
            Path(receipt["requirement_results"][0]["evidence"][0]["path"]).write_text(
                json.dumps({"tampered": True}), encoding="utf-8",
            )
            errors = validate_real_project_validation(
                receipt, media_probe=lambda path: probes[str(path)],
            )
            self.assertTrue(any("hash is stale" in error for error in errors))

    def test_pass_rejects_missing_requirement_and_user_approval(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            receipt, probes = self._receipt(Path(temp))
            receipt["requirement_results"] = receipt["requirement_results"][:-1]
            receipt["user_decisions"][0]["decision"] = "rejected"
            errors = validate_real_project_validation(
                receipt, media_probe=lambda path: probes[str(path)],
            )
            self.assertTrue(any("RQ-001 through RQ-020" in error for error in errors))
            self.assertTrue(any("sample_quality" in error for error in errors))

    def test_pass_enforces_cross_canary_thresholds(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            receipt, probes = self._receipt(Path(temp))
            receipt["metrics"]["semantic_correct_rate"] = 0.94
            receipt["metrics"]["geometry_correct_rate"] = 0.90
            receipt["metrics"]["correction_minutes"] = 21
            receipt["metrics"]["baseline_candidate_preference"] = "tie"
            errors = validate_real_project_validation(
                receipt, media_probe=lambda path: probes[str(path)],
            )
            self.assertTrue(any("semantic correctness" in error for error in errors))
            self.assertTrue(any("geometry correctness" in error for error in errors))
            self.assertTrue(any("correction time" in error for error in errors))
            self.assertTrue(any("candidate preference" in error for error in errors))

    def test_pending_review_cannot_recommend_real_project_maturity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            receipt, probes = self._receipt(Path(temp))
            receipt["overall_status"] = "pending_user_review"
            receipt["maturity_recommendation"] = "fixture_validated"
            receipt["user_decisions"] = [{
                "criterion": "likeness",
                "decision": "not_applicable",
                "reviewer": "workflow",
                "reviewed_at": "2026-08-11T04:30:00-07:00",
                "reason": "identity-neutral canary does not generate or transform a person",
            }]
            self.assertEqual(
                validate_real_project_validation(receipt, media_probe=lambda path: probes[str(path)]),
                [],
            )
            receipt["maturity_recommendation"] = "real_project_validated"
            errors = validate_real_project_validation(
                receipt, media_probe=lambda path: probes[str(path)],
            )
            self.assertTrue(any("pending receipt cannot recommend" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
