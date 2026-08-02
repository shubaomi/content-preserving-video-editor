#!/usr/bin/env python3
"""Serve a localhost-only review API that can create pending proposals only."""
from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import unquote, urlsplit

from director_contracts import sha256_file, write_json


READ_PATHS = {"/", "/index.html", "/api/artifacts"}
WRITE_PATHS = {"/api/proposals"}
EVENT_ACTIONS = {
    "approve", "reject", "move", "resize", "hide", "change_variant",
    "change_anchor", "change_sfx", "request_regeneration",
}


class RequestRejected(ValueError):
    """Raised when a review request crosses a local security boundary."""

    def __init__(self, message: str, *, status: int = 400) -> None:
        super().__init__(message)
        self.status = status


@dataclass(frozen=True)
class ReviewServerConfig:
    root: Path
    proposal_dir: Path
    auth_token: str
    csrf_token: str
    max_body_bytes: int = 64 * 1024

    def __post_init__(self) -> None:
        object.__setattr__(self, "root", self.root.resolve())
        object.__setattr__(self, "proposal_dir", self.proposal_dir.resolve())
        if not self.auth_token or not self.csrf_token:
            raise ValueError("review server auth and CSRF tokens are required")
        if isinstance(self.max_body_bytes, bool) or self.max_body_bytes <= 0:
            raise ValueError("review server max_body_bytes must be positive")
        if not self.proposal_dir.is_relative_to(self.root):
            raise ValueError("proposal_dir must remain inside the allowlisted root")


def _loopback_name(host: str) -> bool:
    lowered = host.strip().strip("[]").lower()
    if lowered == "localhost":
        return True
    try:
        return __import__("ipaddress").ip_address(lowered).is_loopback
    except ValueError:
        return False


def validate_bind_host(host: str) -> str:
    if not _loopback_name(host):
        raise RequestRejected("review server bind host must be localhost/loopback only")
    return host


def _headers(value: Mapping[str, str]) -> dict[str, str]:
    return {str(key).lower(): str(item).strip() for key, item in value.items()}


def _host_name(host_header: str) -> str:
    parsed = urlsplit(f"//{host_header}")
    if not parsed.hostname or not _loopback_name(parsed.hostname):
        raise RequestRejected("Host header must name localhost/loopback", status=403)
    return parsed.netloc.lower()


def _origin_name(origin: str) -> str:
    parsed = urlsplit(origin)
    if parsed.scheme != "http" or not parsed.hostname or not _loopback_name(parsed.hostname):
        raise RequestRejected("Origin must be an http localhost/loopback origin", status=403)
    if parsed.path not in ("", "/") or parsed.query or parsed.fragment:
        raise RequestRejected("Origin must not contain a path", status=403)
    return parsed.netloc.lower()


def validate_request(
    config: ReviewServerConfig, *, method: str, path: str,
    headers: Mapping[str, str], body: bytes,
) -> None:
    """Validate path, token, origin, CSRF, and bounded-body invariants."""
    method = method.upper()
    parsed_path = urlsplit(path)
    decoded_path = unquote(parsed_path.path)
    if parsed_path.query or parsed_path.fragment or "\\" in decoded_path or "\x00" in decoded_path:
        raise RequestRejected("request path is not allowlisted", status=404)
    allowed = READ_PATHS if method == "GET" else WRITE_PATHS if method == "POST" else set()
    if decoded_path not in allowed:
        raise RequestRejected("request path is not allowlisted", status=404)
    normalized = _headers(headers)
    host = _host_name(normalized.get("host", ""))
    origin = _origin_name(normalized.get("origin", ""))
    if origin != host:
        raise RequestRejected("Origin and Host must match", status=403)
    expected_auth = f"Bearer {config.auth_token}"
    if not hmac.compare_digest(normalized.get("authorization", ""), expected_auth):
        raise RequestRejected("review server token is invalid", status=401)
    if method == "POST":
        if not hmac.compare_digest(normalized.get("x-csrf-token", ""), config.csrf_token):
            raise RequestRejected("review server CSRF token is invalid", status=403)
        if "transfer-encoding" in normalized:
            raise RequestRejected("chunked request bodies are not accepted", status=411)
        try:
            declared_size = int(normalized.get("content-length", ""))
        except ValueError as error:
            raise RequestRejected("Content-Length is required", status=411) from error
        if declared_size != len(body):
            raise RequestRejected("request body length does not match Content-Length")
        if declared_size > config.max_body_bytes:
            raise RequestRejected("request body exceeds the configured limit", status=413)
    elif body:
        raise RequestRejected("GET request body is not accepted")


