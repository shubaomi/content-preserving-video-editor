"""Isolated WP0 checks, not imported by production and never an approval issuer.

Structural validation, byte/scope verification, and normalized timeline binding are
separate layers. A schema pass is not a license, identity, semantic or media pass.
Production adapters and authoritative human-review integration remain WP3 work.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import math
from pathlib import Path
from typing import Callable

from jsonschema import Draft202012Validator

ROOT = Path(__file__).resolve().parents[2]
SCHEMA = ROOT / "references/motion-editorial-v3-design/schemas/editorial-motion.schema.json"
PHASES = ("entrance", "explain", "hold", "exit")
ROLES = {
    "hook_plan": {"source", "transcript", "base_edl", "evidence"},
    "timeline_projection": {"source", "transcript", "base_edl", "candidate_edl", "hook_plan", "approval"},
    "shot_motion_plan": {"projection", "semantic_brief", "evidence", "design"},
    "short_validation_plan": {"plan", "source", "baseline", "shot_plan"},
}
DISABLED = dict(enabled=False, version=1, direction=None, opening="propose_only", design_approval_path=None, hook_approval_path=None)


class ContractError(ValueError):
    """Input fails an explicit isolated contract invariant."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ContractError(message)


def finite_tree(value) -> None:
    if isinstance(value, float):
        require(math.isfinite(value), "non-finite number")
    elif isinstance(value, dict):
        for item in value.values():
            finite_tree(item)
    elif isinstance(value, list):
        for item in value:
            finite_tree(item)


def loads_strict(text: str):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, f"duplicate JSON key: {key}")
            result[key] = value
        return result

    def reject(value):
        raise ContractError(f"invalid JSON constant: {value}")

    try:
        result = json.loads(text, object_pairs_hook=pairs, parse_constant=reject)
    except json.JSONDecodeError as exc:
        raise ContractError(str(exc)) from exc
    finite_tree(result)
    return result


def load_json(path: Path):
    return loads_strict(Path(path).read_text(encoding="utf-8-sig"))


def sha256(path: Path) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def span(value: dict) -> tuple[float, float]:
    start, end = value["start"], value["end"]
    require(all(isinstance(x, (int, float)) and not isinstance(x, bool) and math.isfinite(x) for x in (start, end)), "range values must be finite numbers")
    require(0 <= start < end, "range must be positive and half-open")
    return start, end


def close(left: float, right: float) -> bool:
    return math.isclose(left, right, abs_tol=1e-7, rel_tol=0)


def unique(items, key: str) -> dict:
    result = {}
    for item in items:
        require(item[key] not in result, f"duplicate {key}: {item[key]}")
        result[item[key]] = item
    return result


def normalize_speech(transcript: dict) -> list[dict]:
    """Words take precedence; segment fallback never invents word timestamps."""
    require(isinstance(transcript, dict), "transcript must be object")
    words = transcript.get("words", [])
    segments = transcript.get("segments", [])
    require(isinstance(words, list) and isinstance(segments, list), "words/segments must be arrays")
    source = words if words else segments
    normalized = []
    for index, item in enumerate(source):
        require(isinstance(item, dict), "speech item must be object")
        text = item.get("word", item.get("text"))
        require(isinstance(text, str) and bool(text.strip()), "empty or invalid speech text")
        require("start" in item and "end" in item, "speech timestamps missing")
        start, end = span(item)
        identifier = str(item.get("id", item.get("word_id", f"segment-{index}")))
        require(bool(identifier.strip()) and identifier != "None", "invalid speech ID")
        normalized.append(dict(id=identifier, text=text, start=start, end=end))
    unique(normalized, "id")
    require(all(a["start"] <= b["start"] for a,b in zip(normalized, normalized[1:])), "source speech order changed")
    return normalized


def audit_opening(transcript: dict) -> dict:
    """Measurements only; keyword cues are not proof of visible value."""
    speech = normalize_speech(transcript)
    cues = ("今天", "分享", "介绍", "关键", "为什么", "怎么", "效果", "问题", "功能", "结论")
    first = speech[0]["start"] if speech else None
    cue = next((s["start"] for s in speech if any(w in s["text"] for w in cues)), None)
    return dict(state="measured" if speech else "unknown", first_speech=first,
                duration=max((s["end"] for s in speech), default=None),
                speech_units=len(speech), first_value_cue=cue,
                visible_evidence_score=None, visible_evidence_status="unassessed",
                cue_is_editorial_inference=True, authorizes_reorder=False)


