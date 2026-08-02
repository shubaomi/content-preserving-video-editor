from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from event_cache import (  # noqa: E402
    EventCache,
    EventCacheError,
    build_event_key,
    plan_event_rebuild,
)


def fingerprint(event_id: str, *, anchor: str = "概念", asset: str = "asset-a") -> dict:
    return {
        "event_id": event_id,
        "owner_artifact_sha256": "1" * 64,
        "renderer": "hyperframes",
        "renderer_version": "0.1.2",
        "event_payload": {"anchor": anchor},
        "captions_sha256": "2" * 64,
        "safe_zones_sha256": "3" * 64,
        "design_tokens_sha256": "4" * 64,
        "provider_evidence_sha256": "5" * 64,
        "rights_evidence_sha256": "6" * 64,
        "asset_hashes": [asset],
        "implementation_sha256": "7" * 64,
    }


class EventCacheTests(unittest.TestCase):
    def test_event_key_requires_all_safety_and_provenance_inputs(self) -> None:
        value = fingerprint("event-a")
        first = build_event_key(value)
        self.assertEqual(first, build_event_key(dict(reversed(list(value.items())))))
        for required in (
            "captions_sha256", "safe_zones_sha256", "design_tokens_sha256",
            "provider_evidence_sha256", "rights_evidence_sha256",
        ):
            broken = dict(value)
            broken.pop(required)
            with self.subTest(required=required), self.assertRaises(EventCacheError):
                build_event_key(broken)

    def test_single_event_change_rebuilds_only_that_event_and_dependents(self) -> None:
        previous = {
            "a": fingerprint("a"),
            "b": fingerprint("b"),
            "chapter": fingerprint("chapter"),
        }
        current = dict(previous)
        current["a"] = fingerprint("a", anchor="改变后的概念")
        plan = plan_event_rebuild(
            previous,
            current,
            [
                {"id": "a"}, {"id": "b"},
                {"id": "chapter", "depends_on": ["a", "b"]},
            ],
        )
        self.assertEqual(plan["rebuild"], ["a", "chapter"])
        self.assertEqual(plan["reuse"], ["b"])
        self.assertEqual(plan["removed"], [])

    def test_partial_or_corrupt_entry_is_never_reused(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache = EventCache(Path(temporary))
            key = build_event_key(fingerprint("a"))
            partial = Path(temporary) / f"{key}.partial-abandoned"
            partial.mkdir()
            (partial / "manifest.json").write_text("{}", encoding="utf-8")
            self.assertIsNone(cache.lookup(key))

            source = Path(temporary) / "render.mov"
            source.write_bytes(b"render")
            cache.store(key, {"render.mov": source})
            entry = cache.lookup(key)
            self.assertIsNotNone(entry)
            assert entry is not None
            Path(entry["outputs"][0]["cache_path"]).write_bytes(b"tampered")
            self.assertIsNone(cache.lookup(key))

    def test_concurrent_store_converges_on_one_valid_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "render.mov"
            source.write_bytes(b"same-render")
            cache = EventCache(root / "cache")
            key = build_event_key(fingerprint("a"))
            with ThreadPoolExecutor(max_workers=2) as executor:
                manifests = list(executor.map(
                    lambda _: cache.store(key, {"render.mov": source}),
                    range(2),
                ))
            self.assertEqual(
                {json.dumps(item, sort_keys=True) for item in manifests}.__len__(),
                1,
            )
            self.assertIsNotNone(cache.lookup(key))

    def test_abandoned_lock_is_reclaimed_without_permanent_cache_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = EventCache(root / "cache", lock_timeout_seconds=0.2, stale_lock_seconds=0.01)
            key = build_event_key(fingerprint("a"))
            lock = cache.root / f"{key}.lock"
            lock.write_text(json.dumps({
                "schema_version": 1, "pid": 999999,
                "created_at": time.time() - 10, "token": "abandoned",
            }), encoding="utf-8")
            source = root / "render.mov"
            source.write_bytes(b"recovered")
            stored = cache.store(key, {"render.mov": source})
            self.assertEqual(stored["event_key"], key)
            self.assertFalse(lock.exists())

    def test_live_lock_is_not_reclaimed_merely_because_lease_age_elapsed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            owner = EventCache(root / "cache", lock_timeout_seconds=0.05,
                               stale_lock_seconds=0.001)
            key = build_event_key(fingerprint("a"))
            lock, _token = owner._acquire_lock(key)
            time.sleep(0.01)
            contender = EventCache(root / "cache", lock_timeout_seconds=0.05,
                                   stale_lock_seconds=0.001)
            with self.assertRaisesRegex(EventCacheError, "timed out"):
                contender._acquire_lock(key)
            lock.unlink(missing_ok=True)

    def test_cross_process_liveness_probe_does_not_terminate_process(self) -> None:
        from event_cache import _pid_is_alive

        process = subprocess.Popen(
            [sys.executable, "-c", "import time; time.sleep(30)"],
        )
        try:
            self.assertTrue(_pid_is_alive(process.pid))
            self.assertIsNone(process.poll())
        finally:
            process.terminate()
            process.wait(timeout=5)
        self.assertFalse(_pid_is_alive(process.pid))

    def test_reused_pid_with_different_start_identity_is_not_treated_as_owner(self) -> None:
        from event_cache import _lock_owner_is_current

        record = {"pid": 1234, "process_identity": "old-start"}
        with patch("event_cache._pid_is_alive", return_value=True), \
                patch("event_cache._process_identity", return_value="new-start"):
            self.assertFalse(_lock_owner_is_current(record))


if __name__ == "__main__":
    unittest.main()