def _target_path(config: ReviewServerConfig, value: Any) -> Path:
    raw = str(value or "")
    path = Path(raw)
    candidate = path.resolve() if path.is_absolute() else (config.root / path).resolve()
    if not candidate.is_relative_to(config.root):
        raise RequestRejected("proposal target is outside the allowlisted root", status=403)
    if not candidate.is_file():
        raise RequestRejected("proposal target is not an allowlisted file", status=404)
    if candidate.is_relative_to(config.proposal_dir):
        raise RequestRejected("proposal target cannot be a pending proposal", status=403)
    return candidate


def _required_text(proposal: Mapping[str, Any], field: str, *, max_length: int = 2048) -> str:
    value = str(proposal.get(field) or "").strip()
    if not value or len(value) > max_length or any(ord(character) < 32 for character in value):
        raise RequestRejected(f"event action requires valid {field}")
    return value


def _parse_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise RequestRejected("event action timestamp must be ISO-8601") from error
    if parsed.tzinfo is None:
        raise RequestRejected("event action timestamp must include a timezone")
    return value


def _hash_bound_files(
    config: ReviewServerConfig, rows: Any, *, field: str = "related_files",
) -> list[dict[str, str]]:
    if not isinstance(rows, list) or not rows:
        raise RequestRejected(f"event action requires {field} hash evidence")
    result: list[dict[str, str]] = []
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise RequestRejected(f"{field}[{index}] must be an object")
        path = _target_path(config, row.get("path"))
        expected = str(row.get("sha256") or "").lower()
        actual = sha256_file(path)
        if not hmac.compare_digest(expected, actual):
            raise RequestRejected(f"{field}[{index}] hash evidence is stale", status=409)
        result.append({"path": str(path), "sha256": actual})
    return result


def propose_event_action(
    config: ReviewServerConfig, proposal: dict[str, Any],
) -> dict[str, Any]:
    """Create a hash-bound correction request without editing its target artifact."""
    if not isinstance(proposal, dict):
        raise RequestRejected("proposal body must be a JSON object")
    if proposal.get("status", "pending") != "pending":
        raise RequestRejected("review server may only create pending proposals", status=403)
    action = _required_text(proposal, "action", max_length=64)
    if action not in EVENT_ACTIONS:
        raise RequestRejected("event action is not supported")
    event_id = _required_text(proposal, "event_id", max_length=256)
    selector = _required_text(proposal, "selector", max_length=512)
    reason = _required_text(proposal, "reason")
    approver = _required_text(proposal, "approver", max_length=256)
    timestamp = _parse_timestamp(_required_text(proposal, "timestamp", max_length=128))
    if "before_value" not in proposal or "after_value" not in proposal:
        raise RequestRejected("event action requires before_value and after_value")
    if proposal["before_value"] == proposal["after_value"]:
        raise RequestRejected("event action before_value and after_value must differ")

    target = _target_path(config, proposal.get("target_path"))
    target_hash = sha256_file(target)
    expected_hash = str(proposal.get("target_sha256") or "").lower()
    if not expected_hash or not hmac.compare_digest(expected_hash, target_hash):
        raise RequestRejected("event action target hash is stale", status=409)
    related_files = _hash_bound_files(config, proposal.get("related_files"))
    canonical_payload = {
        "action": action,
        "event_id": event_id,
        "target_path": str(target),
        "target_sha256": target_hash,
        "selector": selector,
        "before_value": proposal["before_value"],
        "after_value": proposal["after_value"],
        "reason": reason,
        "approver": approver,
        "timestamp": timestamp,
        "related_files": related_files,
    }
    canonical = json.dumps(
        canonical_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    proposal_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    result = {
        "schema_version": 1,
        "proposal_id": proposal_id,
        "request_type": "correction",
        "status": "pending",
        **canonical_payload,
        "applied": False,
    }
    config.proposal_dir.mkdir(parents=True, exist_ok=True)
    write_json(config.proposal_dir / f"{proposal_id}.json", result)
    return result


def propose_pending_change(
    config: ReviewServerConfig, proposal: dict[str, Any],
) -> dict[str, Any]:
    """Persist a pending proposal while leaving the target artifact untouched."""
    if not isinstance(proposal, dict):
        raise RequestRejected("proposal body must be a JSON object")
    requested_status = proposal.get("status", "pending")
    if requested_status != "pending":
        raise RequestRejected("review server may only create pending proposals", status=403)
    operation = str(proposal.get("operation") or "").strip()
    if operation not in {"add", "comment", "remove", "replace"}:
        raise RequestRejected("proposal operation is not supported")
    pointer = str(proposal.get("pointer") or "").strip()
    if operation != "comment" and not pointer.startswith("/"):
        raise RequestRejected("proposal JSON pointer is required")
    target = _target_path(config, proposal.get("target_path"))
    target_hash = sha256_file(target)
    canonical = json.dumps(
        {
            "target": str(target), "target_sha256": target_hash,
            "operation": operation, "pointer": pointer,
            "value": proposal.get("value"), "reason": proposal.get("reason"),
        },
        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    )
    proposal_id = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:24]
    result = {
        "schema_version": 1,
        "proposal_id": proposal_id,
        "status": "pending",
        "target_path": str(target),
        "target_sha256": target_hash,
        "operation": operation,
        "pointer": pointer,
        "value": proposal.get("value"),
        "reason": str(proposal.get("reason") or "").strip() or None,
        "applied": False,
    }
    config.proposal_dir.mkdir(parents=True, exist_ok=True)
    write_json(config.proposal_dir / f"{proposal_id}.json", result)
    return result


