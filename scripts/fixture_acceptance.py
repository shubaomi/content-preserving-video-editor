#!/usr/bin/env python3
"""Evaluate the six cross-video-type acceptance fixtures with shared gates."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from asr_router import choose_backend
from director_contracts import sha256_file, write_json

REPOSITORY_ROOT = Path(__file__).parents[1]


def _repository_id(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPOSITORY_ROOT.resolve()).as_posix()
    except ValueError:
        return resolved.name
from hyperframes_router import route_hyperframes


REQUIRED_TYPES = {
    "landscape_screen_tutorial",
    "portrait_talking_head",
    "published_edit_polish",
    "two_person_interview",
    "noisy_audio_hotwords",
    "screen_camera_mixed",
}
CHECK_NAMES = (
    "caption_timing_and_sentence_segmentation",
    "content_preservation",
    "semantic_relevance",
    "keyword_and_form_repetition",
    "geometry_occlusion_crop_whitespace",
    "sfx_audibility_and_repetition",
    "bgm_speech_loudness",
    "studio_render_parity",
    "manual_correction_cost",
    "hyperframes_route",
    "asr_route",
)
IMPLEMENTATION_DEPENDENCIES = (
    Path(__file__).resolve(),
    Path(__file__).with_name("asr_router.py").resolve(),
    Path(__file__).with_name("hyperframes_router.py").resolve(),
    Path(__file__).with_name("director_contracts.py").resolve(),
)
LOW_INFORMATION = {"打开", "点击", "添加", "然后", "接着", "这里", "下面", "这个", "那个"}


def _check(name: str, passed: bool, detail: str) -> dict[str, Any]:
    return {"name": name, "status": "pass" if passed else "failed", "detail": detail}


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def evaluate_scenario(row: dict[str, Any]) -> dict[str, Any]:
    project = {
        "content": {"type": row.get("content_type"), "task": row.get("task")},
        "transcription": {"router": {"backends": {
            "local_faster_whisper": {"available": True},
            "funasr": {"available": True},
            "whisperx": {"available": True},
        }}},
    }
    evidence = {
        "content_type": row.get("content_type"), "task": row.get("task"),
        **(row.get("asr_evidence") or {}),
    }
    route = route_hyperframes(project, evidence)
    asr = choose_backend(project["transcription"]["router"], evidence)
    captions = row.get("captions") or {}
    preservation = row.get("preservation") or {}
    semantic = row.get("semantic") or {}
    geometry = row.get("geometry") or {}
    audio = row.get("audio") or {}
    events = semantic.get("events") or []
    anchors = [str(event.get("anchor") or "").strip() for event in events]
    signatures = [json.dumps(event.get("visual_signature") or {}, sort_keys=True,
                             ensure_ascii=False) for event in events]
    cue_count = int(audio.get("sfx_cue_count", 0))
    checks = [
        _check("caption_timing_and_sentence_segmentation",
               captions.get("word_aligned") is True
               and captions.get("sentence_boundary_pass") is True
               and float(captions.get("max_sync_error_seconds", 99)) <= 0.12,
               "word alignment, sentence boundaries, and <=120 ms fixture error"),
        _check("content_preservation",
               preservation.get("tail_covered") is True
               and float(preservation.get("unapproved_removed_seconds", 99)) == 0
               and float(preservation.get("coverage_ratio", 0)) >= 0.98,
               "tail covered, no unapproved semantic deletion, >=98% coverage"),
        _check("semantic_relevance",
               bool(events) and all(float(event.get("relevance_score", 0)) >= 0.75 for event in events)
               and all(anchor and anchor not in LOW_INFORMATION for anchor in anchors),
               "every event is evidence-backed and avoids low-information anchors"),
        _check("keyword_and_form_repetition",
               len(anchors) == len(set(anchors)) and len(signatures) == len(set(signatures)),
               "anchors and structural signatures are distinct"),
        _check("geometry_occlusion_crop_whitespace",
               all(int(geometry.get(name, 99)) == 0 for name in
                   ("overflow_count", "occlusion_count", "crop_count", "excess_whitespace_count")),
               "no seeded overflow, collision, crop, or excess whitespace"),
        _check("sfx_audibility_and_repetition",
               cue_count > 0
               and int(audio.get("audible_sfx_count", 0)) == cue_count
               and float(audio.get("sfx_repeat_ratio", 1)) <= 0.35
               and audio.get("all_visual_events_have_audio_decision") is True,
               "all visual events have cue/silence decisions; cues audible and varied"),
        _check("bgm_speech_loudness",
               audio.get("bgm_decision_recorded") is True
               and float(audio.get("speech_lufs", -99)) - float(audio.get("bgm_lufs", 99)) >= 8
               and float(audio.get("true_peak_dbtp", 99)) <= -1.0,
               "speech remains >=8 LU above BGM and true peak is safe"),
        _check("studio_render_parity", row.get("preview_render_parity") is True,
               "representative Studio and render snapshots match within tolerance"),
        _check("manual_correction_cost",
               int((row.get("manual_review") or {}).get("correction_count", 99)) <= 2
               and float((row.get("manual_review") or {}).get("minutes", 99)) <= 10,
               "fixture needs at most two small corrections and ten minutes"),
        _check("hyperframes_route", route.get("route") == row.get("expected_hyperframes_route"),
               f"selected {route.get('route')}"),
        _check("asr_route", asr.get("selected_backend") == row.get("expected_asr_backend"),
               f"selected {asr.get('selected_backend')}"),
    ]
    return {
        "id": row.get("id"), "fixture_type": row.get("fixture_type"),
        "evidence_kind": row.get("evidence_kind"),
        "scenario_evidence_sha256": _stable_hash(row),
        "status": "pass" if all(check["status"] == "pass" for check in checks) else "failed",
        "checks": checks, "routing": {"hyperframes": route, "asr": asr},
    }


def evaluate_suite(
    payload: dict[str, Any], *, fixture_source: Path | None = None,
) -> dict[str, Any]:
    scenarios = [evaluate_scenario(row) for row in (payload.get("scenarios") or [])]
    types = [row.get("fixture_type") for row in scenarios]
    ids = [row.get("id") for row in scenarios]
    found = set(types)
    coverage = sorted(REQUIRED_TYPES - found)
    duplicate_types = sorted({value for value in types if types.count(value) > 1 and value})
    duplicate_ids = sorted({value for value in ids if ids.count(value) > 1 and value})
    check_contract_pass = bool(scenarios) and all(
        [check.get("name") for check in row.get("checks") or []] == list(CHECK_NAMES)
        and all(check.get("name") and check.get("status") in {"pass", "failed"}
                for check in row["checks"])
        for row in scenarios
    )
    source_hash = sha256_file(fixture_source) if fixture_source and fixture_source.is_file() else _stable_hash(payload)
    return {
        "schema_version": 1,
        "evidence_boundary": (
            "Six structured short-fixture contracts exercise routing and shared automated gates; "
            "they do not replace human aesthetic, identity, or real-platform review."
        ),
        "required_types": sorted(REQUIRED_TYPES),
        "fixture_source": _repository_id(fixture_source) if fixture_source else None,
        "fixture_source_sha256": source_hash,
        "implementation": _repository_id(Path(__file__)),
        "implementation_sha256": sha256_file(Path(__file__).resolve()),
        "implementation_dependencies": {
            _repository_id(path): sha256_file(path) for path in IMPLEMENTATION_DEPENDENCIES
        },
        "missing_types": coverage,
        "duplicate_types": duplicate_types,
        "duplicate_ids": duplicate_ids,
        "scenario_count": len(scenarios),
        "scenarios": scenarios,
        "status": "pass" if not coverage and not duplicate_types and not duplicate_ids
        and check_contract_pass and len(scenarios) == len(REQUIRED_TYPES)
        and all(row["status"] == "pass" for row in scenarios) else "failed",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixtures", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    payload = json.loads(Path(args.fixtures).read_text(encoding="utf-8"))
    fixture_path = Path(args.fixtures).resolve()
    report = evaluate_suite(payload, fixture_source=fixture_path)
    write_json(Path(args.out), report)
    print(Path(args.out).resolve())
    return 0 if report["status"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
