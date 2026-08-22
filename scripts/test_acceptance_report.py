#!/usr/bin/env python3
"""Run the complete test suite and retain a source-bound, zero-skip receipt."""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from director_contracts import sha256_file, write_json


REQUIRED_TEST_IDS = (
    "test_all_six_acceptance_types_have_real_decodable_short_media_evidence",
    "test_complete_hash_bound_fixture_passes_all_completion_criteria",
    "test_old_state_migration_invalidates_all_unverifiable_completed_work",
    "test_concurrent_identical_request_set_serializes_manifest_creation",
    "test_platform_validation_rebuilds_reports_when_cover_bytes_change",
    "test_wp4_install_creates_only_fixed_new_test_target_without_store_enumeration",
    "test_wp4_install_cleans_staging_when_atomic_promotion_fails",
    "test_wp4_install_cleans_identity_bound_partial_staging_on_copy_failure",
    "test_wp4_receipt_validation_returns_error_on_target_identity_race",
    "test_wp4_validation_and_rollback_reject_project_root_as_store",
    "test_wp4_rollback_requires_exact_unchanged_generated_inventory",
)
REQUIRED_TEST_CASES = (
    "test_technical_qa.TechnicalQaTests."
    "test_all_six_acceptance_types_have_real_decodable_short_media_evidence",
    "test_completion_audit.CompletionAuditTests."
    "test_complete_hash_bound_fixture_passes_all_completion_criteria",
    "test_director.DirectorTests."
    "test_old_state_migration_invalidates_all_unverifiable_completed_work",
    "test_media_catalog_adapter.MediaCatalogAdapterTests."
    "test_concurrent_identical_request_set_serializes_manifest_creation",
    "test_director.DirectorTests."
    "test_platform_validation_rebuilds_reports_when_cover_bytes_change",
    "test_jianying_native_draft.JianyingNativeDraftV1Tests."
    "test_wp4_install_creates_only_fixed_new_test_target_without_store_enumeration",
    "test_jianying_native_draft.JianyingNativeDraftV1Tests."
    "test_wp4_install_cleans_staging_when_atomic_promotion_fails",
    "test_jianying_native_draft.JianyingNativeDraftV1Tests."
    "test_wp4_install_cleans_identity_bound_partial_staging_on_copy_failure",
    "test_jianying_native_draft.JianyingNativeDraftV1Tests."
    "test_wp4_receipt_validation_returns_error_on_target_identity_race",
    "test_jianying_native_draft.JianyingNativeDraftV1Tests."
    "test_wp4_validation_and_rollback_reject_project_root_as_store",
    "test_jianying_native_draft.JianyingNativeDraftV1Tests."
    "test_wp4_rollback_requires_exact_unchanged_generated_inventory",
)


_RESULT_LINE = re.compile(
    r"^(?P<test_id>[^\s(]+)\s+\((?P<test_case>[^)]+)\)\s+\.\.\.\s+"
    r"(?P<status>ok|FAIL|ERROR|skipped(?:\s+.*)?|expected failure|unexpected success)\s*$",
    re.MULTILINE,
)
_COUNT_LINE = re.compile(r"^Ran\s+(\d+)\s+tests?\s+in\s+.+$", re.MULTILINE)
_SUMMARY_LINE = re.compile(r"^(OK|FAILED)(?:\s+\(([^)]*)\))?\s*$", re.MULTILINE)
_SUMMARY_KEYS = {
    "failures": "FAIL",
    "errors": "ERROR",
    "skipped": "skipped",
    "expected failures": "expected failure",
    "unexpected successes": "unexpected success",
}
_PORTABLE_COMMAND = ["python", "-m", "unittest", "discover", "-s", "tests", "-v"]
_RUNNER_PATH = "scripts/test_acceptance_report.py"
_WINDOWS_ABSOLUTE_PATH = re.compile(
    r"(?i)(?:\\\\\?\\[A-Z]:\\|\\\\[^\\/\s]+\\[^\\/\s]+\\|[A-Z]:[\\/])"
    r"[^\s\"'<>|]*"
)
_UNIX_ABSOLUTE_PATH = re.compile(
    r"(?<![A-Za-z0-9_:/])/(?:[^/\s\"'<>|]+/)*[^/\s\"'<>|]*"
)
_SECRET_ASSIGNMENT = re.compile(
    r"(?i)\b([A-Za-z0-9_]*(?:token|api[_-]?key|password|secret|authorization|cookie)"
    r"[A-Za-z0-9_]*)\b"
    r"\s*([:=])\s*(?:\"[^\"]*\"|'[^']*'|\S+)"
)
_BEARER_SECRET = re.compile(r"(?i)\bBearer\s+[A-Za-z0-9._~+/=-]+")
_PRIVATE_KEY = re.compile(
    r"-----BEGIN [^-\r\n]*PRIVATE KEY-----.*?-----END [^-\r\n]*PRIVATE KEY-----",
    re.DOTALL,
)


