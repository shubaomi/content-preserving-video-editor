#!/usr/bin/env python3
"""Deterministic provider selection and auditable estimate/reserve/reconcile ledger."""
from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from director_contracts import read_json, sha256_file, write_json


TASKS = (
    "asr_stt", "image_generation", "identity_reference_generation", "bgm", "sfx",
    "media_catalog", "translation", "tts", "local_model",
)
SCORE_FIELDS = {
    "task_fit": 0.20,
    "chinese": 0.10,
    "identity_preservation": 0.20,
    "quality": 0.15,
    "reliability": 0.10,
    "privacy_locality": 0.08,
    "remaining_quota": 0.05,
    "latency": 0.04,
    "continuity_cache": 0.04,
    "fallback": 0.04,
}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _implementation() -> dict[str, str]:
    path = Path(__file__).resolve()
    return {"path": str(path), "sha256": sha256_file(path)}


def _score(candidate: dict[str, Any]) -> tuple[float, dict[str, float]]:
    components: dict[str, float] = {}
    for field, weight in SCORE_FIELDS.items():
        try:
            value = max(0.0, min(1.0, float(candidate.get(field, 0.0))))
        except (TypeError, ValueError):
            value = 0.0
        components[field] = round(value * weight, 6)
    try:
        cost = max(0.0, float(candidate.get("incremental_cost", 0.0)))
    except (TypeError, ValueError):
        cost = 0.0
    components["incremental_cost_penalty"] = -min(0.10, cost * 0.02)
    return round(sum(components.values()), 6), components


def _positive_number(value: Any) -> bool:
    try:
        return float(value) > 0
    except (TypeError, ValueError):
        return False


def _current_evidence(value: Any, max_age_days: int) -> bool:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return False
    if parsed.tzinfo is None:
        return False
    age_seconds = (datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)).total_seconds()
    return -300 <= age_seconds <= max_age_days * 86400


def build_decision_report(*, config: dict[str, Any], project_hash: str) -> dict[str, Any]:
    decisions: dict[str, Any] = {}
    configured = config.get("providers") or {}
    max_evidence_age_days = int(config.get("max_evidence_age_days", 30))
    for task in TASKS:
        candidates = configured.get(task) or []
        ranked: list[dict[str, Any]] = []
        rejected: list[dict[str, Any]] = []
        for candidate in candidates if isinstance(candidates, list) else []:
            if not isinstance(candidate, dict):
                continue
            name = str(candidate.get("name") or "unnamed")
            reasons: list[str] = []
            paid_call = (
                candidate.get("requires_paid_call") is True
                or _positive_number(candidate.get("incremental_cost"))
            )
            if candidate.get("available") is not True:
                reasons.append("unavailable")
            if (
                paid_call
                and candidate.get("paid_call_authorized") is not True
            ):
                reasons.append("paid_call_not_authorized")
            if paid_call:
                if (
                    candidate.get("verified_pricing_basis") is not True
                    or candidate.get("pricing_source") not in {"user_plan", "user_contract"}
                    or not str(candidate.get("cost_basis") or "").strip()
                    or candidate.get("incremental_cost") is None
                ):
                    reasons.append("verified_user_pricing_required")
                if (
                    not str(candidate.get("evidence_timestamp") or "").strip()
                    or not str(candidate.get("quota_evidence_timestamp") or "").strip()
                    or not _positive_number(candidate.get("remaining_quota"))
                ):
                    reasons.append("quota_evidence_required")
                elif not (
                    _current_evidence(candidate.get("evidence_timestamp"), max_evidence_age_days)
                    and _current_evidence(
                        candidate.get("quota_evidence_timestamp"), max_evidence_age_days,
                    )
                ):
                    reasons.append("stale_pricing_or_quota_evidence")
                if candidate.get("actual_cost_strategy") not in {
                    "fixed", "result_field", "local_runtime"
                }:
                    reasons.append("actual_cost_reconciliation_required")
                if candidate.get("failure_incremental_cost") is None:
                    reasons.append("failure_cost_evidence_required")
            score, components = _score(candidate)
            row = {
                "name": name,
                "score": score,
                "score_components": components,
                "incremental_cost": candidate.get("incremental_cost"),
                "cost_basis": candidate.get("cost_basis"),
                "model": candidate.get("model"),
                "cache_key": candidate.get("cache_key"),
                "evidence": {field: candidate.get(field) for field in SCORE_FIELDS},
                "local_runtime_seconds": candidate.get("local_runtime_seconds"),
                "requires_paid_call": paid_call,
                "pricing_source": candidate.get("pricing_source"),
                "verified_pricing_basis": candidate.get("verified_pricing_basis") is True,
                "evidence_timestamp": candidate.get("evidence_timestamp"),
                "quota_evidence_timestamp": candidate.get("quota_evidence_timestamp"),
                "actual_cost_strategy": candidate.get("actual_cost_strategy") or "fixed",
                "fixed_actual_cost": candidate.get("fixed_actual_cost"),
                "failure_incremental_cost": candidate.get("failure_incremental_cost", 0.0),
                "cost_per_runtime_second": candidate.get("cost_per_runtime_second"),
                "actual_cost_result_field": candidate.get("actual_cost_result_field"),
            }
            if reasons:
                rejected.append({**row, "reasons": reasons})
            else:
                ranked.append(row)
        ranked.sort(key=lambda row: (-float(row["score"]), str(row["name"])))
        if ranked:
            decisions[task] = {
                "status": "selected",
                "selected": ranked[0],
                "selection_reason": "highest configured evidence score among authorized available candidates",
                "rejected": rejected + [
                    {**row, "reasons": ["lower_evidence_score"]} for row in ranked[1:]
                ],
            }
        else:
            decisions[task] = {
                "status": "unavailable",
                "selected": None,
                "selection_reason": "no authorized available configured candidate",
                "rejected": rejected,
            }
    report = {
        "schema_version": 1,
        "project_sha256": project_hash,
        "config": config,
        "config_sha256": _stable_hash(config),
        "implementation": _implementation(),
        "weights": SCORE_FIELDS,
        "decisions": decisions,
    }
    report["integrity_sha256"] = _stable_hash(report)
    return report


