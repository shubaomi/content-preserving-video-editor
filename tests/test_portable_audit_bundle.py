from __future__ import annotations

import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from portable_audit_bundle import create_portable_audit_bundle  # noqa: E402
from verify_audit_bundle import verify_audit_bundle  # noqa: E402


class PortableAuditBundleTests(unittest.TestCase):
    def test_bundle_is_relative_relocatable_and_excludes_sensitive_files(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            (root / "reports").mkdir(parents=True)
            safe = root / "reports" / "qa.json"
            safe.write_text(json.dumps({"status": "pass", "project": str(root),
                                        "external": r"C:\Users\someone\private.jpg"}),
                            encoding="utf-8")
            yaml_evidence = root / "reports" / "project.yaml"
            yaml_evidence.write_text(
                f'root: "{root.as_posix()}"\nexternal: "C:/Users/someone/private.jpg"\n',
                encoding="utf-8",
            )
            secret = root / ".env"
            secret.write_text("API_KEY=do-not-copy", encoding="utf-8")
            disguised_secret = root / "reports" / "notes.txt"
            disguised_secret.write_text("client_secret=also-do-not-copy", encoding="utf-8")
            bundle = Path(temp) / "bundle"
            manifest = create_portable_audit_bundle(
                root, bundle, [safe, yaml_evidence, secret, disguised_secret],
            )

            self.assertIn(
                "artifacts/reports/qa.json",
                {entry["path"] for entry in manifest["entries"]},
            )
            self.assertNotIn(str(root), json.dumps(manifest))
            self.assertEqual({row["reason"] for row in manifest["excluded"]},
                             {"sensitive_path", "sensitive_content"})
            self.assertFalse((bundle / "artifacts" / ".env").exists())
            copied = (bundle / "artifacts" / "reports" / "qa.json").read_text(encoding="utf-8")
            self.assertNotIn(str(root), copied)
            self.assertNotIn(r"C:\Users", copied)
            self.assertIn("$PROJECT_ROOT", copied)
            copied_yaml = (bundle / "artifacts" / "reports" / "project.yaml").read_text(
                encoding="utf-8",
            )
            self.assertNotIn(str(root), copied_yaml)
            self.assertNotIn("C:/Users", copied_yaml)
            self.assertIn("$PROJECT_ROOT", copied_yaml)

            moved = Path(temp) / "offline-copy"
            shutil.copytree(bundle, moved)
            result = verify_audit_bundle(moved)
            self.assertEqual(result["status"], "pass")
            self.assertTrue(result["offline_verification"])

    def test_replace_failure_preserves_previous_verified_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            source = root / "qa.json"
            source.write_text('{"status":"old"}', encoding="utf-8")
            bundle = Path(temp) / "bundle"
            create_portable_audit_bundle(root, bundle, [source])
            old_manifest = (bundle / "audit-bundle.json").read_bytes()
            missing = root / "missing.json"
            with self.assertRaisesRegex(ValueError, "does not exist"):
                create_portable_audit_bundle(root, bundle, [missing], replace=True)
            self.assertEqual((bundle / "audit-bundle.json").read_bytes(), old_manifest)
            self.assertEqual(verify_audit_bundle(bundle)["status"], "pass")

    def test_malformed_structured_and_unsupported_binary_inputs_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            malformed = root / "broken.json"
            malformed.write_text('{"path":', encoding="utf-8")
            binary = root / "opaque.bin"
            binary.write_bytes(b"opaque")
            bundle = Path(temp) / "bundle"
            manifest = create_portable_audit_bundle(root, bundle, [malformed, binary])
            self.assertEqual(manifest["entries"], [])
            self.assertEqual(
                {entry["reason"] for entry in manifest["excluded"]},
                {"structured_parse_failed", "unsupported_binary_or_unstructured_input"},
            )

    def test_common_review_bearer_and_provider_tokens_are_excluded(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            secrets = root / "runtime.log"
            secrets.write_text(
                "DIRECTOR_REVIEW_TOKEN=not-safe-token\n"
                "Authorization: Bearer abcdefghijklmnop\n"
                "OPENAI_API_KEY=sk-abcdefghijklmnop\n",
                encoding="utf-8",
            )
            manifest = create_portable_audit_bundle(root, Path(temp) / "bundle", [secrets])
            self.assertEqual(manifest["entries"], [])
            self.assertEqual(manifest["excluded"][0]["reason"], "sensitive_content")

    def test_interrupted_directory_swap_restores_verified_backup_on_next_run(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            source = root / "qa.json"
            source.write_text('{"status":"old"}', encoding="utf-8")
            bundle = Path(temp) / "bundle"
            create_portable_audit_bundle(root, bundle, [source])
            backup = bundle.with_name(".bundle.replace-backup-fixture")
            bundle.rename(backup)
            source.write_text('{"status":"new"}', encoding="utf-8")
            create_portable_audit_bundle(root, bundle, [source], replace=True)
            self.assertFalse(backup.exists())
            self.assertEqual(verify_audit_bundle(bundle)["status"], "pass")

    def test_retired_backup_cleanup_failure_does_not_block_valid_bundle(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            source = root / "qa.json"
            source.write_text('{"version":1}', encoding="utf-8")
            bundle = Path(temp) / "bundle"
            create_portable_audit_bundle(root, bundle, [source])
            source.write_text('{"version":2}', encoding="utf-8")
            with patch("portable_audit_bundle.shutil.rmtree", side_effect=OSError("busy")):
                create_portable_audit_bundle(root, bundle, [source], replace=True)
            self.assertEqual(verify_audit_bundle(bundle)["status"], "pass")
            source.write_text('{"version":3}', encoding="utf-8")
            create_portable_audit_bundle(root, bundle, [source], replace=True)
            self.assertEqual(verify_audit_bundle(bundle)["status"], "pass")

    def test_tampered_file_and_manifest_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp) / "project"
            root.mkdir()
            source = root / "qa.json"
            source.write_text("{}", encoding="utf-8")
            bundle = Path(temp) / "bundle"
            create_portable_audit_bundle(root, bundle, [source])
            (bundle / "artifacts" / "qa.json").write_text("tampered", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash"):
                verify_audit_bundle(bundle)

            second_bundle = Path(temp) / "bundle-2"
            create_portable_audit_bundle(root, second_bundle, [source])
            manifest_path = second_bundle / "audit-bundle.json"
            data = json.loads(manifest_path.read_text(encoding="utf-8"))
            data["payload"]["entries"][0]["size"] = 999
            manifest_path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "manifest payload hash"):
                verify_audit_bundle(second_bundle)


if __name__ == "__main__":
    unittest.main()