def _parse_summary_counts(detail: str | None) -> dict[str, int] | None:
    counts = {key: 0 for key in _SUMMARY_KEYS}
    if not detail:
        return counts
    for item in detail.split(","):
        match = re.fullmatch(r"\s*([a-z ]+)=(\d+)\s*", item)
        if not match or match.group(1) not in counts:
            return None
        counts[match.group(1)] = int(match.group(2))
    return counts


def _parse_unittest_output(output_text: str) -> dict[str, Any]:
    result_rows = []
    test_cases = []
    observed = {status: 0 for status in _SUMMARY_KEYS.values()}
    for match in _RESULT_LINE.finditer(output_text):
        raw_status = match.group("status")
        status = "skipped" if raw_status.startswith("skipped") else raw_status
        result_rows.append((match.group("test_id"), status))
        test_cases.append(match.group("test_case"))
        if status != "ok":
            observed[status] += 1

    count_matches = list(_COUNT_LINE.finditer(output_text))
    count = int(count_matches[0].group(1)) if len(count_matches) == 1 else 0
    summaries = (
        list(_SUMMARY_LINE.finditer(output_text, count_matches[0].end()))
        if len(count_matches) == 1 else []
    )
    result = summaries[-1].group(1) if len(summaries) == 1 else "INVALID"
    summary_counts = (
        _parse_summary_counts(summaries[0].group(2)) if len(summaries) == 1 else None
    )
    counts_reconcile = summary_counts is not None and all(
        summary_counts[key] == observed[status]
        for key, status in _SUMMARY_KEYS.items()
    )
    unsuccessful = observed["FAIL"] + observed["ERROR"] + observed["unexpected success"]
    result_reconciles = (
        (result == "OK" and unsuccessful == 0)
        or (result == "FAILED" and unsuccessful > 0)
    )
    return {
        "valid": (
            len(count_matches) == 1
            and len(summaries) == 1
            and count > 0
            and count == len(result_rows)
            and counts_reconcile
            and result_reconciles
        ),
        "test_count": count,
        "failed": sum(observed.values()) - observed["skipped"],
        "skipped": observed["skipped"],
        "result": result,
        "test_ids": [test_id for test_id, _status in result_rows],
        "test_cases": test_cases,
    }