def validate_contract(artifact: dict) -> None:
    """Schema + local relational invariants; does not issue runtime readiness."""
    finite_tree(artifact)
    errors = list(Draft202012Validator(load_json(SCHEMA)).iter_errors(artifact))
    require(not errors, "; ".join(e.message for e in errors[:3]))
    inputs = unique(artifact["inputs"], "id")
    require(ROLES[artifact["kind"]] <= {i["role"] for i in inputs.values()}, "required evidence role missing")

    def ref(identifier, role):
        require(identifier in inputs and inputs[identifier]["role"] in role, f"unresolved/wrong-role reference: {identifier}")

    p = artifact["payload"]
    if artifact["kind"] == "hook_plan":
        unique(p["candidates"], "id")
        for item in p["candidates"]:
            start, end = span(item["source_range"])
            require(2 <= end-start <= 6, "hook must be 2-6 seconds")
            ref(item["source_ref"], {"source"})
            for identifier in item["frame_refs"]:
                ref(identifier, {"evidence"})
    elif artifact["kind"] == "timeline_projection":
        ref(p["edl_ref"], {"candidate_edl"}); ref(p["approval_ref"], {"approval"})
        segments = unique(p["segments"], "segment_id")
        last_end = 0
        for item in p["segments"]:
            ref(item["source_ref"], {"source"})
            start, end = span(item["source_range"])
            require(item["output_start"] >= last_end-1e-7, "segments overlap or out of output order")
            require((item["role"] == "hook" and item["base_segment_id"] is None) or (item["role"] == "body" and bool(item["base_segment_id"])), "segment baseline identity invalid")
            last_end = item["output_start"] + end-start
        require(close(last_end, p["output_duration"]), "output duration differs from EDL endpoint")
        unique(p["words"], "occurrence_id")
        previous = -1
        for word in p["words"]:
            require(word["segment_id"] in segments, "unknown word segment")
            segment = segments[word["segment_id"]]
            start,end = span(word["source_range"]); out_start,out_end = span(word["output_range"])
            require(word["occurrence_id"] == f'{word["segment_id"]}:{word["source_word_id"]}', "incorrect occurrence ID")
            require(segment["source_range"]["start"] <= start < end <= segment["source_range"]["end"], "word crosses segment edge")
            shift = segment["output_start"] - segment["source_range"]["start"]
            require(close(out_start,start+shift) and close(out_end,end+shift), "word mapping drift")
            require(out_start >= previous, "words not in output order")
            previous = out_start
    elif artifact["kind"] == "shot_motion_plan":
        ref(p["projection_ref"], {"projection"})
        unique(p["events"], "instance_id")
        for event in p["events"]:
            start,end = span(event["output_range"])
            require(event["instance_id"] == f'{event["semantic_id"]}@{event["segment_id"]}', "invalid semantic instance ID")
            require(all(w.startswith(event["segment_id"] + ":") for w in event["word_occurrence_ids"]), "word instance from other segment")
            for identifier in event["target_binding_ids"]:
                ref(identifier, {"target_binding"})
            if event["sound"]["asset_ref"] is not None:
                ref(event["sound"]["asset_ref"], {"audio"})
            crop = event["source_crop"]
            if crop:
                require(crop["x"]+crop["w"] <= 1 and crop["y"]+crop["h"] <= 1, "crop out of source bounds")
                require(event["decision"] == "shot", "crop changes require shot decision")
            if event["recipe"]:
                prefix = "A" if p["direction"] == "authentic_product_editorial" else "B"
                require(event["recipe"].startswith(prefix), "recipe belongs to other direction")
                require(tuple(x["phase"] for x in event["phases"]) == PHASES, "phases must be ordered entrance/explain/hold/exit")
                previous = 0
                for phase in event["phases"]:
                    require(previous <= phase["start"] <= phase["end"] <= end-start+1e-7, "phase overlap or event overflow")
                    previous = phase["end"]
                require(close(event["phases"][0]["start"], 0) and close(previous, end-start), "phases must span event through clean exit")
    else:
        ref(p["baseline_ref"], {"baseline"}); ref(p["shot_plan_ref"], {"shot_plan"})