def validate_decision_report(
    report: dict[str, Any], config: dict[str, Any], project_hash: str,
) -> list[str]:
    errors: list[str] = []
    if report.get("schema_version") != 1:
        errors.append("provider decision schema_version must be 1")
    if report.get("project_sha256") != project_hash:
        errors.append("provider decision project hash is stale")
    if report.get("config_sha256") != _stable_hash(config) or report.get("config") != config:
        errors.append("provider decision configuration is stale")
    integrity = report.get("integrity_sha256")
    if integrity != _stable_hash({k: v for k, v in report.items() if k != "integrity_sha256"}):
        errors.append("provider decision integrity hash is stale")
    implementation = report.get("implementation") or {}
    path = Path(str(implementation.get("path") or ""))
    if not path.is_file() or path.resolve() != Path(__file__).resolve() or (
        implementation.get("sha256") != (sha256_file(path) if path.is_file() else None)
    ):
        errors.append("provider decision implementation binding is stale")
    if report != build_decision_report(config=config, project_hash=project_hash):
        errors.append("provider decision does not match current deterministic selection")
    return errors


def _ledger_integrity(ledger: dict[str, Any]) -> str:
    return _stable_hash({k: v for k, v in ledger.items() if k != "integrity_sha256"})


def _refresh_totals(ledger: dict[str, Any]) -> None:
    rows = ledger.get("reservations") or []
    ledger["totals"] = {
        "estimated": round(sum(float(row.get("estimate") or 0) for row in rows), 6),
        "reserved": round(sum(
            float(row.get("estimate") or 0) for row in rows if row.get("status") == "reserved"
        ), 6),
        "actual": round(sum(
            float(row.get("actual") or 0) for row in rows
            if row.get("status") in {"success", "failed"}
        ), 6),
    }
    ledger["integrity_sha256"] = _ledger_integrity(ledger)


def create_cost_ledger(*, config: dict[str, Any], project_hash: str) -> dict[str, Any]:
    ledger = {
        "schema_version": 1,
        "project_sha256": project_hash,
        "config": config,
        "config_sha256": _stable_hash(config),
        "implementation": _implementation(),
        "currency": config.get("currency", "USD"),
        "budget": {"mode": config.get("mode", "observe"), "total": config.get("budget_total")},
        "reservations": [],
        "totals": {"estimated": 0.0, "reserved": 0.0, "actual": 0.0},
    }
    ledger["integrity_sha256"] = _ledger_integrity(ledger)
    return ledger


