"""Projection captions retain source-word instances without owning EDL approval."""
import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import editorial_projection as ep
import video_use_bridge as bridge
from director_contracts import sha256_file


class EditorialCaptionBridgeTests(unittest.TestCase):
    def setUp(self):
        self.edl = {"source": "cam", "segments": [
            {"segment_id": "one", "start": 0, "end": 2},
            {"segment_id": "two", "start": 0, "end": 2},
        ]}
        self.words = {"words": [{"id": 7, "text": "真实", "start": 0, "end": 1},
                                {"id": "tail", "text": "动作", "start": 1, "end": 2}]}
        self.hashes = {name: "a" * 64 for name in ("source", "transcript", "base_edl", "candidate_edl")}

    def projection(self):
        return ep.build_projection(baseline_edl=self.edl, candidate_edl=self.edl,
                                   transcript=self.words, fps=30, input_hashes=self.hashes)

    def test_repeated_words_zero_gap_never_merge_occurrences(self):
        mapped = bridge.map_projection_words(self.projection(), self.edl, {"cam": self.words})
        self.assertEqual([w["source_word_id"] for w in mapped], [7, "tail", 7, "tail"])
        captions = bridge.build_captions(mapped)
        self.assertEqual(len(captions), 2)
        self.assertEqual([c["segment_id"] for c in captions], ["one", "two"])
        self.assertEqual(captions[0]["word_occurrence_ids"], ["one:7", "one:tail"])
        self.assertEqual(captions[1]["source_word_ids"], [7, "tail"])

    def test_gap_is_preserved(self):
        self.edl["segments"][1]["timeline_start"] = 5
        mapped = bridge.map_projection_words(self.projection(), self.edl, {"cam": self.words})
        self.assertEqual(mapped[2]["start"], 5)

    def test_hook_body_instances_remain_separate_without_pause(self):
        base = {"source": "cam", "segments": [dict(self.edl["segments"][0])]}
        candidate = copy.deepcopy(base)
        candidate["segments"][0].update(segment_id="body", timeline_start=2)
        candidate["segments"].insert(0, {"source": "cam", "segment_id": "hook", "role": "hook", "start": 0, "end": 2})
        hashes = dict(self.hashes, hook_plan="b" * 64)
        hook = {"state": "proposed", "candidates": [{"id": "h", "source_ref": "cam",
            "source_range": {"start": 0, "end": 2}, "word_ids": [7, "tail"], "quote": "真实动作",
            "context_before": "测试前文", "context_after": "测试后文", "promise": "真实动作",
            "frame_refs": ["fixture"], "payoff_semantic_ids": ["fixture"]}]}
        approval = {"kind": "hook_excerpt", "scope": "short_preview", "candidate_id": "h",
            "original_user_message": "synthetic fixture only", "operator": "fixture", "timestamp": "fixture",
            "input_hashes": {k: v for k, v in hashes.items() if k != "candidate_edl"}}
        projection = ep.build_projection(baseline_edl=base, candidate_edl=candidate, transcript=self.words,
            fps=30, mode="approved_duplicate", input_hashes=hashes, hook_plan=hook, approval=approval, authority=lambda *_: True)
        captions = bridge.build_captions(bridge.map_projection_words(projection, candidate, {"cam": self.words}))
        self.assertEqual([c["word_occurrence_ids"] for c in captions], [["hook:7", "hook:tail"], ["body:7", "body:tail"]])

    def test_forged_projection_words_or_actual_edl_rejected(self):
        for change in (lambda p: p["words"][0].update(text="伪造"), lambda p: p["words"].pop(),
                       lambda p: p["words"][0].update(source_start=.2, output_start=.2)):
            p = self.projection(); change(p)
            with self.assertRaises(ValueError): bridge.map_projection_words(p, self.edl, {"cam": self.words})
        for change in (lambda e: e["segments"][0].update(speed=2),
                       lambda e: e["segments"][0].update(start=.5),
                       lambda e: e["segments"][1].update(timeline_start=3)):
            edl = copy.deepcopy(self.edl); change(edl)
            with self.assertRaises(ValueError): bridge.map_projection_words(self.projection(), edl, {"cam": self.words})

    def test_projection_corrections_keep_complete_instance_ids(self):
        mapped = bridge.map_projection_words(self.projection(), self.edl, {"cam": self.words})
        corrected, applied = bridge.apply_audited_corrections(mapped, {"replacements": [
            {"from": "真实动作", "to": "真实操作", "evidence": "synthetic approved correction"}]})
        captions = bridge.build_captions(corrected)
        self.assertEqual(len(applied), 2)
        self.assertEqual(captions[0]["word_occurrence_ids"], ["one:7", "one:tail"])
        self.assertEqual(captions[1]["word_occurrence_ids"], ["two:7", "two:tail"])

    def test_correction_cannot_match_across_segment_boundary(self):
        mapped = bridge.map_projection_words(self.projection(), self.edl, {"cam": self.words})
        corrected, applied = bridge.apply_audited_corrections(mapped, {"replacements": [
            {"from": "动作真实", "to": "错误跨段", "evidence": "fixture"}]})
        self.assertEqual(corrected, mapped)
        self.assertEqual(applied, [])

    def test_half_word_rejected_even_when_projection_matches_forged_edl(self):
        self.edl["segments"] = [self.edl["segments"][0]]
        projection = self.projection()
        self.edl["segments"][0]["start"] = .5
        projection["segments"][0].update(source_range={"start": .5, "end": 2},
            output_end=1.5, output_end_frame=45)
        projection.update(output_duration=1.5, summary={"mode": "preserve_order", "output_duration": 1.5})
        projection["words"][0].update(source_start=.5, output_end=.5)
        projection["words"][1].update(output_start=.5, output_end=1.5)
        ep.validate_projection(projection)
        with self.assertRaisesRegex(ValueError, "cuts a source word"):
            bridge.map_projection_words(projection, self.edl, {"cam": self.words})

    def test_strict_projection_input_rejects_duplicate_keys_and_nan(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "input.json"
            for data in ('{"words": [], "words": []}', '{"value": NaN}'):
                path.write_text(data, encoding="utf-8")
                with self.assertRaises(ValueError): bridge._read_projection_input(path)

    def test_legacy_grouping_unchanged(self):
        words = [{"text": "真实", "start": 0, "end": 1}, {"text": "动作", "start": 1, "end": 2}]
        self.assertEqual(bridge.build_captions(words), [{"start": 0.0, "end": 2.0, "text": "真实动作",
            "timeline": "output", "alignment": "word_timestamp", "mapping_owner": "video-use",
            "source_word_start": 0, "source_word_end": 1}])

    def test_cli_checks_current_hashes_before_writing(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            for name, value in (("edl", self.edl), ("words", self.words)):
                (root / f"{name}.json").write_text(json.dumps(value), encoding="utf-8")
            self.hashes.update(candidate_edl=sha256_file(root / "edl.json"), transcript=sha256_file(root / "words.json"))
            projection = self.projection()
            (root / "projection.json").write_text(json.dumps(projection), encoding="utf-8")
            command = [sys.executable, str(ROOT / "scripts/video_use_bridge.py"), "--edl", str(root / "edl.json"),
                "--transcript", "cam=" + str(root / "words.json"), "--projection", str(root / "projection.json"), "--out-dir", str(root / "out")]
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            projection["input_hashes"]["candidate_edl"] = "0" * 64
            (root / "projection.json").write_text(json.dumps(projection), encoding="utf-8")
            command[-1] = str(root / "bad")
            result = subprocess.run(command, capture_output=True, text=True)
            self.assertNotEqual(result.returncode, 0)
            self.assertFalse((root / "bad").exists())


if __name__ == "__main__":
    unittest.main()