def verify_evidence(artifact: dict, authorized_roots: list[Path]) -> dict[str, Path]:
    """Read-only hash/scope check; rights and review authority are NOT inferred."""
    validate_contract(artifact)
    require(artifact["evidence_tier"] == "runtime", "synthetic fixture is not runtime evidence")
    try:
        roots = [Path(p).resolve(strict=True) for p in authorized_roots]
    except OSError as exc:
        raise ContractError("authorized root does not exist") from exc
    require(bool(roots) and all(p.is_dir() for p in roots), "authorized roots required")
    result = {}
    for item in artifact["inputs"]:
        path = Path(item["path"])
        require(path.is_absolute(), "evidence path must be absolute")
        try:
            resolved = path.resolve(strict=True)
        except OSError as exc:
            raise ContractError(f"missing evidence: {item['id']}") from exc
        require(resolved.is_file() and any(resolved.is_relative_to(root) for root in roots), "evidence escapes authorized roots (including link/junction)")
        require(sha256(resolved) == item["sha256"], f"stale evidence: {item['id']}")
        result[item["id"]] = resolved
    return result


def validate_hook_bindings(artifact: dict, source_words: dict[str, list[dict]],
                           frames: dict[str, dict], source_durations: dict[str, float],
                           retained_semantic_ids: set[str]) -> None:
    """Cross-check normalized facts; self-contained meaning remains human review.

    Frame entries contain source_ref and timestamp. Callers bind these normalized
    facts to hash-verified files; production format adapters are not implemented.
    """
    validate_contract(artifact)
    require(artifact["kind"] == "hook_plan", "expected hook plan")
    for candidate in artifact["payload"]["candidates"]:
        source = candidate["source_ref"]
        require(source in source_words and source in source_durations, "missing source facts")
        duration = source_durations[source]
        require(type(duration) in (int, float) and math.isfinite(duration) and duration > 0, "invalid source duration")
        start,end = span(candidate["source_range"])
        require(end <= duration, "hook beyond source duration")
        words = normalize_speech({"words": source_words[source]})
        selected = [word for word in words if word["start"] < end and word["end"] > start]
        require(bool(selected), "hook has no spoken evidence")
        require(all(start <= w["start"] and w["end"] <= end for w in selected), "hook cuts a source word")
        require(candidate["word_ids"] == [w["id"] for w in selected], "hook word IDs/order/coverage differ from source")
        compact = lambda text: "".join(text.split())
        require(compact(candidate["quote"]) == compact("".join(w["text"] for w in selected)), "hook quote differs from source words")
        require(set(candidate["payoff_semantic_ids"]) <= retained_semantic_ids, "hook payoff absent from retained body")
        for identifier in candidate["frame_refs"]:
            require(identifier in frames, "hook frame metadata absent")
            frame = frames[identifier]
            timestamp = frame.get("timestamp")
            require(type(timestamp) in (int, float) and math.isfinite(timestamp), "invalid frame timestamp")
            require(frame.get("source_ref") == source and start <= timestamp < end, "hook frame outside source excerpt")