def reserve_cost(
    ledger: dict[str, Any], *, task: str, provider: str, estimate: float,
    estimate_basis: str, local_runtime_seconds: float | None,
) -> dict[str, Any]:
    estimate = max(0.0, float(estimate))
    row = {
        "id": uuid.uuid4().hex,
        "task": task,
        "provider": provider,
        "estimate": estimate,
        "estimate_basis": estimate_basis,
        "local_runtime_seconds": local_runtime_seconds,
        "reserved_at": _now(),
        "status": "reserved",
        "actual": None,
    }
    budget = ledger.get("budget") or {}
    total = budget.get("total")
    committed = float((ledger.get("totals") or {}).get("actual") or 0) + float(
        (ledger.get("totals") or {}).get("reserved") or 0
    )
    if budget.get("mode") == "cap" and total is not None and committed + estimate > float(total):
        row.update({
            "status": "action_required",
            "reason": "configured budget is insufficient for this reservation",
        })
    ledger.setdefault("reservations", []).append(row)
    _refresh_totals(ledger)
    return row


def reconcile_reservation(
    ledger: dict[str, Any], reservation_id: str, *, actual: float, status: str,
) -> dict[str, Any]:
    if status not in {"success", "failed"}:
        raise ValueError("reconciliation status must be success or failed")
    row = next((item for item in ledger.get("reservations") or []
                if item.get("id") == reservation_id), None)
    if row is None or row.get("status") != "reserved":
        raise ValueError("reservation is missing or no longer reservable")
    row.update({"status": status, "actual": max(0.0, float(actual)), "reconciled_at": _now()})
    _refresh_totals(ledger)
    return row


def reserve_selected_call(
    ledger: dict[str, Any], decision_report: dict[str, Any], *, task: str,
) -> dict[str, Any]:
    decision = (decision_report.get("decisions") or {}).get(task) or {}
    selected = decision.get("selected") if decision.get("status") == "selected" else None
    if not isinstance(selected, dict):
        raise ValueError(f"no selected provider is available for task: {task}")
    estimate = selected.get("incremental_cost")
    if estimate is None:
        raise ValueError(f"selected provider lacks an incremental cost estimate: {task}")
    reservation = reserve_cost(
        ledger, task=task, provider=str(selected.get("name")), estimate=float(estimate),
        estimate_basis=str(selected.get("cost_basis") or "configured local zero-cost call"),
        local_runtime_seconds=selected.get("local_runtime_seconds"),
    )
    reservation["decision_integrity_sha256"] = decision_report.get("integrity_sha256")
    reservation["selected_provider_sha256"] = _stable_hash(selected)
    _refresh_totals(ledger)
    return reservation


def _result_files(value: Any) -> list[dict[str, str]]:
    paths: set[Path] = set()

    def visit(item: Any) -> None:
        if isinstance(item, dict):
            for child in item.values():
                visit(child)
        elif isinstance(item, (list, tuple)):
            for child in item:
                visit(child)
        elif isinstance(item, str):
            candidate = Path(item)
            if candidate.is_absolute():
                paths.add(candidate.resolve())

    visit(value)
    return [{
        "path": str(path),
        "status": "available" if path.is_file() else "missing",
        "sha256": sha256_file(path) if path.is_file() else None,
    } for path in sorted(paths)]


def write_provider_result_receipt(
    output: Path, reservation: dict[str, Any], result: dict[str, Any],
) -> dict[str, Any]:
    receipt = {
        "schema_version": 1,
        "reservation_id": reservation.get("id"),
        "task": reservation.get("task"),
        "provider": reservation.get("provider"),
        "result": result,
        "result_integrity_sha256": _stable_hash(result),
        "files": _result_files(result),
    }
    receipt["integrity_sha256"] = _stable_hash(receipt)
    write_json(output.resolve(), receipt)
    return receipt


def _result_receipt_errors(
    binding: dict[str, Any], reservation: dict[str, Any],
) -> tuple[list[str], dict[str, Any] | None]:
    path = Path(str(binding.get("path") or ""))
    errors: list[str] = []
    if not path.is_absolute() or not path.is_file():
        return ["provider result receipt is missing"], None
    if binding.get("sha256") != sha256_file(path):
        errors.append("provider result receipt hash is stale")
    try:
        receipt = read_json(path)
    except (OSError, json.JSONDecodeError):
        return [*errors, "provider result receipt is unreadable"], None
    if receipt.get("schema_version") != 1:
        errors.append("provider result receipt schema is invalid")
    for field in ("reservation_id", "task", "provider"):
        expected = reservation.get("id" if field == "reservation_id" else field)
        if receipt.get(field) != expected:
            errors.append(f"provider result receipt {field} binding is stale")
    result = receipt.get("result")
    if not isinstance(result, dict) or receipt.get("result_integrity_sha256") != _stable_hash(result or {}):
        errors.append("provider result receipt result hash is stale")
    expected_files = _result_files(result or {})
    if receipt.get("files") != expected_files:
        errors.append("provider result receipt output file inventory is stale")
    for item in expected_files:
        file_path = Path(str(item.get("path") or ""))
        if item.get("status") != "available" or not file_path.is_absolute() or not file_path.is_file() or item.get("sha256") != (
            sha256_file(file_path) if file_path.is_file() else None
        ):
            errors.append("provider result receipt output file binding is stale")
    if receipt.get("integrity_sha256") != _stable_hash(
        {key: value for key, value in receipt.items() if key != "integrity_sha256"}
    ):
        errors.append("provider result receipt integrity is stale")
    return errors, receipt


