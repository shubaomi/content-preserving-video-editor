from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director_contracts import (  # noqa: E402
    VISUAL_VOCABULARY,
    detect_input_mode,
    validate_semantic_brief,
    validate_storyboard,
    validate_video_use_edl,
    validate_video_use_edit_preflight,
    validate_video_use_final_correctness,
    validate_video_use_media_analysis,
    validate_visual_vocabulary_audit,
)


def event(identifier: str, anchor: str, start: float, archetype: str) -> dict:
    return {
        "id": identifier,
        "start": start,
        "anchor": anchor,
        "transcript_quote": f"这里真正讲的是{anchor}的作用",
        "transcript_word_ids": [identifier + "-w1"],
        "relevance_rationale": "把抽象关系转成可见结构",
        "visual_structure": {
            "dom_structure": archetype + "-dom",
            "information_hierarchy": archetype + "-hierarchy",
            "layout_archetype": archetype,
            "animation_choreography": archetype + "-motion",
            "use_case": archetype + "-case",
        },
    }


def valid_brief() -> dict:
    return {
        "schema_version": 1,
        "generated_by": "agent-llm",
        "content_reading": "raw_word_transcript_and_evidence_frames",
        "transcript_sha256": "a" * 64,
        "evidence_frames": ["frame-001.png"],
        "events": [
            event("e1", "知识关系图", 10, "process-path"),
            event("e2", "免费版与高级版", 30, "comparison-split"),
            event("e3", "三步生成流程", 55, "step-rail"),
            event("e4", "五个核心模块", 75, "numeric-result"),
        ],
    }


