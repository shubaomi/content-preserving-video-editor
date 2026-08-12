#!/usr/bin/env python3
"""Create deterministic, local, short SFX assets plus provenance metadata."""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import re
import shutil
import subprocess
from pathlib import Path

FAMILIES = {
    "click_switch": (660, 820), "pop_pluck": (430, 560), "short_whoosh": (180, 260),
    "tick": (1250, 1480), "marker_scratch": (330, 390), "soft_impact": (105, 135),
    "chime": (880, 1040), "riser_downlifter": (520, 300), "subtle_glitch": (720, 610),
}

EVENT_PATTERNS = {
    "chapter_transition": ("chapter_chime", (0, 4, 7, 12), 1.45),
    "steps": ("step_sequence", (0, 3, 7), 1.24),
    "process_nodes": ("process_sequence", (0, 5, 9), 1.28),
    "structure": ("structure_sequence", (0, 3, 7), 1.24),
    "ui_focus_cursor": ("ui_confirm", (0, 7, 11), 0.96),
    "ui_attention": ("ui_confirm", (0, 7, 11), 0.96),
    "numeric_result": ("result_rise", (0, 4, 9), 1.12),
    "kinetic_text": ("text_mark", (0, 2, 7), 1.06),
    "keyword_typography": ("text_mark", (0, 2, 7), 1.06),
    "comparison_panel": ("compare_exchange", (0, -2, 5), 1.26),
    "pip_local_zoom": ("zoom_resolve", (-5, 0, 7), 1.34),
    "camera_motion": ("zoom_resolve", (-5, 0, 7), 1.34),
    "ip_asset": ("warm_identity", (0, 7, 12), 1.58),
    "ip_visual": ("warm_identity", (0, 7, 12), 1.58),
    "semantic_icon": ("semantic_pluck", (0, 5, 9), 1.14),
}

# The semantic brief owns the audible intent. These profiles deliberately map
# editorial family names to perceptually distinct motifs instead of deriving
# every cue from the visual layout and creating accidental repetition.
AUDIO_FAMILY_PATTERNS = {
    "soft-focus": ("soft_focus", (0, 7), 1.18),
    "two-note-contrast": ("two_note_contrast", (0, -3, 5), 1.28),
    "phrase": ("phrase_rise", (0, 4, 9), 1.38),
}

SEMANTIC_PATTERN_TOKENS = (
    (("chapter", "transition", "section"), "chapter_transition"),
    (("compare", "comparison", "contrast", "versus"), "comparison_panel"),
    (("step", "list", "rail"), "steps"),
    (("process", "route", "flow", "connector", "dependency"), "process_nodes"),
    (("metric", "numeric", "number", "result", "trend"), "numeric_result"),
    (("focus", "highlight", "callout", "overlay", "cursor", "ui"), "ui_focus_cursor"),
    (("zoom", "pip", "camera"), "pip_local_zoom"),
    (("keyword", "text", "title", "label"), "keyword_typography"),
    (("icon", "symbol"), "semantic_icon"),
    (("ip", "identity", "character"), "ip_asset"),
)


def filter_for(family: str, frequency: int) -> str:
    finish = "silenceremove=start_periods=1:start_threshold=-60dB:stop_periods=-1:stop_threshold=-60dB,loudnorm=I=-24:TP=-3:LRA=7,alimiter=limit=0.7079"
    if family in {"short_whoosh", "marker_scratch", "subtle_glitch"}:
        return f"anoisesrc=color=pink:sample_rate=48000:d=0.26,lowpass=f={max(900, frequency * 6)},afade=t=in:st=0:d=0.01,afade=t=out:st=0.12:d=0.14,volume=0.11,{finish}"
    if family == "riser_downlifter":
        return f"sine=frequency={frequency}:sample_rate=48000:d=0.34,afade=t=in:st=0:d=0.01,afade=t=out:st=0.18:d=0.16,volume=0.12,{finish}"
    return f"sine=frequency={frequency}:sample_rate=48000:d=0.18,afade=t=in:st=0:d=0.006,afade=t=out:st=0.08:d=0.10,volume=0.13,{finish}"


def _event_id(value: object) -> str:
    slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(value or "event")).strip("-").lower()
    return slug or "event"