def source_tree_sha256(root: Path) -> str:
    rows = []
    for folder in (root / "scripts", root / "tests"):
        for path in sorted(folder.rglob("*")):
            if (
                path.is_file()
                and not {"__pycache__", ".pytest_cache"}.intersection(path.parts)
                and path.suffix not in {".pyc", ".pyo"}
            ):
                rows.append((path.relative_to(root).as_posix(), sha256_file(path)))
    payload = json.dumps(rows, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _report_relative_path(path: Path, report_path: Path) -> str:
    try:
        return path.resolve().relative_to(report_path.resolve().parent).as_posix()
    except ValueError as exc:
        raise ValueError(f"acceptance log must remain beside or below its report: {path}") from exc


def _inside_hashed_source(path: Path, root: Path) -> bool:
    resolved = path.resolve()
    return any(resolved == folder or folder in resolved.parents
               for folder in (root.resolve() / "scripts", root.resolve() / "tests"))


def _sanitize_output(output_text: str, root: Path) -> str:
    sanitized = output_text
    for value in {str(root.resolve()), root.resolve().as_posix()}:
        sanitized = sanitized.replace(value, "$REPO_ROOT")
    sanitized = _WINDOWS_ABSOLUTE_PATH.sub("$ABS_PATH_REDACTED", sanitized)
    sanitized = _UNIX_ABSOLUTE_PATH.sub("$ABS_PATH_REDACTED", sanitized)
    sanitized = _BEARER_SECRET.sub("Bearer $SECRET_REDACTED", sanitized)
    sanitized = _SECRET_ASSIGNMENT.sub(
        lambda match: f"{match.group(1)}{match.group(2)}$SECRET_REDACTED", sanitized,
    )
    return _PRIVATE_KEY.sub("$PRIVATE_KEY_REDACTED", sanitized)


def write_report_from_output(
    root: Path, output_text: str, report_path: Path, log_path: Path,
    *, returncode: int,
) -> dict[str, Any]:
    root = root.resolve()
    report_path = report_path.resolve()
    log_path = log_path.resolve()
    if _inside_hashed_source(report_path, root) or _inside_hashed_source(log_path, root):
        raise ValueError("acceptance artifacts cannot be written inside scripts/ or tests/")
    portable_log_path = _report_relative_path(log_path, report_path)
    log_path.parent.mkdir(parents=True, exist_ok=True)
    sanitized_output = _sanitize_output(output_text, root)
    log_bytes = sanitized_output.encode("utf-8")
    log_path.write_bytes(log_bytes)
    parsed = _parse_unittest_output(sanitized_output)
    required_tests_ran = (
        len(set(parsed["test_cases"])) == len(parsed["test_cases"])
        and all(test_case in parsed["test_cases"] for test_case in REQUIRED_TEST_CASES)
    )
    report = {
        "schema_version": 1,
        "passed": parsed["valid"] and parsed["result"] == "OK" and returncode == 0
        and parsed["failed"] == 0 and parsed["skipped"] == 0 and required_tests_ran,
        "test_count": parsed["test_count"], "failed": parsed["failed"],
        "skipped": parsed["skipped"], "exit_code": returncode,
        "command": _PORTABLE_COMMAND,
        "required_test_ids": list(REQUIRED_TEST_IDS),
        "required_test_cases": list(REQUIRED_TEST_CASES),
        "source_tree_sha256": source_tree_sha256(root),
        "runner_implementation": _RUNNER_PATH,
        "runner_implementation_sha256": sha256_file(Path(__file__).resolve()),
        "log": portable_log_path,
        "log_sha256": hashlib.sha256(log_bytes).hexdigest(),
    }
    write_json(report_path, report)
    return report


def validate_report(
    report: dict[str, Any], root: Path, report_path: Path | None = None,
) -> list[str]:
    errors: list[str] = []
    root = root.resolve()
    stored_log_path = Path(str(report.get("log", "")))
    report_base = report_path.resolve().parent if report_path else root
    try:
        if stored_log_path.is_absolute():
            raise ValueError("absolute log path")
        log_path = (report_base / stored_log_path).resolve()
        log_path.relative_to(report_base)
    except ValueError:
        log_path = root / ".invalid-test-suite-log"
    try:
        log_bytes = log_path.read_bytes() if log_path.is_file() else b""
        log = log_bytes.decode("utf-8")
    except (OSError, UnicodeDecodeError):
        log_bytes = b""
        log = ""
    parsed = _parse_unittest_output(log)
    try:
        reported_count = int(report.get("test_count", 0))
        reported_failed = int(report.get("failed", -1))
        reported_skipped = int(report.get("skipped", -1))
        reported_exit_code = int(report.get("exit_code", -1))
    except (TypeError, ValueError):
        reported_count = reported_failed = reported_skipped = reported_exit_code = -1
    if (
        report.get("schema_version") != 1
        or report.get("passed") is not True
        or not parsed["valid"]
        or parsed["result"] != "OK"
        or reported_count != parsed["test_count"]
        or reported_failed != parsed["failed"]
        or reported_skipped != parsed["skipped"]
        or reported_count <= 0
        or reported_failed != 0
        or reported_skipped != 0
        or reported_exit_code != 0
        or report.get("required_test_ids") != list(REQUIRED_TEST_IDS)
        or report.get("required_test_cases") != list(REQUIRED_TEST_CASES)
        or report.get("command") != _PORTABLE_COMMAND
        or report.get("runner_implementation") != _RUNNER_PATH
        or len(set(parsed["test_cases"])) != len(parsed["test_cases"])
        or any(test_case not in parsed["test_cases"] for test_case in REQUIRED_TEST_CASES)
        or report.get("source_tree_sha256") != source_tree_sha256(root.resolve())
        or report.get("runner_implementation_sha256") != sha256_file(Path(__file__).resolve())
        or not log_path.is_file()
        or report.get("log_sha256") != hashlib.sha256(log_bytes).hexdigest()
    ):
        errors.append("test-suite receipt is missing, stale, skipped, failed, or lacks required tests")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=str(Path(__file__).parents[1]))
    parser.add_argument("--report", required=True)
    parser.add_argument("--log", required=True)
    args = parser.parse_args()
    root = Path(args.root).resolve()
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    run = subprocess.run(command, cwd=root, capture_output=True, text=True,
                         encoding="utf-8", errors="replace")
    output = (run.stdout or "") + (run.stderr or "")
    report = write_report_from_output(
        root, output, Path(args.report), Path(args.log), returncode=run.returncode,
    )
    print(Path(args.report).resolve())
    return 0 if report["passed"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
