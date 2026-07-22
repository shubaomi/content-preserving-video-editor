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
)


_RESULT_LINE = re.compile(
    r"^(?P<test_id>[^\s(]+)\s+\([^)]+\)\s+\.\.\.\s+"
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
    observed = {status: 0 for status in _SUMMARY_KEYS.values()}
    for match in _RESULT_LINE.finditer(output_text):
        raw_status = match.group("status")
        status = "skipped" if raw_status.startswith("skipped") else raw_status
        result_rows.append((match.group("test_id"), status))
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


def write_report_from_output(
    root: Path, output_text: str, report_path: Path, log_path: Path,
    *, returncode: int,
) -> dict[str, Any]:
    root = root.resolve()
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(output_text, encoding="utf-8")
    parsed = _parse_unittest_output(output_text)
    required_tests_ran = all(test_id in parsed["test_ids"] for test_id in REQUIRED_TEST_IDS)
    report = {
        "schema_version": 1,
        "passed": parsed["valid"] and parsed["result"] == "OK" and returncode == 0
        and parsed["failed"] == 0 and parsed["skipped"] == 0 and required_tests_ran,
        "test_count": parsed["test_count"], "failed": parsed["failed"],
        "skipped": parsed["skipped"], "exit_code": returncode,
        "command": [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        "required_test_ids": list(REQUIRED_TEST_IDS),
        "source_tree_sha256": source_tree_sha256(root),
        "runner_implementation": str(Path(__file__).resolve()),
        "runner_implementation_sha256": sha256_file(Path(__file__).resolve()),
        "log": str(log_path.resolve()), "log_sha256": sha256_file(log_path),
    }
    write_json(report_path, report)
    return report


def validate_report(report: dict[str, Any], root: Path) -> list[str]:
    errors: list[str] = []
    log_path = Path(str(report.get("log", "")))
    log = log_path.read_text(encoding="utf-8") if log_path.is_file() else ""
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
        or any(test_id not in parsed["test_ids"] for test_id in REQUIRED_TEST_IDS)
        or report.get("source_tree_sha256") != source_tree_sha256(root.resolve())
        or report.get("runner_implementation_sha256") != sha256_file(Path(__file__).resolve())
        or not log_path.is_file()
        or report.get("log_sha256") != (sha256_file(log_path) if log_path.is_file() else None)
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
