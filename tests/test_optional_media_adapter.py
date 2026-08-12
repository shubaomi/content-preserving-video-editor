from __future__ import annotations

import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from optional_media_adapter import authorize_optional_adapter  # noqa: E402


class OptionalMediaAdapterTests(unittest.TestCase):
    def test_string_false_is_not_treated_as_governance_approval(self) -> None:
        result = authorize_optional_adapter({
            "enabled": True, "kind": "ocr", "provider": "local",
            "rights_approved": "false", "privacy_approved": "false",
            "budget_approved": "false", "provenance_enabled": "false",
            "human_review_required": "false",
        })
        self.assertEqual(result["status"], "action_required")
        self.assertIn("rights_approved", result["missing_contracts"])

    def test_cloud_adapter_requires_all_governance_and_human_review_contracts(self) -> None:
        denied = authorize_optional_adapter({
            "enabled": True, "kind": "cover_generation", "provider": "example-cloud",
            "cloud_upload": True, "rights_approved": True, "privacy_approved": False,
            "budget_approved": True, "provenance_enabled": True,
            "human_review_required": True,
        })
        self.assertEqual(denied["status"], "action_required")
        self.assertIn("privacy_approved", denied["missing_contracts"])

    def test_local_optional_adapter_is_default_off_and_never_approves_aesthetics(self) -> None:
        disabled = authorize_optional_adapter({"enabled": False, "kind": "ocr"})
        self.assertEqual(disabled["status"], "disabled")
        allowed = authorize_optional_adapter({
            "enabled": True, "kind": "ocr", "provider": "local",
            "cloud_upload": False, "rights_approved": True, "privacy_approved": True,
            "budget_approved": True, "provenance_enabled": True,
            "human_review_required": True,
        })
        self.assertEqual(allowed["status"], "authorized_to_run")
        self.assertFalse(allowed["aesthetic_approval_granted"])

    def test_authorized_adapter_is_not_reported_as_executed_or_reviewed(self) -> None:
        allowed = authorize_optional_adapter({
            "enabled": True, "kind": "ip_image", "provider": "local",
            "cloud_upload": False, "rights_approved": True, "privacy_approved": True,
            "budget_approved": True, "provenance_enabled": True,
            "human_review_required": True,
        })

        self.assertEqual(allowed["execution_status"], "not_run")
        self.assertEqual(allowed["review_status"], "pending")
        self.assertFalse(allowed["publication_authorized"])

    def test_unknown_adapter_kind_is_rejected(self) -> None:
        denied = authorize_optional_adapter({
            "enabled": True, "kind": "make_everything", "provider": "local",
            "rights_approved": True, "privacy_approved": True,
            "budget_approved": True, "provenance_enabled": True,
            "human_review_required": True,
        })
        self.assertEqual(denied["status"], "unavailable")


if __name__ == "__main__":
    unittest.main()