def reconcile_selected_call(
    ledger: dict[str, Any], decision_report: dict[str, Any], reservation_id: str, *,
    status: str, elapsed_seconds: float, result: dict[str, Any] | None = None,
    result_receipt_path: Path | None = None,
) -> dict[str, Any]:
    reservation = next(
        (row for row in ledger.get("reservations") or [] if row.get("id") == reservation_id),
        None,
    )
    if reservation is None:
        raise ValueError("provider reservation is missing")
    task = str(reservation.get("task"))
    selected = ((decision_report.get("decisions") or {}).get(task) or {}).get("selected") or {}
    strategy = selected.get("actual_cost_strategy") or "fixed"
    receipt_binding: dict[str, Any] | None = None
    if status == "success":
        if not isinstance(result, dict) or result_receipt_path is None:
            raise ValueError("successful provider call requires a result receipt")
        receipt_binding = {
            "path": str(result_receipt_path.resolve()),
            "sha256": sha256_file(result_receipt_path.resolve()),
        }
        receipt_errors, receipt = _result_receipt_errors(receipt_binding, reservation)
        if receipt_errors or not isinstance(receipt, dict) or receipt.get("result") != result:
            raise ValueError("successful provider result receipt is invalid: " + "; ".join(receipt_errors))
    if status == "failed":
        actual = selected.get("failure_incremental_cost")
        if actual is None:
            raise ValueError("failed provider call lacks verified actual-cost evidence")
    elif strategy == "fixed":
        actual = selected.get("fixed_actual_cost")
        if actual is None:
            actual = selected.get("incremental_cost")
    elif strategy == "local_runtime":
        rate = selected.get("cost_per_runtime_second")
        if rate is None:
            raise ValueError("local runtime provider lacks cost_per_runtime_second")
        actual = max(0.0, float(elapsed_seconds)) * float(rate)
    elif strategy == "result_field":
        field = str(selected.get("actual_cost_result_field") or "actual_cost")
        if not isinstance(result, dict) or result.get(field) is None:
            raise ValueError(f"provider result lacks actual cost field: {field}")
        actual = result[field]
    else:
        raise ValueError(f"unsupported actual cost strategy: {strategy}")
    row = reconcile_reservation(
        ledger, reservation_id, actual=float(actual), status=status,
    )
    row["actual_cost_strategy"] = strategy
    row["actual_cost_evidence"] = {
        "elapsed_seconds": round(max(0.0, float(elapsed_seconds)), 6),
        "result_integrity_sha256": _stable_hash(result) if isinstance(result, dict) else None,
        "result_cost_value": (
            actual if strategy == "result_field" else None
        ),
        "result_receipt": receipt_binding,
    }
    _refresh_totals(ledger)
    return row


