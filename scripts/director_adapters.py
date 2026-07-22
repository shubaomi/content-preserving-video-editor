#!/usr/bin/env python3
"""Hash-bound execution and recovery for local Director capability adapters."""
from __future__ import annotations

import hashlib
import json
import subprocess
import tempfile
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator

from director_contracts import exclusive_file_lock


class AdapterExecutionError(RuntimeError):
    """Raised when a blocking adapter cannot produce its declared artifacts."""


@contextmanager
def _exclusive_lock(path: Path, timeout_seconds: float = 30.0) -> Iterator[None]:
    try:
        with exclusive_file_lock(path, timeout_seconds=timeout_seconds):
            yield
    except RuntimeError as error:
        raise AdapterExecutionError(str(error)) from error


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _file_record(path: Path) -> dict[str, Any]:
    resolved = path.resolve()
    return {
        "path": str(resolved),
        "available": resolved.is_file(),
        "sha256": _sha256(resolved) if resolved.is_file() else None,
    }


class AdapterRunner:
    def __init__(self, state_path: Path) -> None:
        self.state_path = state_path.resolve()
        self.state = self._load()

    def _load(self) -> dict[str, Any]:
        if not self.state_path.is_file():
            return {"schema_version": 1, "adapters": {}}
        try:
            state = json.loads(self.state_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as error:
            raise AdapterExecutionError(f"adapter state is unreadable: {error}") from error
        if not isinstance(state, dict) or state.get("schema_version") != 1 or not isinstance(state.get("adapters"), dict):
            raise AdapterExecutionError("adapter state has an unsupported schema")
        return state

    def _save(self) -> None:
        self.state_path.parent.mkdir(parents=True, exist_ok=True)
        with _exclusive_lock(self.state_path, timeout_seconds=10.0):
            disk = {"schema_version": 1, "adapters": {}}
            if self.state_path.is_file():
                candidate = json.loads(self.state_path.read_text(encoding="utf-8"))
                if not isinstance(candidate, dict) or not isinstance(candidate.get("adapters"), dict):
                    raise AdapterExecutionError("adapter state has an unsupported schema")
                disk = candidate
            disk["adapters"].update(self.state.get("adapters", {}))
            with tempfile.NamedTemporaryFile(
                mode="w", encoding="utf-8", delete=False,
                dir=self.state_path.parent, prefix=self.state_path.name + ".", suffix=".tmp",
            ) as handle:
                handle.write(json.dumps(disk, ensure_ascii=False, indent=2) + "\n")
                temporary = Path(handle.name)
            temporary.replace(self.state_path)
            self.state = disk

    def run(
        self,
        *,
        name: str,
        enabled: bool,
        command: list[str],
        inputs: list[Path],
        outputs: list[Path],
        blocking: bool,
        cwd: Path | None = None,
        settings: dict[str, Any] | None = None,
        environment_signature: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if not enabled:
            return {"name": name, "status": "disabled", "reason": "optional_default_off"}
        adapter_key = hashlib.sha256(name.encode("utf-8")).hexdigest()[:16]
        transaction_lock = self.state_path.with_suffix(
            self.state_path.suffix + f".{adapter_key}.adapter.lock"
        )
        with _exclusive_lock(transaction_lock):
            self.state = self._load()
            return self._run_locked(
                name=name, command=command, inputs=inputs, outputs=outputs,
                blocking=blocking, cwd=cwd, settings=settings,
                environment_signature=environment_signature,
            )

    def _run_locked(
        self,
        *,
        name: str,
        command: list[str],
        inputs: list[Path],
        outputs: list[Path],
        blocking: bool,
        cwd: Path | None,
        settings: dict[str, Any] | None,
        environment_signature: dict[str, Any] | None,
    ) -> dict[str, Any]:
        input_records = [_file_record(path) for path in inputs]
        missing_inputs = [row["path"] for row in input_records if not row["available"]]
        input_paths = {str(Path(row["path"]).resolve()) for row in input_records}
        output_paths = {str(path.resolve()) for path in outputs}
        implementation_paths: list[Path] = []
        base = (cwd or Path.cwd()).resolve()
        implementation_suffixes = {
            ".py", ".pyw", ".js", ".mjs", ".cjs", ".ts", ".tsx",
            ".ps1", ".sh", ".bat", ".cmd", ".exe",
        }
        for token in command[1:]:
            candidate = Path(token)
            candidate = candidate.resolve() if candidate.is_absolute() else (base / candidate).resolve()
            if (candidate.is_file() and candidate.suffix.lower() in implementation_suffixes
                    and str(candidate) not in input_paths
                    and str(candidate) not in output_paths):
                implementation_paths.append(candidate)
        implementation_records = [_file_record(path) for path in implementation_paths]
        signature = _stable_hash({
            "name": name,
            "command": command,
            "inputs": input_records,
            "implementation": implementation_records,
            "settings": settings or {},
            "environment": environment_signature or {},
        })
        previous = self.state["adapters"].get(name, {})
        current_outputs = [_file_record(path) for path in outputs]
        if (
            previous.get("status") == "complete"
            and previous.get("signature") == signature
            and previous.get("outputs") == current_outputs
            and all(row["available"] for row in current_outputs)
        ):
            return {**previous, "status": "reused"}
        if missing_inputs:
            reason = f"missing adapter inputs: {', '.join(missing_inputs)}"
            return self._record_failure(name, signature, input_records, current_outputs, reason, blocking)
        try:
            timeout = float((settings or {}).get("timeout_seconds", 3600))
            subprocess.run(command, cwd=cwd, check=True, timeout=timeout)
        except (OSError, subprocess.CalledProcessError, subprocess.TimeoutExpired) as error:
            return self._record_failure(
                name, signature, input_records, [_file_record(path) for path in outputs],
                f"adapter command failed: {error}", blocking,
            )
        output_records = [_file_record(path) for path in outputs]
        missing_outputs = [row["path"] for row in output_records if not row["available"]]
        if missing_outputs:
            reason = f"adapter did not create outputs: {', '.join(missing_outputs)}"
            return self._record_failure(name, signature, input_records, output_records, reason, blocking)
        row = {
            "name": name,
            "status": "complete",
            "signature": signature,
            "command": command,
            "inputs": input_records,
            "implementation": implementation_records,
            "outputs": output_records,
            "blocking": blocking,
        }
        self.state["adapters"][name] = row
        self._save()
        return row

    def _record_failure(
        self,
        name: str,
        signature: str,
        inputs: list[dict[str, Any]],
        outputs: list[dict[str, Any]],
        reason: str,
        blocking: bool,
    ) -> dict[str, Any]:
        row = {
            "name": name,
            "status": "failed" if blocking else "unavailable",
            "signature": signature,
            "inputs": inputs,
            "outputs": outputs,
            "blocking": blocking,
            "error": reason,
        }
        self.state["adapters"][name] = row
        self._save()
        if blocking:
            raise AdapterExecutionError(reason)
        return row
