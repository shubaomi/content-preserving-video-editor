from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from review_server import (  # noqa: E402
    RequestRejected,
    ReviewServerConfig,
    propose_pending_change,
    propose_event_action,
    validate_bind_host,
    validate_request,
)


class ReviewServerTests(unittest.TestCase):
    def _config(self, root: Path) -> ReviewServerConfig:
        return ReviewServerConfig(
            root=root, proposal_dir=root / "proposals", auth_token="secret-token",
            csrf_token="csrf-token", max_body_bytes=256,
        )

    def _headers(self, body: bytes = b"") -> dict[str, str]:
        return {
            "Host": "127.0.0.1:8765",
            "Origin": "http://127.0.0.1:8765",
            "Authorization": "Bearer secret-token",
            "X-CSRF-Token": "csrf-token",
            "Content-Length": str(len(body)),
        }

    def test_localhost_only_and_all_request_guards(self) -> None:
        for host in ("127.0.0.1", "::1", "localhost"):
            validate_bind_host(host)
        for host in ("0.0.0.0", "192.168.1.10", "example.com"):
            with self.subTest(host=host), self.assertRaises(RequestRejected):
                validate_bind_host(host)
        with tempfile.TemporaryDirectory() as folder:
            config = self._config(Path(folder))
            body = b'{}'
            validate_request(config, method="POST", path="/api/proposals", headers=self._headers(body), body=body)
            mutations = (
                ("Host", "evil.example"), ("Origin", "https://evil.example"),
                ("Authorization", "Bearer wrong"), ("X-CSRF-Token", "wrong"),
            )
            for name, value in mutations:
                headers = self._headers(body)
                headers[name] = value
                with self.subTest(name=name), self.assertRaises(RequestRejected):
                    validate_request(config, method="POST", path="/api/proposals", headers=headers, body=body)
            with self.assertRaisesRegex(RequestRejected, "body"):
                validate_request(
                    config, method="POST", path="/api/proposals",
                    headers=self._headers(b"x" * 257), body=b"x" * 257,
                )
            with self.assertRaisesRegex(RequestRejected, "path"):
                validate_request(config, method="GET", path="/../../secret", headers=self._headers(), body=b"")

    def test_proposal_is_path_allowlisted_and_can_only_be_pending(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            artifact = root / "reviewable.json"
            artifact.write_text('{"value":1}', encoding="utf-8")
            config = self._config(root)
            proposal = propose_pending_change(config, {
                "target_path": "reviewable.json", "operation": "replace",
                "pointer": "/value", "value": 2, "reason": "human review suggestion",
            })
            self.assertEqual(proposal["status"], "pending")
            self.assertEqual(json.loads(artifact.read_text(encoding="utf-8"))["value"], 1)
            self.assertTrue((config.proposal_dir / f"{proposal['proposal_id']}.json").is_file())
            with self.assertRaisesRegex(RequestRejected, "pending"):
                propose_pending_change(config, {
                    "target_path": "reviewable.json", "operation": "replace",
                    "pointer": "/value", "value": 2, "status": "approved",
                })

    def test_event_actions_are_hash_bound_pending_requests_and_never_edit_artifact(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            artifact = root / "storyboard.json"
            original = b'{"events":[{"event_id":"event-1","x":10}]}'
            artifact.write_bytes(original)
            digest = hashlib.sha256(original).hexdigest()
            config = self._config(root)
            for action in (
                "approve", "reject", "move", "resize", "hide", "change_variant",
                "change_anchor", "change_sfx", "request_regeneration",
            ):
                with self.subTest(action=action):
                    request = propose_event_action(config, {
                        "action": action,
                        "event_id": "event-1",
                        "target_path": "storyboard.json",
                        "target_sha256": digest,
                        "selector": "#event-1",
                        "before_value": {"state": "before"},
                        "after_value": {"state": action},
                        "reason": "reviewed visual correction",
                        "approver": "reviewer",
                        "timestamp": "2026-08-02T12:00:00+00:00",
                        "related_files": [{"path": "storyboard.json", "sha256": digest}],
                    })
                    self.assertEqual(request["status"], "pending")
                    self.assertEqual(request["request_type"], "correction")
                    self.assertFalse(request["applied"])
                    self.assertEqual(artifact.read_bytes(), original)

    def test_event_action_rejects_missing_fields_stale_hash_and_bad_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            artifact = root / "storyboard.json"
            artifact.write_text("{}", encoding="utf-8")
            digest = hashlib.sha256(artifact.read_bytes()).hexdigest()
            config = self._config(root)
            valid = {
                "action": "move", "event_id": "event-1", "target_path": "storyboard.json",
                "target_sha256": digest, "selector": "#event-1", "before_value": [1, 2],
                "after_value": [3, 4], "reason": "align to safe area", "approver": "reviewer",
                "timestamp": "2026-08-02T12:00:00+00:00",
                "related_files": [{"path": "storyboard.json", "sha256": digest}],
            }
            for field in (
                "event_id", "selector", "before_value", "after_value", "reason",
                "approver", "timestamp", "related_files",
            ):
                broken = dict(valid)
                broken.pop(field)
                with self.subTest(field=field), self.assertRaises(RequestRejected):
                    propose_event_action(config, broken)
            stale = dict(valid, target_sha256="0" * 64)
            with self.assertRaisesRegex(RequestRejected, "stale"):
                propose_event_action(config, stale)
            outside = root.parent / "outside-evidence.json"
            outside.write_text("{}", encoding="utf-8")
            bad_evidence = dict(valid, related_files=[{
                "path": str(outside), "sha256": hashlib.sha256(outside.read_bytes()).hexdigest(),
            }])
            with self.assertRaisesRegex(RequestRejected, "allowlisted root"):
                propose_event_action(config, bad_evidence)

    def test_request_guards_reject_encoded_traversal_chunking_and_length_mismatch(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            config = self._config(Path(folder))
            body = b"{}"
            for path in ("/%2e%2e/secret", "/api%5cproposals", "/api/proposals?next=/"):
                with self.subTest(path=path), self.assertRaises(RequestRejected):
                    validate_request(config, method="POST", path=path, headers=self._headers(body), body=body)
            headers = self._headers(body)
            headers["Transfer-Encoding"] = "chunked"
            with self.assertRaisesRegex(RequestRejected, "chunked"):
                validate_request(config, method="POST", path="/api/proposals", headers=headers, body=body)
            headers = self._headers(body)
            headers["Content-Length"] = "99"
            with self.assertRaisesRegex(RequestRejected, "length"):
                validate_request(config, method="POST", path="/api/proposals", headers=headers, body=body)
            with self.assertRaisesRegex(RequestRejected, "allowlisted root"):
                propose_pending_change(config, {
                    "target_path": "../outside.json", "operation": "replace",
                    "pointer": "/value", "value": 2,
                })


if __name__ == "__main__":
    unittest.main()