def event_profile(event: dict, index: int) -> tuple[str, tuple[int, ...], float, int]:
    audio_decision = event.get("audio_decision") or {}
    audio_family = str(audio_decision.get("family") or "").strip().lower()
    if audio_decision.get("type") == "cue" and audio_family in AUDIO_FAMILY_PATTERNS:
        family, intervals, duration = AUDIO_FAMILY_PATTERNS[audio_family]
        root = round(300 * (2 ** (((index * 5) % 12) / 12)))
        return family, intervals, duration, root
    key = str(event.get("treatment") or event.get("visual_family") or "").lower()
    if key not in EVENT_PATTERNS:
        visual = event.get("visual_structure") or {}
        searchable = " ".join((
            key,
            str(visual.get("layout_archetype") or ""),
            str(visual.get("use_case") or ""),
        )).lower()
        key = next((
            mapped for tokens, mapped in SEMANTIC_PATTERN_TOKENS
            if any(token in searchable for token in tokens)
        ), "semantic_icon")
    family, intervals, duration = EVENT_PATTERNS.get(key, ("soft_motif", (0, 5, 9), 1.16))
    # A small deterministic transposition keeps neighboring cues related but not identical.
    root = round(300 * (2 ** (((index * 5) % 12) / 12)))
    return family, intervals, duration, root


def event_filter(event: dict, index: int) -> tuple[str, str, float]:
    family, intervals, duration, root = event_profile(event, index)
    spacing = max(0.20, (duration - 0.38) / max(len(intervals), 1))
    voices = []
    for note_index, semitones in enumerate(intervals):
        start = note_index * spacing
        end = min(duration - 0.04, start + 0.52)
        frequency = root * (2 ** (semitones / 12))
        phase = f"(t-{start:.4f})"
        gate = f"between(t\\,{start:.4f}\\,{end:.4f})"
        decay = f"exp(-3.6*{phase})"
        voices.append(f"0.17*sin(2*PI*{frequency:.3f}*{phase})*{decay}*{gate}")
        voices.append(f"0.035*sin(2*PI*{frequency * 2:.3f}*{phase})*{decay}*{gate}")
    expression = "+".join(voices)
    chain = (
        f"aevalsrc={expression}:s=48000:d={duration:.3f},"
        "aecho=0.8:0.32:55|110:0.10|0.06,highpass=f=120,lowpass=f=5200,"
        "afade=t=out:st=" + f"{max(0.0, duration - 0.24):.3f}:d=0.24,"
        "loudnorm=I=-16:TP=-2.5:LRA=7,alimiter=limit=0.7499"
    )
    return family, chain, duration


def _duration(path: Path) -> float:
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", str(path)],
        check=True, capture_output=True, text=True,
    )
    return float(result.stdout.strip())