def validate_cost_ledger(ledger: dict[str, Any], project_hash: str) -> list[str]:
    errors: list[str] = []
    if ledger.get("schema_version") != 1:
        errors.append("cost ledger schema_version must be 1")
    if ledger.get("project_sha256") != project_hash:
        errors.append("cost ledger project hash is stale")
    if ledger.get("config_sha256") != _stable_hash(ledger.get("config") or {}):
        errors.append("cost ledger configuration hash is stale")
    expected = json.loads(json.dumps(ledger))
    expected.pop("integrity_sha256", None)
    rows = expected.get("reservations") or []
    decision = build_decision_report(config=ledger.get("config") or {}, project_hash=project_hash)
    seen_ids: set[str] = set()
    allowed_statuses = {"reserved", "action_required", "success", "failed"}
    for index, row in enumerate(rows):
        prefix = f"cost ledger reservations[{index}]"
        reservation_id = str(row.get("id") or "")
        if not reservation_id or reservation_id in seen_ids:
            errors.append(f"{prefix} requires a unique id")
        seen_ids.add(reservation_id)
        status = row.get("status")
        if status not in allowed_statuses:
            errors.append(f"{prefix} has unsupported status")
        task = str(row.get("task") or "")
        selected = ((decision.get("decisions") or {}).get(task) or {}).get("selected")
        if not isinstance(selected, dict) or row.get("provider") != selected.get("name"):
            errors.append(f"{prefix} does not match the selected task/provider")
        else:
            if row.get("decision_integrity_sha256") != decision.get("integrity_sha256"):
                errors.append(f"{prefix} decision binding is stale")
            if row.get("selected_provider_sha256") != _stable_hash(selected):
                errors.append(f"{prefix} selected provider binding is stale")
            try:
                if abs(float(row.get("estimate")) - float(selected.get("incremental_cost"))) > 0.000001:
                    errors.append(f"{prefix} estimate does not match selected provider")
            except (TypeError, ValueError):
                errors.append(f"{prefix} estimate does not match selected provider")
            if row.get("estimate_basis") != str(
                selected.get("cost_basis") or "configured local zero-cost call"
            ):
                errors.append(f"{prefix} estimate basis does not match selected provider")
            if row.get("local_runtime_seconds") != selected.get("local_runtime_seconds"):
                errors.append(f"{prefix} local runtime estimate does not match selected provider")
        if status in {"reserved", "action_required"} and row.get("actual") is not None:
            errors.append(f"{prefix} cannot record actual cost before reconciliation")
        if status == "action_required" and not str(row.get("reason") or "").strip():
            errors.append(f"{prefix} action_required reason is missing")
        if status in {"success", "failed"}:
            if row.get("actual") is None or not row.get("reconciled_at"):
                errors.append(f"{prefix} lacks reconciled actual cost evidence")
            if row.get("actual_cost_strategy") not in {"fixed", "result_field", "local_runtime"}:
                errors.append(f"{prefix} actual cost strategy is invalid")
            actual_evidence = row.get("actual_cost_evidence")
            if not isinstance(actual_evidence, dict) or actual_evidence.get("elapsed_seconds") is None:
                errors.append(f"{prefix} actual cost evidence is missing")
            else:
                receipt_result: dict[str, Any] | None = None
                if status == "success":
                    receipt_errors, receipt = _result_receipt_errors(
                        actual_evidence.get("result_receipt") or {}, row,
                    )
                    errors.extend(f"{prefix} {error}" for error in receipt_errors)
                    receipt_result = receipt.get("result") if isinstance(receipt, dict) else None
                    if actual_evidence.get("result_integrity_sha256") != _stable_hash(
                        receipt_result or {}
                    ):
                        errors.append(f"{prefix} result evidence hash is invalid")
                try:
                    if status == "failed":
                        expected_actual = float(selected.get("failure_incremental_cost"))
                    elif selected.get("actual_cost_strategy") == "fixed":
                        expected_actual = float(
                            selected.get("fixed_actual_cost")
                            if selected.get("fixed_actual_cost") is not None
                            else selected.get("incremental_cost")
                        )
                    elif selected.get("actual_cost_strategy") == "local_runtime":
                        expected_actual = float(actual_evidence["elapsed_seconds"]) * float(
                            selected.get("cost_per_runtime_second")
                        )
                    else:
                        field = str(selected.get("actual_cost_result_field") or "actual_cost")
                        expected_actual = float((receipt_result or {})[field])
                        if float(actual_evidence.get("result_cost_value")) != expected_actual:
                            raise ValueError("stale provider result value")
                    if abs(float(row.get("actual")) - expected_actual) > 0.000001:
                        errors.append(f"{prefix} actual cost does not match selected provider strategy")
                except (KeyError, TypeError, ValueError):
                    errors.append(f"{prefix} actual cost does not match selected provider strategy")
    totals = {
        "estimated": round(sum(float(row.get("estimate") or 0) for row in rows), 6),
        "reserved": round(sum(float(row.get("estimate") or 0) for row in rows
                              if row.get("status") == "reserved"), 6),
        "actual": round(sum(float(row.get("actual") or 0) for row in rows
                            if row.get("status") in {"success", "failed"}), 6),
    }
    if ledger.get("totals") != totals:
        errors.append("cost ledger totals do not reconcile")
    if ledger.get("integrity_sha256") != _stable_hash(expected):
        errors.append("cost ledger integrity hash is stale")
    implementation = ledger.get("implementation") or {}
    path = Path(str(implementation.get("path") or ""))
    if not path.is_file() or path.resolve() != Path(__file__).resolve() or (
        implementation.get("sha256") != (sha256_file(path) if path.is_file() else None)
    ):
        errors.append("cost ledger implementation binding is stale")
    return errors
