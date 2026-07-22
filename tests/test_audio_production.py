from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from audio_production import build_audio_plan, resolve_bgm  # noqa: E402
from director_adapters import AdapterRunner  # noqa: E402


class AudioProductionTests(unittest.TestCase):
    def test_approved_local_asset_wins_without_spending_provider_quota(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            bgm = root / "approved.wav"
            bgm.write_bytes(b"music")
            runner = AdapterRunner(root / "state.json")
            result = resolve_bgm({
                "enabled_by_default": True,
                "asset": str(bgm),
                "authorization": "creator-owned",
                "provider_chain": [{"name": "minimax", "enabled": True,
                                    "command": [sys.executable, "missing.py"]}],
            }, root=root, output_dir=root / "audio", runner=runner)
            self.assertEqual(result["mode"], "authorized_asset")
            self.assertEqual(result["provider"], "approved_local")
            self.assertFalse((root / "state.json").exists())

    def test_provider_chain_stops_after_first_success(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            first = root / "audio" / "first.wav"
            second = root / "audio" / "second.wav"
            create_first = (
                "from pathlib import Path; p=Path(r'%s'); p.parent.mkdir(parents=True,exist_ok=True); "
                "p.write_bytes(b'first')" % first
            )
            create_second = (
                "from pathlib import Path; p=Path(r'%s'); p.parent.mkdir(parents=True,exist_ok=True); "
                "p.write_bytes(b'second')" % second
            )
            result = resolve_bgm({
                "enabled_by_default": True,
                "provider_chain": [
                    {"name": "heygen", "enabled": True,
                     "command": [sys.executable, "-c", create_first], "output": str(first),
                     "authorization": "test"},
                    {"name": "minimax", "enabled": True,
                     "command": [sys.executable, "-c", create_second], "output": str(second),
                     "authorization": "test"},
                ],
            }, root=root, output_dir=root / "audio", runner=AdapterRunner(root / "state.json"))
            self.assertEqual(result["provider"], "heygen")
            self.assertTrue(first.is_file())
            self.assertFalse(second.exists())

    def test_audio_plan_preserves_silent_decisions_and_records_pending_mix_measurement(self) -> None:
        manifest = {"event_decisions": [
            {"event_id": "e1", "decision": "cue", "asset": "assets/e1.wav"},
            {"event_id": "e2", "decision": "intentionally_silent", "reason": "source UI click is audible"},
        ]}
        plan = build_audio_plan(
            manifest, source_audio="source.mp4",
            bgm={"mode": "disabled", "reason": "no approved asset"}, preview_volume=0.1,
        )
        self.assertEqual(plan["motion_sfx"]["event_decisions"][1]["decision"],
                         "intentionally_silent")
        self.assertEqual(plan["motion_sfx"]["mix_audibility_check"]["status"],
                         "pending_render_measurement")
        self.assertEqual(plan["background_music"]["mode"], "disabled")


if __name__ == "__main__":
    unittest.main()
