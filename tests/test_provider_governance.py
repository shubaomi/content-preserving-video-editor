from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from provider_governance import (  # noqa: E402
    build_decision_report,
    create_cost_ledger,
    validate_cost_ledger,
    validate_decision_report,
    reserve_selected_call,
    reconcile_selected_call,
    write_provider_result_receipt,
)


class ProviderGovernanceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)

    def tearDown(self) -> None:
        self.temp.cleanup()

    def _receipt(self, reservation: dict, result: dict) -> Path:
        path = self.root / f"{reservation['id']}.json"
        write_provider_result_receipt(path, reservation, result)
        return path

    def test_selector_records_selected_and_rejected_candidates(self) -> None:
        config = {
            "enabled": True, "mode": "cap", "currency": "USD", "budget_total": 5.0,
            "providers": {"image_generation": [
                {"name": "cheap-local", "available": True, "task_fit": 0.7,
                 "chinese": 0.8, "identity_preservation": 0.2, "quality": 0.6,
                 "reliability": 0.9, "privacy_locality": 1.0, "incremental_cost": 0.0,
                 "remaining_quota": 1.0, "latency": 0.5, "continuity_cache": 1.0,
                 "fallback": 1.0},
                {"name": "identity-api", "available": True, "paid_call_authorized": True,
                 "requires_paid_call": True, "verified_pricing_basis": True,
                 "pricing_source": "user_plan", "cost_basis": "user token plan",
                 "evidence_timestamp": "2026-08-01T00:00:00+00:00",
                 "quota_evidence_timestamp": "2026-08-01T00:00:00+00:00",
                 "actual_cost_strategy": "fixed", "failure_incremental_cost": 0.0,
                 "task_fit": 1.0, "chinese": 0.9, "identity_preservation": 1.0,
                 "quality": 0.95, "reliability": 0.8, "privacy_locality": 0.4,
                 "incremental_cost": 1.0, "remaining_quota": 1.0, "latency": 0.7,
                 "continuity_cache": 0.8, "fallback": 0.8},
            ]},
        }
        report = build_decision_report(config=config, project_hash="a" * 64)
        decision = report["decisions"]["image_generation"]
        self.assertEqual(decision["status"], "selected")
        self.assertEqual(decision["selected"]["name"], "identity-api")
        self.assertTrue(decision["rejected"])
        self.assertEqual(validate_decision_report(report, config, "a" * 64), [])

    def test_cost_ledger_estimate_reserve_reconcile_and_budget_cap(self) -> None:
        config = {"mode": "cap", "currency": "USD", "budget_total": 2.0,
                  "providers": {
            "bgm": [{"name": "fixture-bgm", "available": True, "task_fit": 1.0,
                     "incremental_cost": 1.25, "cost_basis": "configured fixture",
                     "actual_cost_strategy": "fixed", "fixed_actual_cost": 0.75,
                     "failure_incremental_cost": 0.0, "paid_call_authorized": True,
                     "verified_pricing_basis": True, "pricing_source": "user_plan",
                     "evidence_timestamp": "2026-08-01T00:00:00+00:00",
                     "quota_evidence_timestamp": "2026-08-01T00:00:00+00:00",
                     "remaining_quota": 10}],
            "image_generation": [{"name": "fixture-cover", "available": True,
                                  "task_fit": 1.0, "incremental_cost": 1.5,
                                  "cost_basis": "configured fixture",
                                  "actual_cost_strategy": "fixed", "fixed_actual_cost": 1.5,
                                  "failure_incremental_cost": 0.0,
                                  "paid_call_authorized": True,
                                  "verified_pricing_basis": True,
                                  "pricing_source": "user_plan",
                                  "evidence_timestamp": "2026-08-01T00:00:00+00:00",
                                  "quota_evidence_timestamp": "2026-08-01T00:00:00+00:00",
                                  "remaining_quota": 10}],
        }}
        ledger = create_cost_ledger(
            config=config,
            project_hash="b" * 64,
        )
        decision = build_decision_report(config=config, project_hash="b" * 64)
        reservation = reserve_selected_call(ledger, decision, task="bgm")
        self.assertEqual(reservation["status"], "reserved")
        reconcile_selected_call(
            ledger, decision, reservation["id"], status="success", elapsed_seconds=0.1,
            result={"asset": "bgm.wav"}, result_receipt_path=self._receipt(
                reservation, {"asset": "bgm.wav"},
            ),
        )
        rejected = reserve_selected_call(ledger, decision, task="image_generation")
        self.assertEqual(rejected["status"], "action_required")
        self.assertEqual(validate_cost_ledger(ledger, "b" * 64), [])

    def test_tampered_cost_ledger_is_rejected(self) -> None:
        ledger = create_cost_ledger(config={"mode": "observe"}, project_hash="c" * 64)
        ledger["totals"]["actual"] = 99
        self.assertTrue(validate_cost_ledger(ledger, "c" * 64))

    def test_unknown_reservation_status_is_rejected_even_with_recomputed_integrity(self) -> None:
        config = {"providers": {"sfx": [{
            "name": "local-sfx", "available": True, "task_fit": 1.0,
            "incremental_cost": 0.0, "cost_basis": "local",
            "actual_cost_strategy": "fixed", "fixed_actual_cost": 0.0,
            "failure_incremental_cost": 0.0,
        }]}}
        decision = build_decision_report(config=config, project_hash="1" * 64)
        ledger = create_cost_ledger(config=config, project_hash="1" * 64)
        reservation = reserve_selected_call(ledger, decision, task="sfx")
        reservation["status"] = "complete-ish"
        ledger["integrity_sha256"] = __import__("hashlib").sha256(json.dumps(
            {key: value for key, value in ledger.items() if key != "integrity_sha256"},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()

        errors = validate_cost_ledger(ledger, "1" * 64)

        self.assertTrue(any("unsupported status" in error for error in errors))

    def test_recomputed_ledger_rejects_forged_fixed_actual_and_result_hash(self) -> None:
        config = {"providers": {"sfx": [{
            "name": "local-sfx", "available": True, "task_fit": 1.0,
            "incremental_cost": 0.25, "cost_basis": "local",
            "actual_cost_strategy": "fixed", "fixed_actual_cost": 0.2,
            "failure_incremental_cost": 0.0, "paid_call_authorized": True,
            "verified_pricing_basis": True, "pricing_source": "user_plan",
            "evidence_timestamp": "2026-08-01T00:00:00+00:00",
            "quota_evidence_timestamp": "2026-08-01T00:00:00+00:00",
            "remaining_quota": 10,
        }]}}
        decision = build_decision_report(config=config, project_hash="2" * 64)
        ledger = create_cost_ledger(config=config, project_hash="2" * 64)
        reservation = reserve_selected_call(ledger, decision, task="sfx")
        reconcile_selected_call(
            ledger, decision, reservation["id"], status="success", elapsed_seconds=0.1,
            result={"asset": "sfx.wav"}, result_receipt_path=self._receipt(
                reservation, {"asset": "sfx.wav"},
            ),
        )
        reservation["actual"] = 0.0
        reservation["actual_cost_evidence"]["result_integrity_sha256"] = "forged"
        ledger["totals"]["actual"] = 0.0
        ledger["integrity_sha256"] = __import__("hashlib").sha256(json.dumps(
            {key: value for key, value in ledger.items() if key != "integrity_sha256"},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()

        errors = validate_cost_ledger(ledger, "2" * 64)

        self.assertTrue(any("does not match selected provider strategy" in error for error in errors))
        self.assertTrue(any("result evidence hash is invalid" in error for error in errors))

    def test_recomputed_ledger_rejects_forged_estimate_and_basis(self) -> None:
        config = {"providers": {"bgm": [{
            "name": "paid-bgm", "available": True, "task_fit": 1.0,
            "incremental_cost": 100.0, "cost_basis": "user contract",
            "actual_cost_strategy": "fixed", "fixed_actual_cost": 100.0,
            "failure_incremental_cost": 0.0, "paid_call_authorized": True,
            "verified_pricing_basis": True, "pricing_source": "user_contract",
            "evidence_timestamp": "2026-08-01T00:00:00+00:00",
            "quota_evidence_timestamp": "2026-08-01T00:00:00+00:00",
            "remaining_quota": 1000,
        }]}}
        decision = build_decision_report(config=config, project_hash="3" * 64)
        ledger = create_cost_ledger(config=config, project_hash="3" * 64)
        reservation = reserve_selected_call(ledger, decision, task="bgm")
        reservation["estimate"] = 0.0
        reservation["estimate_basis"] = "forged"
        ledger["totals"]["estimated"] = 0.0
        ledger["totals"]["reserved"] = 0.0
        ledger["integrity_sha256"] = __import__("hashlib").sha256(json.dumps(
            {key: value for key, value in ledger.items() if key != "integrity_sha256"},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()

        errors = validate_cost_ledger(ledger, "3" * 64)

        self.assertTrue(any("estimate does not match" in error for error in errors))
        self.assertTrue(any("estimate basis does not match" in error for error in errors))

    def test_reserved_row_cannot_be_forged_into_success_without_result_receipt(self) -> None:
        config = {"providers": {"sfx": [{
            "name": "local-sfx", "available": True, "task_fit": 1.0,
            "incremental_cost": 0.0, "cost_basis": "local",
            "actual_cost_strategy": "fixed", "fixed_actual_cost": 0.0,
            "failure_incremental_cost": 0.0,
        }]}}
        decision = build_decision_report(config=config, project_hash="4" * 64)
        ledger = create_cost_ledger(config=config, project_hash="4" * 64)
        reservation = reserve_selected_call(ledger, decision, task="sfx")
        reservation.update({
            "status": "success", "actual": 0.0,
            "reconciled_at": "2026-08-01T00:00:00+00:00",
            "actual_cost_strategy": "fixed",
            "actual_cost_evidence": {
                "elapsed_seconds": 0.1, "result_integrity_sha256": "a" * 64,
                "result_cost_value": None, "result_receipt": None,
            },
        })
        ledger["totals"]["reserved"] = 0.0
        ledger["integrity_sha256"] = __import__("hashlib").sha256(json.dumps(
            {key: value for key, value in ledger.items() if key != "integrity_sha256"},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()

        errors = validate_cost_ledger(ledger, "4" * 64)

        self.assertTrue(any("result receipt is missing" in error for error in errors))

    def test_result_receipt_cannot_omit_output_file_inventory(self) -> None:
        config = {"providers": {"sfx": [{
            "name": "local-sfx", "available": True, "task_fit": 1.0,
            "incremental_cost": 0.0, "cost_basis": "local",
            "actual_cost_strategy": "fixed", "fixed_actual_cost": 0.0,
            "failure_incremental_cost": 0.0,
        }]}}
        decision = build_decision_report(config=config, project_hash="5" * 64)
        ledger = create_cost_ledger(config=config, project_hash="5" * 64)
        reservation = reserve_selected_call(ledger, decision, task="sfx")
        output = self.root / "sfx.wav"; output.write_bytes(b"sound")
        result = {"asset": str(output.resolve())}
        receipt_path = self._receipt(reservation, result)
        reconcile_selected_call(
            ledger, decision, reservation["id"], status="success", elapsed_seconds=0.1,
            result=result, result_receipt_path=receipt_path,
        )
        receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
        receipt["files"] = []
        receipt["integrity_sha256"] = __import__("hashlib").sha256(json.dumps(
            {key: value for key, value in receipt.items() if key != "integrity_sha256"},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        reservation["actual_cost_evidence"]["result_receipt"]["sha256"] = __import__(
            "director_contracts"
        ).sha256_file(receipt_path)
        ledger["integrity_sha256"] = __import__("hashlib").sha256(json.dumps(
            {key: value for key, value in ledger.items() if key != "integrity_sha256"},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()

        errors = validate_cost_ledger(ledger, "5" * 64)

        self.assertTrue(any("output file inventory is stale" in error for error in errors))

    def test_paid_provider_without_verified_current_plan_evidence_is_rejected(self) -> None:
        config = {"providers": {"bgm": [{
            "name": "unknown-price", "available": True, "requires_paid_call": True,
            "paid_call_authorized": True, "incremental_cost": 1.0,
            "remaining_quota": 1.0, "task_fit": 1.0,
        }]}}

        report = build_decision_report(config=config, project_hash="d" * 64)

        self.assertEqual(report["decisions"]["bgm"]["status"], "unavailable")
        reasons = report["decisions"]["bgm"]["rejected"][0]["reasons"]
        self.assertIn("verified_user_pricing_required", reasons)
        self.assertIn("quota_evidence_required", reasons)

    def test_positive_incremental_cost_cannot_omit_paid_evidence(self) -> None:
        config = {"providers": {"bgm": [{
            "name": "unclassified-cost", "available": True,
            "incremental_cost": 9.9, "task_fit": 1.0,
        }]}}

        report = build_decision_report(config=config, project_hash="9" * 64)

        decision = report["decisions"]["bgm"]
        self.assertEqual(decision["status"], "unavailable")
        self.assertIn("verified_user_pricing_required", decision["rejected"][0]["reasons"])

    def test_paid_provider_with_stale_plan_evidence_is_rejected(self) -> None:
        config = {
            "max_evidence_age_days": 30,
            "providers": {"bgm": [{
                "name": "stale-plan", "available": True,
                "requires_paid_call": True, "paid_call_authorized": True,
                "verified_pricing_basis": True, "pricing_source": "user_plan",
                "cost_basis": "user token plan", "incremental_cost": 1.0,
                "remaining_quota": 1.0, "task_fit": 1.0,
                "evidence_timestamp": "2025-01-01T00:00:00+00:00",
                "quota_evidence_timestamp": "2025-01-01T00:00:00+00:00",
                "actual_cost_strategy": "fixed", "failure_incremental_cost": 0.0,
            }]},
        }

        report = build_decision_report(config=config, project_hash="f" * 64)

        decision = report["decisions"]["bgm"]
        self.assertEqual(decision["status"], "unavailable")
        self.assertIn("stale_pricing_or_quota_evidence", decision["rejected"][0]["reasons"])

    def test_selected_call_is_reserved_then_reconciled_with_actual_basis(self) -> None:
        config = {"providers": {"sfx": [{
            "name": "local-sfx", "available": True, "incremental_cost": 0.25,
            "cost_basis": "user configured fixed call", "actual_cost_strategy": "fixed",
            "fixed_actual_cost": 0.2, "failure_incremental_cost": 0.0,
            "paid_call_authorized": True, "verified_pricing_basis": True,
            "pricing_source": "user_plan",
            "evidence_timestamp": "2026-08-01T00:00:00+00:00",
            "quota_evidence_timestamp": "2026-08-01T00:00:00+00:00",
            "task_fit": 1.0,
            "remaining_quota": 10,
        }]}}
        decision = build_decision_report(config=config, project_hash="e" * 64)
        ledger = create_cost_ledger(config=config, project_hash="e" * 64)

        reservation = reserve_selected_call(ledger, decision, task="sfx")
        reconcile_selected_call(
            ledger, decision, reservation["id"], status="success", elapsed_seconds=0.5,
            result={"asset": "sfx.wav"}, result_receipt_path=self._receipt(
                reservation, {"asset": "sfx.wav"},
            ),
        )

        self.assertEqual(ledger["reservations"][0]["status"], "success")
        self.assertEqual(ledger["reservations"][0]["actual"], 0.2)
        self.assertEqual(validate_cost_ledger(ledger, "e" * 64), [])


if __name__ == "__main__":
    unittest.main()
