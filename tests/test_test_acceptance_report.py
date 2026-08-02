from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from test_acceptance_report import (  # noqa: E402
    REQUIRED_TEST_CASES,
    REQUIRED_TEST_IDS,
    source_tree_sha256,
    validate_report,
    write_report_from_output,
)


class TestAcceptanceReportTests(unittest.TestCase):
    @staticmethod
    def _result_lines(*, statuses: dict[str, str] | None = None) -> list[str]:
        statuses = statuses or {}
        return [
            f"{test_id} ({test_case}) ... "
            f"{statuses.get(test_id, 'ok')}"
            for test_id, test_case in zip(REQUIRED_TEST_IDS, REQUIRED_TEST_CASES)
        ]

    @classmethod
    def _successful_log(cls) -> str:
        return "\n".join([
            *cls._result_lines(),
            "----------------------------------------------------------------------",
            f"Ran {len(REQUIRED_TEST_IDS)} tests in 0.001s",
            "",
            "OK",
        ])

    @staticmethod
    def _source_root(folder: str) -> Path:
        root = Path(folder)
        (root / "scripts").mkdir()
        (root / "tests" / "fixtures").mkdir(parents=True)
        (root / "scripts" / "runner.py").write_text("print('run')\n", encoding="utf-8")
        (root / "tests" / "test_runner.py").write_text("# test\n", encoding="utf-8")
        return root

    def _write(self, root: Path, log: str, *, returncode: int = 0) -> dict[str, object]:
        return write_report_from_output(
            root,
            log,
            root / "receipt.json",
            root / "receipt.log",
            returncode=returncode,
        )

    def test_rejects_required_ids_that_are_not_test_result_rows(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = self._source_root(folder)
            fabricated = "\n".join([
                *REQUIRED_TEST_IDS,
                f"Ran {len(REQUIRED_TEST_IDS)} tests in 0.001s",
                "OK",
            ])

            report = self._write(root, fabricated)

            self.assertFalse(report["passed"])
            self.assertTrue(validate_report(report, root))

    def test_rejects_count_and_result_summary_mismatches(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = self._source_root(folder)
            wrong_count = self._successful_log().replace(
                f"Ran {len(REQUIRED_TEST_IDS)} tests",
                f"Ran {len(REQUIRED_TEST_IDS) + 1} tests",
            )
            contradictory_result = "\n".join([
                *self._result_lines(statuses={REQUIRED_TEST_IDS[0]: "FAIL"}),
                "----------------------------------------------------------------------",
                f"Ran {len(REQUIRED_TEST_IDS)} tests in 0.001s",
                "",
                "OK",
            ])

            self.assertFalse(self._write(root, wrong_count)["passed"])
            self.assertFalse(self._write(root, contradictory_result)["passed"])

    def test_validation_reparses_bound_log_and_rejects_tampered_counts(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = self._source_root(folder)
            report = self._write(root, self._successful_log())
            self.assertEqual(validate_report(report, root), [])

            report["test_count"] = int(report["test_count"]) + 1

            self.assertTrue(validate_report(report, root))

    def test_receipt_uses_portable_paths_and_sanitizes_machine_paths(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = self._source_root(folder)
            raw_log = "\n".join([
                f"diagnostic repository={root}",
                r"diagnostic private=C:\Users\person\secret\token.txt",
                r"diagnostic unc=\\server\share\private\token.txt",
                r"diagnostic device=\\?\C:\private\token.txt",
                "diagnostic unix=/tmp/private/token.txt",
                "diagnostic mac=/private/var/folders/private/token.txt",
                "Authorization: Bearer abc.def.secret",
                "api_key=private-value",
                "DIRECTOR_REVIEW_TOKEN=review-value",
                "OPENAI_API_KEY=openai-value",
                "AWS_SECRET_ACCESS_KEY=aws-value",
                self._successful_log(),
            ])

            report = self._write(root, raw_log)
            stored_log = (root / str(report["log"])).read_text(encoding="utf-8")
            serialized_report = (root / "receipt.json").read_text(encoding="utf-8")

            self.assertEqual(report["log"], "receipt.log")
            self.assertEqual(report["runner_implementation"],
                             "scripts/test_acceptance_report.py")
            self.assertEqual(report["command"][0], "python")
            self.assertNotIn(str(root), stored_log)
            self.assertNotIn(r"C:\Users\person", stored_log)
            self.assertNotIn(r"\\server\share", stored_log)
            self.assertNotIn("/tmp/private", stored_log)
            self.assertNotIn("abc.def.secret", stored_log)
            self.assertNotIn("private-value", stored_log)
            self.assertNotIn("review-value", stored_log)
            self.assertNotIn("openai-value", stored_log)
            self.assertNotIn("aws-value", stored_log)
            self.assertNotIn(str(root), serialized_report)
            self.assertEqual(validate_report(report, root), [])

    def test_validation_rejects_absolute_or_escaping_log_paths(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = self._source_root(folder)
            report = self._write(root, self._successful_log())

            report["log"] = str((root / "receipt.log").resolve())
            self.assertTrue(validate_report(report, root))
            report["log"] = "../receipt.log"
            self.assertTrue(validate_report(report, root))

    def test_required_test_names_cannot_be_satisfied_by_other_test_cases(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = self._source_root(folder)
            impostor = "\n".join([
                *(f"{test_id} (impostor.Case.{test_id}) ... ok"
                  for test_id in REQUIRED_TEST_IDS),
                f"Ran {len(REQUIRED_TEST_IDS)} tests in 0.001s",
                "",
                "OK",
            ])

            report = self._write(root, impostor)

            self.assertFalse(report["passed"])
            self.assertTrue(validate_report(report, root))

    def test_receipt_rejects_output_inside_hashed_source_tree(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = self._source_root(folder)

            with self.assertRaisesRegex(ValueError, "scripts/ or tests"):
                write_report_from_output(
                    root,
                    self._successful_log(),
                    root / "tests" / "receipt.json",
                    root / "tests" / "receipt.log",
                    returncode=0,
                )

    def test_skips_and_failures_are_taken_from_bound_log(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = self._source_root(folder)
            statuses = {
                REQUIRED_TEST_IDS[0]: "FAIL",
                REQUIRED_TEST_IDS[1]: "skipped 'not available'",
            }
            log = "\n".join([
                *self._result_lines(statuses=statuses),
                "----------------------------------------------------------------------",
                f"Ran {len(REQUIRED_TEST_IDS)} tests in 0.001s",
                "",
                "FAILED (failures=1, skipped=1)",
            ])

            report = self._write(root, log, returncode=1)

            self.assertEqual(report["test_count"], len(REQUIRED_TEST_IDS))
            self.assertEqual(report["failed"], 1)
            self.assertEqual(report["skipped"], 1)
            self.assertFalse(report["passed"])

    def test_source_digest_covers_fixture_and_non_python_script_inputs(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = self._source_root(folder)
            fixture = root / "tests" / "fixtures" / "scenario.json"
            script_input = root / "scripts" / "tool-config.json"
            fixture.write_text('{"version": 1}\n', encoding="utf-8")
            script_input.write_text('{"enabled": true}\n', encoding="utf-8")
            original = source_tree_sha256(root)

            fixture.write_text('{"version": 2}\n', encoding="utf-8")
            after_fixture_change = source_tree_sha256(root)
            script_input.write_text('{"enabled": false}\n', encoding="utf-8")
            after_script_change = source_tree_sha256(root)

            self.assertNotEqual(original, after_fixture_change)
            self.assertNotEqual(after_fixture_change, after_script_change)


if __name__ == "__main__":
    unittest.main()
