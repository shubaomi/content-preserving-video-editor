#!/usr/bin/env python3
"""Turn an existing-edit analysis and transcript into adaptive semantic events."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from attention_planner import plan_attention_events


SEMANTIC_CUES = ("不是", "因为", "所以", "关键", "本质", "区别", "建议", "首先", "最后", "记住", "其实", "如果")


def load_segments(path: Path) -> list[dict]:
    data = json.loads(path.read_text(encoding="utf-8"))
    segments = data.get("segments", data if isinstance(data, list) else [])
    return [item for item in segments if isinstance(item, dict) and item.get("text")]


def load_glossary(path: Path | None) -> list[str]:
    if path is None:
        return []
    if path.suffix.lower() == ".json":
        data = json.loads(path.read_text(encoding="utf-8"))
        values = data.get("terms", []) if isinstance(data, dict) else data
    else:
        values = path.read_text(encoding="utf-8").splitlines()
    if not isinstance(values, list):
        raise ValueError("glossary must be a JSON list, a JSON object with terms, or a line-delimited text file")
    return [str(value).strip() for value in values if str(value).strip()]


def semantic_score(segment: dict, target: float) -> float:
    text = str(segment.get("text", "")).strip()
    midpoint = (float(segment.get("start", 0)) + float(segment.get("end", 0))) / 2
    distance = abs(midpoint - target)
    cue_bonus = sum(1.5 for cue in SEMANTIC_CUES if cue in text)
    length_bonus = min(len(text), 36) / 18.0
    question_penalty = 0.8 if text.endswith(("吗", "呢", "?", "？")) else 0.0
    return 10.0 - distance / 5.0 + cue_bonus + length_bonus - question_penalty


def choose_segment(segments: list[dict], target: float, used: set[int]) -> tuple[int, dict]:
    window = [
        (index, segment) for index, segment in enumerate(segments)
        if index not in used and abs((float(segment.get("start", 0)) + float(segment.get("end", 0))) / 2 - target) <= 22
    ]
    if not window:
        window = [(index, segment) for index, segment in enumerate(segments) if index not in used]
    return max(window, key=lambda pair: semantic_score(pair[1], target))


def build_plan(analysis: dict, segments: list[dict], *, profile: str = "adaptive_dynamic",
               content_type: str = "polish_existing", seed: str = "default",
               glossary: list[str] | None = None) -> dict:
    duration = float(analysis.get("input", {}).get("duration") or max((float(item.get("end", 0)) for item in segments), default=0))
    attention = plan_attention_events(
        segments, duration, profile=profile, content_type=content_type, seed=seed,
        burned_captions=not bool(analysis["captions"].get("add_caption_layer", False)),
        glossary=glossary,
    )
    beats = [{
        "id": event["id"], "start": event["start"], "duration": event["duration"],
        "type": event["visual_family"], "message": event["transcript_evidence"]["text"],
        "reason": f"{event['purpose']} anchored to a complete spoken idea", "source_segment": event["transcript_evidence"]["segment_index"],
    } for event in attention["events"]]
    return {
        "schema_version": 2,
        "input_mode": "polish_existing",
        "duration": attention["duration"],
        "beats": beats,
        "attention_events": attention["events"],
        "intentional_quiet_sections": attention["intentional_quiet_sections"],
        "constraints": {**attention["constraints"], "preserve_timeline": True, "preserve_source_audio": True, "add_caption_layer": bool(analysis["captions"].get("add_caption_layer", False)), "add_bgm": bool(analysis["audio"].get("add_bgm", False)), "profile": profile, "recommended_events_per_minute": attention["recommended_events_per_minute"]},
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--analysis", required=True)
    parser.add_argument("--transcript", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--profile", choices=("calm", "balanced", "adaptive_dynamic"), default="adaptive_dynamic")
    parser.add_argument("--content-type", choices=("screen_tutorial", "polish_existing"), default="polish_existing")
    parser.add_argument("--seed", default="default")
    parser.add_argument("--glossary", type=Path, help="JSON terms/list or line-delimited verified project terminology.")
    args = parser.parse_args()
    analysis = json.loads(Path(args.analysis).read_text(encoding="utf-8"))
    plan = build_plan(analysis, load_segments(Path(args.transcript)), profile=args.profile, content_type=args.content_type, seed=args.seed, glossary=load_glossary(args.glossary))
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