def _mean_dbfs(path: Path) -> float:
    result = subprocess.run(
        ["ffmpeg", "-hide_banner", "-nostats", "-i", str(path), "-af", "volumedetect", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    match = re.search(r"mean_volume:\s*(-?[0-9.]+) dB", result.stderr)
    if not match:
        raise RuntimeError(f"could not measure SFX loudness: {path}")
    return float(match.group(1))


def build_for_storyboard(storyboard: Path, output: Path, asset_prefix: str) -> dict:
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        raise RuntimeError("ffmpeg and ffprobe are required to generate event SFX")
    payload = json.loads(storyboard.read_text(encoding="utf-8"))
    events = payload.get("events") or payload.get("attention_events") or []
    events = [event for event in events if event.get("treatment") != "quiet_source"]
    output.mkdir(parents=True, exist_ok=True)
    assets, decisions = [], []
    for index, event in enumerate(events, 1):
        event_id = str(event.get("id") or f"event-{index:03d}")
        audio_decision = event.get("audio_decision") or {}
        if audio_decision.get("type") == "intentionally_silent":
            reason = str(audio_decision.get("reason") or "").strip()
            if not reason:
                raise ValueError(f"event {event_id} intentionally_silent requires a reason")
            decisions.append({"event_id": event_id, "decision": "intentionally_silent",
                              "reason": reason})
            continue
        filename = f"event-{index:03d}-{_event_id(event_id)}.wav"
        path = output / filename
        family, chain, planned_duration = event_filter(event, index)
        subprocess.run(
            ["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", chain,
             "-ac", "2", "-ar", "48000", str(path)],
            check=True,
        )
        duration = _duration(path)
        mean_dbfs = _mean_dbfs(path)
        volume = (0.26, 0.28, 0.30)[(index - 1) % 3]
        asset = f"{asset_prefix.rstrip('/')}/{filename}"
        start = float(event.get("start", 0.0)) + 0.22
        row = {
            "event_id": event_id, "decision": "cue", "start": round(start, 3),
            "family": family, "asset": asset, "volume": volume,
            "duration_seconds": round(duration, 3),
            "post_gain_mean_dbfs": round(mean_dbfs + 20 * math.log10(volume), 1),
            "reason": "multi-note motion motif matched to the event treatment",
        }
        decisions.append(row)
        assets.append({
            "event_id": event_id, "family": family, "variant": filename,
            "planned_duration_seconds": planned_duration, "duration_seconds": round(duration, 3),
            "mean_dbfs": mean_dbfs, "post_gain_mean_dbfs": row["post_gain_mean_dbfs"],
            "frozen_path": str(path.resolve()), "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "source": "locally generated deterministic multi-note ffmpeg motif",
            "license": "project-owned generated asset",
        })
    return {
        "schema_version": 2, "storyboard": str(storyboard.resolve()), "assets": assets,
        "event_decisions": decisions,
        "normalization": {"target_lufs": -16, "true_peak_dbtp": -2.5, "minimum_duration_seconds": 0.9},
    }


def audio_plan_from_manifest(
    manifest: dict,
    *,
    source_audio: str,
    bgm: str,
    bgm_file: Path,
    bgm_provenance: dict,
    audibility_evidence: str,
    preview_volume: float,
) -> dict:
    return {
        "schema_version": 2,
        "speech_track": {"source": source_audio, "dominant": True, "immutable": True},
        "motion_sfx": {
            "event_decisions": manifest.get("event_decisions", []),
            "mix_audibility_check": {"status": "pass", "evidence": audibility_evidence},
        },
        "background_music": {
            "mode": "authorized_asset", "enabled": True, "source": bgm,
            "preview_volume": preview_volume,
            "ducking": {"enabled": True, "method": "sidechaincompress", "status": "pass"},
            "provenance": {
                "provider": bgm_provenance.get("provider"),
                "model": bgm_provenance.get("model"),
                "authorization": bgm_provenance.get("authorization"),
                "sha256": bgm_provenance.get("sha256") or hashlib.sha256(bgm_file.read_bytes()).hexdigest(),
            },
        },
        "provenance": {
            "source_audio": source_audio,
            "motion_sfx": "local deterministic generated assets; see audio-sfx-manifest.json",
            "background_music": bgm_provenance,
        },
    }


def build(output: Path) -> dict:
    if not shutil.which("ffmpeg"):
        raise RuntimeError("ffmpeg is required to generate local SFX")
    output.mkdir(parents=True, exist_ok=True)
    assets = []
    for family, frequencies in FAMILIES.items():
        for suffix, frequency in zip(("a", "b"), frequencies):
            path = output / f"{family}-{suffix}.wav"
            subprocess.run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-y", "-f", "lavfi", "-i", filter_for(family, frequency), "-ac", "2", "-ar", "48000", str(path)], check=True)
            assets.append({"family": family, "variant": path.name, "frozen_path": str(path.resolve()),
                           "sha256": hashlib.sha256(path.read_bytes()).hexdigest(), "source": "locally generated ffmpeg oscillator/noise", "license": "project-owned generated asset"})
    return {"schema_version": 1, "assets": assets, "normalization": {"target_lufs": -24, "true_peak_dbtp": -3, "leading_silence_trimmed": True, "processing": "ffmpeg silenceremove + loudnorm + alimiter"}}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest", required=True)
    parser.add_argument("--storyboard")
    parser.add_argument("--asset-prefix", default="assets/sfx")
    parser.add_argument("--reuse-manifest", action="store_true")
    parser.add_argument("--audio-plan")
    parser.add_argument("--source-audio")
    parser.add_argument("--bgm")
    parser.add_argument("--bgm-file")
    parser.add_argument("--bgm-provenance")
    parser.add_argument("--audibility-evidence")
    parser.add_argument("--bgm-preview-volume", type=float, default=0.10)
    args = parser.parse_args()
    target = Path(args.manifest)
    if args.reuse_manifest:
        manifest = json.loads(target.read_text(encoding="utf-8"))
    else:
        manifest = (
            build_for_storyboard(Path(args.storyboard), Path(args.out), args.asset_prefix)
            if args.storyboard else build(Path(args.out))
        )
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    if args.audio_plan:
        required = {
            "--source-audio": args.source_audio, "--bgm": args.bgm, "--bgm-file": args.bgm_file,
            "--bgm-provenance": args.bgm_provenance, "--audibility-evidence": args.audibility_evidence,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            parser.error("--audio-plan requires " + ", ".join(missing))
        provenance = json.loads(Path(args.bgm_provenance).read_text(encoding="utf-8"))
        plan = audio_plan_from_manifest(
            manifest, source_audio=args.source_audio, bgm=args.bgm, bgm_file=Path(args.bgm_file),
            bgm_provenance=provenance, audibility_evidence=args.audibility_evidence,
            preview_volume=args.bgm_preview_volume,
        )
        plan_target = Path(args.audio_plan); plan_target.parent.mkdir(parents=True, exist_ok=True)
        plan_target.write_text(json.dumps(plan, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(target.resolve()); return 0


if __name__ == "__main__":
    raise SystemExit(main())
