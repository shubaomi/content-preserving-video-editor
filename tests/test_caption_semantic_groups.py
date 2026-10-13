import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import caption_semantic_groups as grouping
import video_use_bridge as bridge
from director_contracts import sha256_file, write_json


class SemanticGroupsTests(unittest.TestCase):
    def setUp(self):
        text = ["的", "工艺", "制作", "的", "轻轻", "一放"]
        self.words = [dict(text=t, start=i * .2, end=(i + 1) * .2,
                           source="cam", source_word_id=f"w{i}",
                           source_start=i * .2, source_end=(i + 1) * .2,
                           segment_id="body", word_occurrence_id=f"body:w{i}")
                      for i, t in enumerate(text)]
        self.bindings = dict(edl="a" * 64, transcripts={"cam": "b" * 64}, corrections=None)
        self.manifest = dict(schema_version=1, kind="semantic_caption_groups", owner="video-use",
                             input_hashes=self.bindings,
                             mapped_words_sha256=grouping.words_hash(self.words), groups=[
            dict(id="c1", semantic_group_id="magnet", word_occurrence_ids=[f"body:w{i}" for i in range(4)], rationale="前句修饰语"),
            dict(id="c2", semantic_group_id="action", word_occurrence_ids=["body:w4", "body:w5"], rationale="新动作句")])

    def compile(self, **kwargs):
        return grouping.build_grouped_captions(self.words, self.manifest,
            raw_words=self.words, input_hashes=self.bindings, max_chars=14,
            max_duration=4.2, punctuation_style="spoken_clean", **kwargs)

    def test_semantic_boundary_and_exact_timestamps(self):
        before = copy.deepcopy(self.words)
        rows = self.compile()
        self.assertEqual([r["text"] for r in rows], ["的工艺制作的", "轻轻一放"])
        self.assertEqual([(r["start"], r["end"]) for r in rows], [(0, .8), (.8, 1.2)])
        self.assertEqual(self.words, before)

    def test_stale_missing_duplicate_reordered_and_unknown_rejected(self):
        mutations = [lambda d: d.update(mapped_words_sha256="0" * 64),
            lambda d: d["groups"][0]["word_occurrence_ids"].pop(),
            lambda d: d["groups"][1]["word_occurrence_ids"].append("body:w4"),
            lambda d: d["groups"].reverse(), lambda d: d["groups"][0].update(text="rewrite")]
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                original = copy.deepcopy(self.manifest)
                mutate(self.manifest)
                with self.assertRaises(ValueError):
                    self.compile()
                self.manifest = original

    def test_hard_limits_not_legacy_soft_overflow(self):
        self.words[0]["text"] = "这是一个非常非常长的不能压缩字号来容忍的句子"
        self.manifest["mapped_words_sha256"] = grouping.words_hash(self.words)
        with self.assertRaisesRegex(ValueError, "max_chars"):
            self.compile()

    def test_cross_segment_rejected(self):
        self.words[1]["segment_id"] = "other"
        self.manifest["mapped_words_sha256"] = grouping.words_hash(self.words)
        with self.assertRaisesRegex(ValueError, "segment"):
            self.compile()

    def test_duration_and_nonconsecutive_semantic_groups_rejected(self):
        self.words[-1]["end"] = 9
        self.manifest["mapped_words_sha256"] = grouping.words_hash(self.words)
        with self.assertRaisesRegex(ValueError, "max_duration"):
            self.compile()
        self.setUp()
        self.manifest["groups"] = [dict(id=f"c{i}", semantic_group_id=s,
            word_occurrence_ids=[f"body:w{i}"], rationale="fixture")
            for i, s in enumerate(["a", "b", "a", "a", "c", "c"])]
        with self.assertRaisesRegex(ValueError, "consecutive"):
            self.compile()

    def test_span_correction_keeps_original_span_not_character_interpolation(self):
        doc = dict(schema_version=2, kind="word_span_corrections", owner="video-use",
                   input_hashes={k: v for k, v in self.bindings.items() if k != "corrections"},
                   replacements=[dict(word_occurrence_ids=["body:w4", "body:w5"],
                                      **{"from": "轻轻一放", "to": "Excel", "evidence": "fixture user correction"})])
        words, changes = grouping.apply_span_corrections(self.words, doc, self.bindings)
        self.assertEqual(len(words), 5)
        self.assertEqual(words[-1]["text"], "Excel")
        self.assertAlmostEqual(words[-1]["start"], .8)
        self.assertAlmostEqual(words[-1]["end"], 1.2)
        self.assertEqual(words[-1]["word_occurrence_ids"], ["body:w4", "body:w5"])
        self.assertEqual(words[:4], self.words[:4])
        rows = grouping.build_grouped_captions(words, self.manifest, raw_words=self.words,
            input_hashes=self.bindings, max_chars=14, max_duration=4.2)
        self.assertEqual(rows[-1]["text"], "Excel")
        self.assertEqual(len(changes), 1)


