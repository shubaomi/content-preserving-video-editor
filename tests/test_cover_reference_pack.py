from __future__ import annotations

import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from cover_reference_pack import (  # noqa: E402
    build_candidate_specs,
    build_reference_pack,
    evaluate_candidate,
    privacy_projection,
    record_identity_approval,
    select_references,
    validate_identity_approval,
    validate_reference_pack,
)
from director import prepare_cover_reference_pack  # noqa: E402


class CoverReferencePackTests(unittest.TestCase):
    def _reference(
        self, path: Path, ref_id: str, roles: list[str], *,
        purposes: list[str] | None = None, quality: float = 0.9,
        pose: str | None = None, expression: str | None = None,
    ) -> dict:
        return {
            "reference_id": ref_id,
            "path": str(path.resolve()),
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "roles": roles,
            "purposes": purposes or ["identity_generation"],
            "quality": quality,
            "pose": pose,
            "expression": expression,
            "private_metadata": {"album": "family-private"},
            "biometric_metadata": {"embedding": [1, 2, 3]},
            "authorization": {
                "authorized": True,
                "authorized_by": "asset-owner",
                "authorized_at": "2026-08-02T12:00:00+00:00",
                "scope": "cover_reference",
            },
            "revoked": False,
        }

    def test_distinct_authorized_references_cover_roles_and_project_privacy(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            identity = root / "private-owner-name.png"
            style = root / "style.png"
            identity.write_bytes(b"identity")
            style.write_bytes(b"style")
            pack = build_reference_pack([
                self._reference(identity, "identity-1", ["identity"]),
                self._reference(style, "style-1", ["style", "composition"]),
            ], required_roles=["identity", "style", "composition"])
            validate_reference_pack(pack)
            public = privacy_projection(pack)
            self.assertEqual(public["covered_roles"], ["composition", "identity", "style"])
            rendered = str(public)
            self.assertNotIn(str(root), rendered)
            self.assertNotIn("asset-owner", rendered)
            self.assertNotIn("private-owner-name", rendered)

    def test_rejects_duplicate_content_revocation_and_missing_role(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            first = root / "first.png"
            duplicate = root / "duplicate.png"
            first.write_bytes(b"same")
            duplicate.write_bytes(b"same")
            one = self._reference(first, "one", ["identity"])
            two = self._reference(duplicate, "two", ["style"])
            with self.assertRaisesRegex(ValueError, "distinct content hashes"):
                build_reference_pack([one, two], required_roles=["identity", "style"])
            with self.assertRaisesRegex(ValueError, "revoked"):
                build_reference_pack([{**one, "revoked": True}], required_roles=["identity"])
            with self.assertRaisesRegex(ValueError, "role coverage"):
                build_reference_pack([one], required_roles=["identity", "composition"])

    def _complete_pack(self, root: Path) -> dict:
        rows = []
        specs = [
            ("front-smile", ["identity", "front", "half", "smiling"], "front", "smiling", ["identity_generation", "friendly tutorial"]),
            ("side-think", ["identity", "side", "half", "thinking"], "side", "thinking", ["identity_generation", "analysis direction"]),
            ("explain", ["identity", "explaining", "pointing", "full"], "three_quarter", "explaining", ["identity_generation", "software tutorial"]),
        ]
        for index, (name, roles, pose, expression, purposes) in enumerate(specs):
            path = root / f"{name}.png"
            path.write_bytes(f"photo-{index}".encode())
            rows.append(self._reference(
                path, name, roles, purposes=purposes, pose=pose,
                expression=expression, quality=0.92 - index * 0.01,
            ))
        return build_reference_pack(
            rows,
            required_roles=["identity", "front", "side", "half", "full", "smiling", "explaining", "thinking", "pointing"],
        )

    def test_topic_direction_selection_is_deterministic_and_requires_multiple_images(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pack = self._complete_pack(root)
            first = select_references(
                pack, topic="software tutorial", direction="friendly tutorial",
                target_expression="smiling", minimum_identity_references=2,
            )
            second = select_references(
                pack, topic="software tutorial", direction="friendly tutorial",
                target_expression="smiling", minimum_identity_references=2,
            )
            self.assertEqual(first, second)
            self.assertGreaterEqual(len(first["selected_references"]), 2)
            self.assertEqual(first["generation_mode"], "reference_guided_regeneration")
            self.assertTrue(first["literal_cutout_forbidden"])

            only = root / "only.png"
            only.write_bytes(b"only")
            insufficient = build_reference_pack([
                self._reference(only, "only", ["identity", "front", "smiling"], pose="front", expression="smiling")
            ], required_roles=["identity", "front", "smiling"])
            with self.assertRaisesRegex(ValueError, "at least 2"):
                select_references(insufficient, topic="tutorial", direction="warm", target_expression="smiling")

    def test_wrong_unauthorized_or_expression_mismatched_reference_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pack = self._complete_pack(root)
            pack["references"][0]["authorization"]["authorized"] = False
            with self.assertRaisesRegex(ValueError, "not authorized"):
                select_references(pack, topic="tutorial", direction="warm", target_expression="smiling")

            pack = self._complete_pack(root)
            with self.assertRaisesRegex(ValueError, "expression mismatch"):
                select_references(pack, topic="tutorial", direction="warm", target_expression="joyful")

            pack = self._complete_pack(root)
            pack["references"][0]["subject_id"] = "someone-else"
            pack["references"][1]["subject_id"] = "creator"
            with self.assertRaisesRegex(ValueError, "mixed or wrong subject"):
                select_references(pack, topic="tutorial", direction="warm", target_expression="smiling", expected_subject_id="creator")

    def test_candidate_specs_are_structurally_distinct_and_never_cutout(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            pack = self._complete_pack(Path(folder))
            selection = select_references(
                pack, topic="software tutorial", direction="friendly tutorial", target_expression="smiling",
            )
            specs = build_candidate_specs(
                selection, topic="software tutorial", direction="friendly tutorial",
            )
            self.assertEqual([row["candidate_id"] for row in specs], ["A", "B"])
            self.assertNotEqual(specs[0]["structure"]["template_family"], specs[1]["structure"]["template_family"])
            self.assertNotEqual(specs[0]["structure"]["subject_side"], specs[1]["structure"]["subject_side"])
            self.assertTrue(all(row["generation_mode"] == "reference_guided_regeneration" for row in specs))
            self.assertTrue(all(row["forbid_literal_cutout"] for row in specs))

    def test_candidate_evaluation_separates_identity_expression_anatomy_and_topic(self) -> None:
        good = {
            "identity": 0.9, "expression": 0.85, "gaze": 0.8, "vitality": 0.82,
            "face_proportions": 0.9, "hands_body": 0.88, "topic_relevance": 0.91,
            "thumbnail_composition": 0.86,
        }
        report = evaluate_candidate(candidate_id="A", assessment=good)
        self.assertTrue(report["automated_passed"])
        self.assertEqual(report["identity_user_approval"], "pending")
        hand_bad = {**good, "hands_body": 0.2, "hand_anomaly": True}
        failed = evaluate_candidate(candidate_id="A", assessment=hand_bad)
        self.assertFalse(failed["automated_passed"])
        self.assertIn("hands_body", failed["failed_dimensions"])
        self.assertIn("hand_anomaly", failed["hard_failures"])

    def test_identity_approval_is_hash_bound_and_stale_approval_requires_action(self) -> None:
        approval = record_identity_approval(
            candidate_id="A", candidate_sha256="a" * 64, approved_by="owner",
            approved_at="2026-08-02T12:00:00+00:00", expires_at="2026-08-03T12:00:00+00:00",
        )
        current = validate_identity_approval(
            approval, candidate_id="A", candidate_sha256="a" * 64,
            now="2026-08-02T18:00:00+00:00",
        )
        self.assertTrue(current["approved"])
        stale = validate_identity_approval(
            approval, candidate_id="A", candidate_sha256="b" * 64,
            now="2026-08-04T18:00:00+00:00",
        )
        self.assertFalse(stale["approved"])
        self.assertEqual(stale["status"], "action_required")
        self.assertIn("candidate hash changed", stale["reasons"])

    def test_privacy_projection_omits_paths_biometrics_and_private_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pack = self._complete_pack(root)
            public = privacy_projection(pack)
            rendered = str(public)
            self.assertNotIn(str(root), rendered)
            self.assertNotIn("private_metadata", rendered)
            self.assertNotIn("biometric", rendered)
            self.assertNotIn("embedding", rendered)
            self.assertNotIn("authorized_by", rendered)

    def test_director_prepares_private_selection_and_public_projection(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            pack = self._complete_pack(root)
            manifest = root / "reference-pack.json"
            manifest.write_text(__import__("json").dumps(pack), encoding="utf-8")
            brief = root / "semantic-brief.json"
            brief.write_text('{"events": [], "summary": "ExplainIt concept tutorial"}',
                             encoding="utf-8")
            project = {
                "video_id": "explainit",
                "cover": {
                    "reference_pack": {
                        "enabled": True, "manifest": str(manifest),
                        "required_roles": pack["required_roles"],
                        "target_expression": "smiling",
                        "direction": "friendly software tutorial",
                    },
                    "variants": {"A": {}, "B": {}},
                },
            }
            prepared, artifacts = prepare_cover_reference_pack(
                project, project_root=root, semantic_brief=brief,
                work_dir=root / "work" / "cover",
            )
            self.assertGreaterEqual(len(prepared["cover"]["identity_references"]), 2)
            self.assertEqual(prepared["cover"]["variants"]["A"]["template_family"],
                             "bright_tech_tutorial")
            public = next(path for path in artifacts if path.name.endswith("public.json"))
            self.assertNotIn(str(root), public.read_text(encoding="utf-8"))
            private = next(path for path in artifacts if path.name.endswith("selection.json"))
            self.assertIn("front-smile.png", private.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