def _json_response(handler: BaseHTTPRequestHandler, status: int, value: Any) -> None:
    body = json.dumps(value, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Cache-Control", "no-store")
    handler.send_header("X-Content-Type-Options", "nosniff")
    handler.end_headers()
    handler.wfile.write(body)


def create_review_server(
    config: ReviewServerConfig, *, host: str = "127.0.0.1", port: int = 0,
) -> ThreadingHTTPServer:
    """Create, but do not start, a loopback-only review HTTP server."""
    validate_bind_host(host)

    class Handler(BaseHTTPRequestHandler):
        server_version = "DirectorReview/1"

        def _run(self) -> None:
            try:
                size_text = self.headers.get("Content-Length", "0")
                try:
                    size = int(size_text)
                except ValueError as error:
                    raise RequestRejected("Content-Length is invalid", status=411) from error
                if size < 0 or size > config.max_body_bytes:
                    raise RequestRejected("request body exceeds the configured limit", status=413)
                body = self.rfile.read(size) if size else b""
                validate_request(
                    config, method=self.command, path=self.path,
                    headers=self.headers, body=body,
                )
                if self.command == "POST":
                    try:
                        payload = json.loads(body.decode("utf-8"))
                    except (UnicodeDecodeError, json.JSONDecodeError) as error:
                        raise RequestRejected("proposal body must be valid UTF-8 JSON") from error
                    result = (
                        propose_event_action(config, payload)
                        if isinstance(payload, dict) and "action" in payload
                        else propose_pending_change(config, payload)
                    )
                    _json_response(self, 201, result)
                else:
                    artifacts = [
                        {"path": str(path.relative_to(config.root)), "sha256": sha256_file(path)}
                        for path in sorted(config.root.rglob("*.json"))
                        if path.is_file() and not path.is_relative_to(config.proposal_dir)
                    ]
                    _json_response(self, 200, {"schema_version": 1, "artifacts": artifacts})
            except RequestRejected as error:
                _json_response(self, error.status, {"error": str(error)})

        do_GET = _run
        do_POST = _run

        def log_message(self, format: str, *args: Any) -> None:
            return

    return ThreadingHTTPServer((host, port), Handler)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True)
    parser.add_argument("--proposal-dir", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--max-body-bytes", type=int, default=64 * 1024)
    args = parser.parse_args()
    token = os.environ.get("DIRECTOR_REVIEW_TOKEN", "")
    csrf = os.environ.get("DIRECTOR_REVIEW_CSRF_TOKEN", "")
    config = ReviewServerConfig(
        root=Path(args.root), proposal_dir=Path(args.proposal_dir),
        auth_token=token, csrf_token=csrf, max_body_bytes=args.max_body_bytes,
    )
    server = create_review_server(config, host=args.host, port=args.port)
    print(f"http://{args.host}:{server.server_port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