class DirectorContractTests(unittest.TestCase):
    def test_semantic_brief_requires_four_real_structures(self) -> None:
        self.assertEqual(validate_semantic_brief(valid_brief(), require_sample_variety=True), [])

    def test_low_information_anchor_is_blocking(self) -> None:
        brief = valid_brief()
        brief["events"][0]["anchor"] = "打开"
        errors = validate_semantic_brief(brief, require_sample_variety=True)
        self.assertTrue(any("low-information" in error for error in errors))

    def test_duplicate_structure_is_not_variety(self) -> None:
        brief = valid_brief()
        brief["events"][1]["visual_structure"] = dict(brief["events"][0]["visual_structure"])
        errors = validate_semantic_brief(brief, require_sample_variety=True)
        self.assertTrue(any("duplicates a previous visual structure" in error for error in errors))

    def test_storyboard_must_render_with_hyperframes(self) -> None:
        brief = valid_brief()
        storyboard = {
            "renderer": "ffmpeg",
            "motion_output": "preview_only",
            "capability_skills": [],
            "events": brief["events"],
        }
        errors = validate_storyboard(storyboard, brief)
        self.assertTrue(any("renderer must be hyperframes" in error for error in errors))
        self.assertTrue(any("motion_output must be hyperframes_render" in error for error in errors))

    def test_existing_edit_is_detected_without_changing_preservation_policy(self) -> None:
        project = {"source": {"input_mode": "existing_edit_polish"}}
        self.assertEqual(detect_input_mode(project, Path("source.mp4")), "polish_existing")

    def test_undeclared_mode_requires_analysis_instead_of_guessing_preserve(self) -> None:
        self.assertEqual(detect_input_mode({}, Path("recording.mp4")), "needs_analysis")
        self.assertEqual(
            detect_input_mode({}, Path("recording.mp4"), {"selected_mode": "polish_existing"}),
            "polish_existing",
        )
        self.assertEqual(
            detect_input_mode({"source": {"input_mode": "raw"}}, Path("recording.mp4")),
            "preserve",
        )

    def test_visual_vocabulary_requires_an_explicit_decision_for_all_ten_categories(self) -> None:
        brief = valid_brief()
        storyboard = {
            "renderer": "hyperframes",
            "motion_output": "hyperframes_render",
            "capability_skills": ["hyperframes", "hyperframes-core", "hyperframes-creative",
                                  "hyperframes-animation", "hyperframes-cli"],
            "events": brief["events"],
        }
        selected = {
            name: {"status": "selected", "event_ids": [brief["events"][index]["id"]],
                   "evidence": [f"frame-{index}.png"]}
            for index, name in enumerate(VISUAL_VOCABULARY[:4])
        }
        rejected = {
            name: {"status": "not_applicable", "rationale": "not supported by this sample's speech",
                   "evidence": ["transcript.json"]}
            for name in VISUAL_VOCABULARY[4:]
        }
        audit = {"categories": {**selected, **rejected}}
        self.assertEqual(validate_visual_vocabulary_audit(audit, storyboard), [])
        del audit["categories"]["ip_asset"]
        self.assertTrue(any("ip_asset" in error for error in validate_visual_vocabulary_audit(audit, storyboard)))

    def test_full_visual_vocabulary_requires_per_chapter_decisions(self) -> None:
        brief = valid_brief()
        storyboard = {"events": brief["events"]}
        audit = {"categories": {
            name: ({"status": "selected", "event_ids": [brief["events"][index % 4]["id"]],
                    "evidence": ["frame.png"]}
                   if index < 4 else
                   {"status": "not_applicable", "rationale": "not in transcript", "evidence": ["words.json"]})
            for index, name in enumerate(VISUAL_VOCABULARY)
        }}
        errors = validate_visual_vocabulary_audit(audit, storyboard, full_video=True)
        self.assertTrue(any("chapter_decisions" in error for error in errors))

    def test_four_category_labels_cannot_all_claim_one_structure(self) -> None:
        brief = valid_brief()
        storyboard = {"events": brief["events"]}
        audit = {"categories": {
            name: ({"status": "selected", "event_ids": ["e1"], "evidence": ["frame.png"]}
                   if index < 4 else
                   {"status": "not_applicable", "rationale": "not present", "evidence": ["words.json"]})
            for index, name in enumerate(VISUAL_VOCABULARY)
        }}
        errors = validate_visual_vocabulary_audit(audit, storyboard)
        self.assertTrue(any("four distinct storyboard events" in error for error in errors))

    def test_video_use_edl_owns_cut_policy_and_preserves_existing_timeline(self) -> None:
        edl = {
            "owner": "video-use",
            "sources": {"source": "source.mp4"},
            "ranges": [{"source": "source", "start": 0, "end": 100}],
            "cut_policy": {"word_boundary_padding_ms": [30, 100], "audio_fade_ms": 30},
        }
        self.assertEqual(validate_video_use_edl(
            edl, source_name="source", source_duration=100, input_mode="polish_existing"
        ), [])
        edl["owner"] = "director"
        edl["ranges"][0]["end"] = 80
        errors = validate_video_use_edl(
            edl, source_name="source", source_duration=100, input_mode="polish_existing"
        )
        self.assertTrue(any("owner must be video-use" in error for error in errors))
        self.assertTrue(any("source tail" in error for error in errors))
        self.assertTrue(any("established timeline" in error for error in errors))

    def test_video_use_media_and_edit_preflight_require_real_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.mp4"
            source.write_bytes(b"source")
            views = []
            for index in range(3):
                view = root / f"view-{index}.png"
                view.write_bytes(b"png")
                views.append(str(view))
            media = {
                "owner": "video-use",
                "source_sha256": hashlib.sha256(b"source").hexdigest(),
                "duration_seconds": 100,
                "video_stream": {"width": 1920, "height": 1080},
                "audio_stream": {"codec": "aac"},
                "timeline_views": views,
            }
            self.assertEqual(validate_video_use_media_analysis(
                media, source_path=source, source_duration=100
            ), [])
            transcript = root / "transcript.json"
            transcript.write_text("{}", encoding="utf-8")
            edl_path = root / "edl.json"
            edl = {"ranges": [{"start": 0, "end": 100}]}
            edl_path.write_text(json.dumps(edl), encoding="utf-8")
            preflight = {
                "owner": "video-use", "status": "pass", "boundary_count": 0,
                "boundaries": [], "identity_timeline": True, "tail_covered": True,
                "expected_output_duration": 100,
                "edl_sha256": hashlib.sha256(edl_path.read_bytes()).hexdigest(),
                "transcript_sha256": hashlib.sha256(transcript.read_bytes()).hexdigest(),
            }
            self.assertEqual(validate_video_use_edit_preflight(
                preflight, edl_path=edl_path, transcript_path=transcript, edl=edl
            ), [])
            preflight["identity_timeline"] = False
            self.assertTrue(any("identity_timeline" in error for error in validate_video_use_edit_preflight(
                preflight, edl_path=edl_path, transcript_path=transcript, edl=edl
            )))

    def test_final_video_use_correctness_binds_universal_output_and_overview_views(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            output = root / "universal.mp4"
            output.write_bytes(b"final")
            views = []
            for name in ("first", "middle", "last"):
                view = root / f"{name}.png"
                view.write_bytes(b"png")
                views.append(str(view))
            edl = {"ranges": [{"start": 0, "end": 100}]}
            report = {
                "owner": "video-use", "status": "pass",
                "output_sha256": hashlib.sha256(b"final").hexdigest(),
                "expected_output_duration": 100,
                "actual_output_duration": 100.1,
                "boundary_reviews": [],
                "overview_timeline_views": views,
            }
            self.assertEqual(validate_video_use_final_correctness(
                report, output_path=output, edl=edl
            ), [])
            report["output_sha256"] = "0" * 64
            self.assertTrue(any("output hash" in error for error in validate_video_use_final_correctness(
                report, output_path=output, edl=edl
            )))


if __name__ == "__main__":
    unittest.main()