def validate_projection_bindings(artifact: dict, baseline: list[dict], source_words: list[dict], authoritative_segments: list[dict]) -> None:
    """Normalized isolated adapters only. Does not edit EDL or parse production EDL."""
    validate_contract(artifact)
    require(artifact["kind"] == "timeline_projection", "expected projection")
    p = artifact["payload"]
    require(p["segments"] == authoritative_segments, "projection differs from authoritative EDL")
    require(len({s["source_ref"] for s in p["segments"]}) == 1, "isolated word adapter accepts one source only")
    hooks = [s for s in p["segments"] if s["role"] == "hook"]
    require(len(hooks) <= 1, "multiple hooks outside scope")
    shift = 0
    if hooks:
        hook = hooks[0]
        require(p["segments"][0] == hook and hook["output_start"] == 0, "hook must be first")
        start,end = span(hook["source_range"]); shift = end-start
        require(2 <= shift <= 6, "hook duration outside scope")
    body = [s for s in p["segments"] if s["role"] == "body"]
    require(len(body) == len(baseline), "body coverage changed")
    unique(baseline, "segment_id")
    for current, original in zip(body, baseline):
        require(current["base_segment_id"] == original["segment_id"], "body order changed")
        for field in ("source_ref", "source_range", "speed"):
            require(current[field] == original[field], f"body {field} changed")
        require(close(current["output_start"],original["output_start"]+shift), "baseline gap changed")
    words = normalize_speech({"words": source_words})
    expected = []
    for segment in p["segments"]:
        a,b = span(segment["source_range"])
        for word in words:
            if word["start"] < b and word["end"] > a:
                require(a <= word["start"] and word["end"] <= b, "segment cuts a source word")
                offset = segment["output_start"] - a
                expected.append(dict(occurrence_id=f'{segment["segment_id"]}:{word["id"]}', segment_id=segment["segment_id"], source_word_id=word["id"], text=word["text"], source_range=dict(start=word["start"],end=word["end"]), output_range=dict(start=word["start"]+offset,end=word["end"]+offset)))
    require(p["words"] == expected, "projected words not exactly derived from source/EDL")


def validate_hook_authority(artifact: dict, receipt: dict, authority: Callable | None, hook_plan: dict | None = None) -> None:
    """A caller-supplied TRUSTED review adapter must verify user identity/message.

    No default adapter exists in WP0. A JSON boolean or hash is not authority.
    The callback is application code, never loaded from an input path or JSON.
    """
    require(callable(authority), "external authoritative review adapter required")
    validate_contract(artifact)
    require(artifact["kind"] == "timeline_projection", "approval requires projection")
    require(isinstance(hook_plan, dict), "exact hook plan required")
    validate_contract(hook_plan)
    require(hook_plan["kind"] == "hook_plan" and hook_plan["payload"]["state"] == "proposed", "hook plan is not a proposal")
    require(receipt.get("kind") == "hook_excerpt" and receipt.get("scope") == "short_preview", "wrong approval kind/scope")
    for field in ("candidate_id", "original_user_message", "operator", "timestamp"):
        require(isinstance(receipt.get(field), str) and bool(receipt[field].strip()), f"approval missing {field}")
    bindings = receipt.get("input_hashes", {})
    for role in ("source", "transcript", "base_edl", "hook_plan"):
        expected = {i["id"]: i["sha256"] for i in artifact["inputs"] if i["role"] == role}
        require(bool(expected) and all(bindings.get(k) == v for k,v in expected.items()), f"approval stale/missing {role}")
    chosen = next((candidate for candidate in hook_plan["payload"]["candidates"] if candidate["id"] == receipt["candidate_id"]), None)
    require(chosen is not None, "approved candidate absent from plan")
    hooks = [s for s in artifact["payload"]["segments"] if s["role"] == "hook"]
    require(len(hooks) == 1 and hooks[0]["source_ref"] == chosen["source_ref"] and hooks[0]["source_range"] == chosen["source_range"], "projection differs from approved excerpt")
    require(authority(receipt, artifact) is True, "external reviewer did not validate exact approval")


def migrate_fixture(config: dict) -> dict:
    """WP0 in-memory disabled fixture only. Enabling production is forbidden."""
    version = config.get("schema_version")
    require(type(version) is int and 1 <= version <= 15, "unsupported schema version")
    if version < 15:
        require("motion_editorial" not in config, "legacy config cannot smuggle new runtime settings")
    else:
        settings = config.get("motion_editorial")
        require(isinstance(settings, dict) and settings == DISABLED, "WP0 accepts only exact disabled schema15 fixture")
        require(all(type(settings[key]) is type(value) for key, value in DISABLED.items()), "schema15 setting types must be exact")
    result = copy.deepcopy(config)
    result.update(schema_version=15, motion_editorial=copy.deepcopy(DISABLED))
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("artifact", type=Path)
    parser.add_argument("--verify-root", action="append", type=Path, default=[])
    args = parser.parse_args()
    artifact = load_json(args.artifact)
    validate_contract(artifact)
    if args.verify_root:
        verify_evidence(artifact, args.verify_root)
    print(json.dumps(dict(status="pass", scope="structure_and_hashes" if args.verify_root else "structure_only", runtime_authorized=False, aesthetic_approved=False)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