class CaptionBridgeIntegrationTests(unittest.TestCase):
    def test_cli_semantic_groups_and_stale_binding_fail_closed(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            transcript, edl, groups = (root / n for n in ("words.json", "edl.json", "groups.json"))
            write_json(transcript, {"words": [dict(id="a", text="工艺制作的", type="word", start=0, end=1),
                                                dict(id="b", text="轻轻一放", type="word", start=1, end=2)]})
            write_json(edl, {"ranges": [dict(source="cam", start=0, end=2)]})
            helper = SimpleNamespace(_words_in_range=lambda t, start, end: t["words"])
            with patch.object(bridge, "_load_video_use_render", return_value=helper):
                mapped = bridge.map_words_to_output(json.loads(edl.read_text(encoding="utf-8")),
                                                    {"cam": json.loads(transcript.read_text(encoding="utf-8"))})
                manifest = dict(schema_version=1, kind="semantic_caption_groups", owner="video-use",
                    input_hashes=dict(edl=sha256_file(edl), transcripts={"cam": sha256_file(transcript)}, corrections=None),
                    mapped_words_sha256=grouping.words_hash(mapped), groups=[
                        dict(id=f"c{i}", semantic_group_id=f"s{i}", rationale="phrase boundary",
                             word_occurrence_ids=grouping.token_ids(w)) for i, w in enumerate(mapped)])
                write_json(groups, manifest)
                args = ["bridge", "--edl", str(edl), "--transcript", f"cam={transcript}",
                        "--out-dir", str(root / "out"), "--semantic-groups", str(groups)]
                with patch.object(sys, "argv", args):
                    self.assertEqual(bridge.main(), 0)
                captions = json.loads((root / "out/captions.json").read_text(encoding="utf-8"))["segments"]
                self.assertEqual([c["text"] for c in captions], ["工艺制作的", "轻轻一放"])
                before = (root / "out/master.srt").read_bytes()
                manifest["input_hashes"]["edl"] = "0" * 64
                write_json(groups, manifest)
                with patch.object(sys, "argv", args), self.assertRaisesRegex(ValueError, "hashes"):
                    bridge.main()
                self.assertEqual((root / "out/master.srt").read_bytes(), before)

    def test_director_add_change_remove_sidecar_invalidates_from_timeline(self):
        from director import Director
        import yaml
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            source.write_bytes(b"test fixture not real media")
            project = root / "project.yaml"
            project.write_text(yaml.safe_dump(dict(version=1, video_id="fixture", paths={"root": str(root)},
                source={"primary_video": str(source), "input_mode": "existing_edit_polish"})), encoding="utf-8")
            director = Director(project)
            grouping_path = director.video_use_dir / "caption-semantic-groups.json"
            correction_path = director.context.edit_dir / "transcripts/caption-corrections-v2.json"
            plan = director.video_use_dir / "execution-plan.json"
            def complete():
                write_json(plan, {"caption_owner_inputs": {str(p.resolve()): sha256_file(p) if p.is_file() else None
                                                          for p in (grouping_path, correction_path)}})
                director._complete("inspect", [source])
                director._complete("video_use_timeline", [plan])
            complete()
            self.assertFalse(director._caption_owner_inputs_changed())
            for action in (lambda: write_json(grouping_path, {"test": 1}),
                           lambda: write_json(grouping_path, {"test": 2}),
                           lambda: grouping_path.unlink()):
                action()
                director = Director(project)
                self.assertEqual(director.state["stages"]["video_use_timeline"]["status"], "pending")
                self.assertEqual(director.state["stages"]["inspect"]["status"], "complete")
                complete()


if __name__ == "__main__":
    unittest.main()
