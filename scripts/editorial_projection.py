"""Read-only output instances derived from video-use EDLs (ME-AMEND-01).

No filesystem, edits, renderer, or approval writer lives here. The caller must
load strict JSON and verify the exact file bytes against ``input_hashes`` before
calling. Hash strings alone do not establish that provenance. A trusted hook
authority receives the complete detached context, not a user-provided boolean.
Legacy semantic validators and source briefs are deliberately untouched.
"""
from __future__ import annotations

import copy
from decimal import Decimal
from fractions import Fraction
import hashlib
import json
import math
import re
from typing import Any, Callable


class ProjectionError(ValueError):
    """An input cannot be projected without changing meaning or authority."""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProjectionError(message)


def _finite(value: Any) -> None:
    if isinstance(value, float):
        _require(math.isfinite(value), "non-finite input")
    elif isinstance(value, dict):
        for item in value.values():
            _finite(item)
    elif isinstance(value, list):
        for item in value:
            _finite(item)


def _number(value: Any, label: str) -> float:
    _require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
             f"{label} must be a finite nonnegative number")
    return float(value)


def _id(value: Any, label: str) -> str:
    _require(type(value) in (str, int) and bool(str(value).strip()), f"invalid {label}")
    result = str(value)
    _require(":" not in result and "@" not in result, f"reserved separator in {label}")
    return result


def _range(start: Any, end: Any) -> tuple[float, float]:
    a, b = _number(start, "start"), _number(end, "end")
    _require(a < b, "range must be positive and half-open")
    return a, b


def _source_id(value: Any) -> str:
    # A video-use source key may itself be an absolute Windows path.
    _require(isinstance(value, str) and bool(value.strip()), "invalid source ID")
    return value


def _equal_time(a: float, b: float) -> bool:
    return math.isclose(a, b, abs_tol=1e-9, rel_tol=0)


def _fps(value: Any) -> Fraction:
    try:
        if isinstance(value, dict):
            _require(set(value) == {"numerator", "denominator"}, "invalid fps fields")
            _require(all(type(v) is int and v > 0 for v in value.values()), "invalid rational fps")
            result = Fraction(value["numerator"], value["denominator"])
        elif type(value) is int:
            result = Fraction(value)
        elif isinstance(value, str) and re.fullmatch(r"[1-9]\d*/[1-9]\d*", value):
            result = Fraction(value)
        else:
            raise ProjectionError("fps must be an exact rational, not an approximate float")
        _require(result > 0, "fps must be positive")
        return result
    except (ZeroDivisionError, ValueError, TypeError) as exc:
        raise ProjectionError("invalid rational fps") from exc


def seconds_to_frame(seconds: float, fps: Any) -> int:
    """Round a nonnegative source/output boundary half-up using rational FPS."""
    value = _number(seconds, "seconds")
    rate = _fps(fps)
    # Exact rational arithmetic avoids finite Decimal division near half frames.
    frame = Fraction(Decimal(str(value))) * rate
    return (2 * frame.numerator + frame.denominator) // (2 * frame.denominator)


def _unique(rows: list[dict], key: str) -> None:
    ids = [row[key] for row in rows]
    _require(len(ids) == len(set(ids)), f"duplicate {key}")


def _normalize_edl(edl: dict) -> tuple[list[dict], float]:
    _require(isinstance(edl, dict), "EDL must be an object")
    _require(not ("segments" in edl and "ranges" in edl), "ambiguous EDL segment collections")
    rows = edl.get("segments", edl.get("ranges"))
    _require(isinstance(rows, list) and bool(rows), "EDL needs nonempty segments/ranges")
    result, cursor = [], 0.0
    for index, row in enumerate(rows):
        _require(isinstance(row, dict), "invalid EDL row")
        source = _source_id(row.get("source", edl.get("source")))
        a, b = _range(row.get("start"), row.get("end"))
        speed = row.get("speed", 1)
        _require(type(speed) in (int, float) and speed == 1, "only unchanged 1x EDL segments are supported")
        output = row.get("timeline_start")
        output = cursor if output is None else _number(output, "timeline_start")
        _require(output >= cursor, "EDL overlaps or is out of output order")
        role = row.get("role", "body")
        _require(role in ("body", "hook"), "unknown EDL role")
        result.append({"segment_id": _id(row.get("segment_id", f"segment-{index:06d}"), "segment ID"),
                       "source_ref": source, "source_range": {"start": a, "end": b},
                       "output_start": output, "output_end": output + b - a,
                       "speed": 1, "role": role})
        cursor = output + b - a
    _unique(result, "segment_id")
    duration = _number(edl.get("total_duration_s", edl.get("duration", cursor)), "EDL duration")
    _require(duration >= cursor, "EDL duration truncates retained footage")
    sources = edl.get("sources")
    if sources is not None:
        _require(isinstance(sources, dict) and all(s["source_ref"] in sources for s in result), "EDL source is unresolved")
    return result, duration


def _transcripts(transcript: dict, sources: set[str]) -> dict[str, list[dict]]:
    _require(isinstance(transcript, dict), "transcript must be an object")
    if "words" in transcript:
        _require(len(sources) == 1, "multiple sources need explicitly keyed transcripts")
        transcript = {next(iter(sources)): transcript}
    _require(set(transcript) == sources, "transcript sources do not match EDL")
    result = {}
    for source, document in transcript.items():
        _require(isinstance(document, dict) and isinstance(document.get("words"), list), "word transcript required")
        words = []
        for word in document["words"]:
            _require(isinstance(word, dict), "invalid word")
            a, b = _range(word.get("start"), word.get("end"))
            text = word.get("text", word.get("word"))
            _require(isinstance(text, str) and bool(text.strip()), "empty word text")
            words.append({"id": _id(word.get("id", word.get("word_id")), "word ID"), "text": text, "start": a, "end": b})
        _unique(words, "id")
        _require(all(a["start"] <= b["start"] for a, b in zip(words, words[1:])), "source words are out of order")
        result[source] = words
    return result


def _selected(words: list[dict], start: float, end: float) -> list[dict]:
    chosen = [word for word in words if word["start"] < end and word["end"] > start]
    _require(all(start <= word["start"] < word["end"] <= end for word in chosen), "EDL cuts a source word")
    return chosen


def _hashes(value: dict, duplicate: bool) -> dict:
    required = {"source", "transcript", "base_edl", "candidate_edl"}
    if duplicate:
        required.add("hook_plan")
    _require(isinstance(value, dict) and set(value) == required, "exact required input hashes missing or extra")
    _require(all(isinstance(v, str) and re.fullmatch(r"[a-f0-9]{64}", v) for v in value.values()), "invalid input SHA-256")
    return copy.deepcopy(value)


def _compare_body(base: list[dict], body: list[dict], shift: float, preserve_ids: bool) -> None:
    _require(len(base) == len(body), "retained body count changed")
    for original, current in zip(base, body):
        _require(original["role"] == current["role"] == "body", "body contains hook role")
        _require(all(original[key] == current[key] for key in ("source_ref", "source_range", "speed")), "body source/range/order/speed changed")
        _require(_equal_time(current["output_start"], original["output_start"] + shift), "body output gap changed")
        if preserve_ids:
            _require(original["segment_id"] == current["segment_id"], "preserved segment identity changed")
        current["base_segment_id"] = original["segment_id"]


def _hook_candidate(plan: dict, approval: dict, hashes: dict, hook: dict, words: dict) -> dict:
    _require(isinstance(plan, dict) and isinstance(approval, dict), "exact hook plan and approval required")
    payload = plan.get("payload", plan)
    _require(isinstance(payload, dict) and payload.get("state") == "proposed", "hook plan must be proposed")
    _require(not any(key in payload for key in ("approved", "approval", "approval_ref")), "hook plan cannot self-approve")
    candidates = payload.get("candidates")
    _require(isinstance(candidates, list) and bool(candidates), "hook candidates missing")
    _require(all(isinstance(c, dict) and isinstance(c.get("id"), str) for c in candidates), "invalid hook candidate")
    _unique(candidates, "id")
    _require(approval.get("kind") == "hook_excerpt" and approval.get("scope") == "short_preview", "wrong approval kind or scope")
    for key in ("candidate_id", "original_user_message", "operator", "timestamp"):
        _require(isinstance(approval.get(key), str) and bool(approval[key].strip()), f"approval missing {key}")
    expected = {key: value for key, value in hashes.items() if key != "candidate_edl"}
    _require(approval.get("input_hashes") == expected, "approval input hashes stale or scope changed")
    chosen = next((c for c in candidates if c["id"] == approval["candidate_id"]), None)
    _require(chosen is not None, "approved candidate absent")
    _require(chosen.get("source_ref") == hook["source_ref"] and chosen.get("source_range") == hook["source_range"], "actual hook differs from approved range")
    a, b = _range(**hook["source_range"])
    selected = _selected(words[hook["source_ref"]], a, b)
    _require(bool(selected), "hook needs real spoken words")
    ids = chosen.get("word_ids")
    _require(isinstance(ids, list) and [_id(i, "hook word") for i in ids] == [w["id"] for w in selected], "hook word coverage changed")
    compact = lambda text: "".join(text.split())
    _require(isinstance(chosen.get("quote"), str) and compact(chosen["quote"]) == compact("".join(w["text"] for w in selected)), "hook quote differs from transcript")
    for key in ("context_before", "context_after", "promise"):
        _require(isinstance(chosen.get(key), str) and bool(chosen[key].strip()), f"hook missing {key}")
    for key in ("frame_refs", "payoff_semantic_ids"):
        _require(isinstance(chosen.get(key), list) and bool(chosen[key]), f"hook missing {key}")
    return chosen


def build_projection(*, baseline_edl: dict, candidate_edl: dict, transcript: dict,
                     fps: Any, mode: str = "preserve_order", input_hashes: dict,
                     hook_plan: dict | None = None, approval: dict | None = None,
                     authority: Callable | None = None) -> dict:
    """Derive a detached projection; caller owns byte verification and EDL creation.

    ``authority(approval, context)`` must verify real user authority and exact
    hash-bound hook/context semantics. This callable is trusted application code,
    never an object selected by an artifact. It must return the literal True.
    Only 1x segments are supported; no implicit retiming or clipping is allowed.
    """
    _finite([baseline_edl, candidate_edl, transcript, fps, input_hashes, hook_plan, approval])
    _require(mode in ("preserve_order", "approved_duplicate"), "unknown projection mode")
    duplicate = mode == "approved_duplicate"
    hashes = _hashes(input_hashes, duplicate)
    rate = _fps(fps)
    base, base_duration = _normalize_edl(baseline_edl)
    candidate, duration = _normalize_edl(candidate_edl)
    _require(baseline_edl.get("sources") == candidate_edl.get("sources"), "EDL source bindings changed")
    sources = {s["source_ref"] for s in base}
    _require({s["source_ref"] for s in candidate} == sources, "candidate introduces/removes a source")
    words = _transcripts(transcript, sources)
    for segment in base:
        _selected(words[segment["source_ref"]], **segment["source_range"])
    if not duplicate:
        _require(hook_plan is None and approval is None and authority is None, "preserve_order forbids hook authority")
        forbidden = {"hook_plan", "hook_plan_ref", "hook_applied", "approval", "approval_ref", "hook_approval"}
        _require(not forbidden.intersection(candidate_edl), "preserve_order EDL carries hook/approval fields")
        _compare_body(base, candidate, 0, True)
        _require(_equal_time(duration, base_duration), "preserved total duration changed")
    else:
        _require(callable(authority), "trusted external hook authority required")
        _require(len(candidate) == len(base) + 1, "exactly one copied hook is allowed")
        hook = candidate[0]
        shift = hook["source_range"]["end"] - hook["source_range"]["start"]
        _require(hook["role"] == "hook" and hook["output_start"] == 0 and 2 <= shift <= 6, "invalid continuous 2-6s opening hook")
        hook["base_segment_id"] = None
        _compare_body(base, candidate[1:], shift, False)
        _require(_equal_time(duration, base_duration + shift), "duplicate total duration changed")
        _require(any(s["source_ref"] == hook["source_ref"]
                     and s["source_range"]["start"] <= hook["source_range"]["start"]
                     < hook["source_range"]["end"] <= s["source_range"]["end"] for s in base),
                 "hook must duplicate one continuous retained body excerpt")
        chosen = _hook_candidate(hook_plan, approval, hashes, hook, words)
        context = {"scope": "short_preview", "mode": mode, "input_hashes": hashes,
                   "hook_plan": hook_plan, "candidate": chosen,
                   "baseline_edl": baseline_edl, "candidate_edl": candidate_edl}
        _require(authority(copy.deepcopy(approval), copy.deepcopy(context)) is True, "external authority rejected exact hook")
    projected = []
    for segment in candidate:
        a, b = _range(**segment["source_range"])
        offset = segment["output_start"] - a
        for word in _selected(words[segment["source_ref"]], a, b):
            projected.append({"occurrence_id": f'{segment["segment_id"]}:{word["id"]}',
                              "segment_id": segment["segment_id"], "source_ref": segment["source_ref"],
                              "source_word_id": word["id"], "text": word["text"],
                              "source_start": word["start"], "source_end": word["end"],
                              "output_start": word["start"] + offset, "output_end": word["end"] + offset})
        segment["output_start_frame"] = seconds_to_frame(segment["output_start"], fps)
        segment["output_end_frame"] = seconds_to_frame(segment["output_end"], fps)
    _unique(projected, "occurrence_id")
    result = {"schema_version": 2, "kind": "timeline_projection", "mode": mode,
              "summary": {"mode": mode, "output_duration": duration}, "output_duration": duration,
              "fps": {"numerator": rate.numerator, "denominator": rate.denominator},
              "input_hashes": hashes, "segments": candidate, "words": projected,
              "authority": "derived_from_video_use_edl", "full_render_authorized": False}
    if duplicate:
        result["hook_approval"] = {"candidate_id": approval["candidate_id"], "scope": "short_preview"}
    validate_projection(result)
    return result


def validate_projection(projection: dict) -> None:
    """Check saved projection relations, not filesystem provenance or authority.

    To prove EDL/word completeness or exact authorization, rebuild using
    ``build_projection`` from the current byte-verified authorities. This check
    alone cannot turn an authored projection into authorized execution.
    """
    _require(isinstance(projection, dict), "projection must be an object")
    _finite(projection)
    _require(type(projection.get("schema_version")) is int and projection["schema_version"] == 2
             and projection.get("kind") == "timeline_projection", "unsupported projection")
    mode = projection.get("mode")
    _require(mode in ("preserve_order", "approved_duplicate"), "unknown projection mode")
    _hashes(projection.get("input_hashes"), mode == "approved_duplicate")
    rate = _fps(projection.get("fps"))
    _require(projection.get("full_render_authorized") is False, "projection cannot authorize full rendering")
    duration = _number(projection.get("output_duration"), "output duration")
    _require(projection.get("summary") == {"mode": mode, "output_duration": duration}, "projection summary drift")
    segments, words = projection.get("segments"), projection.get("words")
    _require(isinstance(segments, list) and bool(segments) and all(isinstance(s, dict) for s in segments), "invalid projection segments")
    _require(isinstance(words, list) and all(isinstance(w, dict) for w in words), "invalid projection words")
    previous, index = 0.0, {}
    for segment in segments:
        identifier = _id(segment.get("segment_id"), "segment ID")
        _require(identifier not in index, "duplicate segment ID")
        _source_id(segment.get("source_ref"))
        source_range = segment.get("source_range")
        _require(isinstance(source_range, dict) and set(source_range) == {"start", "end"}, "invalid source range")
        a, b = _range(**source_range)
        start, end = _range(segment.get("output_start"), segment.get("output_end"))
        _require(start >= previous and end <= duration and _equal_time(end - start, b - a), "projection segment mapping drift")
        _require(type(segment.get("speed")) in (int, float) and segment["speed"] == 1, "projection speed changed")
        _require(segment.get("role") in ("body", "hook"), "unknown segment role")
        if segment["role"] == "body":
            _id(segment.get("base_segment_id"), "base segment ID")
        else:
            _require(segment.get("base_segment_id") is None, "hook has a body identity")
        for field, value in (("output_start_frame", start), ("output_end_frame", end)):
            _require(type(segment.get(field)) is int and segment[field] == seconds_to_frame(value, {"numerator": rate.numerator, "denominator": rate.denominator}), "frame mapping drift")
        previous = end
        index[identifier] = segment
    hooks = [s for s in segments if s["role"] == "hook"]
    if mode == "preserve_order":
        _require(not hooks and "hook_approval" not in projection, "preserve_order contains hook authority")
    else:
        _require(len(hooks) == 1 and hooks[0] is segments[0] and hooks[0]["output_start"] == 0
                 and 2 <= hooks[0]["output_end"] <= 6, "invalid duplicate hook")
        receipt = projection.get("hook_approval")
        _require(isinstance(receipt, dict) and receipt.get("scope") == "short_preview"
                 and isinstance(receipt.get("candidate_id"), str), "hook scope missing")
    seen, previous = set(), -1.0
    for word in words:
        segment = index.get(word.get("segment_id"))
        _require(segment is not None, "word has unknown segment")
        identifier = _id(word.get("source_word_id"), "word ID")
        occurrence = f'{segment["segment_id"]}:{identifier}'
        _require(word.get("occurrence_id") == occurrence and occurrence not in seen, "word occurrence identity changed")
        _require(word.get("source_ref") == segment["source_ref"] and isinstance(word.get("text"), str) and bool(word["text"].strip()), "word source/text invalid")
        a, b = _range(word.get("source_start"), word.get("source_end"))
        start, end = _range(word.get("output_start"), word.get("output_end"))
        offset = segment["output_start"] - segment["source_range"]["start"]
        _require(segment["source_range"]["start"] <= a < b <= segment["source_range"]["end"]
                 and _equal_time(start, a + offset) and _equal_time(end, b + offset)
                 and start >= previous, "word mapping drift")
        seen.add(occurrence)
        previous = start


def _row_source_range(row: dict, sources: set[str]) -> tuple[str, float, float]:
    source = row.get("source_ref", row.get("source"))
    if source is None:
        _require(len(sources) == 1, "source-ambiguous instance")
        source = next(iter(sources))
    source = _source_id(source)
    _require(source in sources, "instance has unknown source")
    value = row.get("source_range")
    if value is None:
        value = {"start": row.get("source_start"), "end": row.get("source_end")}
    _require(isinstance(value, dict), "instance source range required")
    a, b = _range(value.get("start"), value.get("end"))
    return source, a, b


def project_instances(rows: list[dict], projection: dict, id_key: str = "event_id") -> list[dict]:
    """Map source-time rows without changing source data or guessing partial events.

    Rows require explicit source_start/source_end (or source_range), a stable
    ``id_key`` and optionally word_ids/transcript_word_ids. An omitted source is
    inferred only for a unique EDL source. Wholly unretained rows are unavailable
    and rejected; partial overlap is rejected, never silently clipped. IDs become
    source-id@segment-id, with the original retained in source_event_id.
    """
    _finite([rows, projection])
    _require(isinstance(rows, list) and all(isinstance(r, dict) for r in rows), "instances must be objects")
    validate_projection(projection)
    sources = {s["source_ref"] for s in projection["segments"]}
    ids = [_id(row.get(id_key), "instance ID") for row in rows]
    _require(len(ids) == len(set(ids)), "duplicate source instance IDs")
    output = []
    for row, identifier in zip(rows, ids):
        source, a, b = _row_source_range(row, sources)
        matches = [s for s in projection["segments"] if s["source_ref"] == source
                   and s["source_range"]["start"] < b and s["source_range"]["end"] > a]
        _require(bool(matches), "instance is not retained in output")
        for segment in matches:
            _require(segment["source_range"]["start"] <= a < b <= segment["source_range"]["end"], "partial instance crosses EDL boundary; adapter unavailable")
            word_rows = [w for w in projection["words"] if w["segment_id"] == segment["segment_id"]
                         and w["source_start"] < b and w["source_end"] > a]
            requested = row.get("transcript_word_ids", row.get("word_ids"))
            if requested is not None:
                _require(isinstance(requested, list), "word references must be a list")
                requested = [_id(w, "instance word") for w in requested]
                _require(len(requested) == len(set(requested)), "duplicate instance word references")
                available = {w["source_word_id"]: w for w in word_rows}
                _require(all(w in available for w in requested), "instance word is outside its source window")
                _require(requested == [w["source_word_id"] for w in word_rows if w["source_word_id"] in set(requested)],
                         "instance word references are out of source order")
                word_rows = [available[w] for w in requested]
            offset = segment["output_start"] - segment["source_range"]["start"]
            item = copy.deepcopy(row)
            item.update({id_key: f'{identifier}@{segment["segment_id"]}',
                         "instance_id": f'{identifier}@{segment["segment_id"]}',
                         "source_event_id": identifier, "segment_id": segment["segment_id"],
                         "source_ref": source, "source_start": a, "source_end": b,
                         "output_start": a + offset, "output_end": b + offset,
                         "word_occurrence_ids": [w["occurrence_id"] for w in word_rows]})
            output.append(item)
    return sorted(output, key=lambda row: (row["output_start"], row["output_end"], row["instance_id"]))


def project_semantics(brief: dict, projection: dict) -> dict:
    """Create output-semantic v4; source brief remains immutable and unreordered."""
    _require(isinstance(brief, dict) and type(brief.get("schema_version")) is int
             and brief["schema_version"] in (1, 2, 3), "source semantic schema must be v1-v3")
    events = project_instances(brief.get("events"), projection, id_key="id")
    for event in events:
        event["source_semantic_id"] = event["source_event_id"]
        _require("source_approved_visible_copy" not in event,
                 "source brief cannot carry projected visible-copy metadata")
        if "editorial_copy_policy" in event:
            _require(brief["schema_version"] == 3
                     and event["editorial_copy_policy"] == "source_only"
                     and event.get("decision") == "render",
                     "editorial_copy_policy requires source_only on schema-v3 render event")
            source_copy = event.get("approved_visible_copy")
            _require(isinstance(source_copy, list)
                     and all(isinstance(text, str) and text.strip() for text in source_copy),
                     "source_only requires the original approved visible-copy list")
            event["source_approved_visible_copy"] = copy.deepcopy(source_copy)
            event["approved_visible_copy"] = []
        if "target_binding_ids" in event:
            refs = event["target_binding_ids"]
            _require(isinstance(refs, list), "target binding references must be a list")
            normalized = [_id(ref, "target binding ID") for ref in refs]
            _require(len(normalized) == len(set(normalized)), "duplicate target binding ID")
            _require("source_target_binding_ids" not in event,
                     "source brief cannot carry projected target binding metadata")
            event["source_target_binding_ids"] = copy.deepcopy(refs)
            event["target_binding_ids"] = [f'{ref}@{event["segment_id"]}' for ref in normalized]
    result = copy.deepcopy(brief)
    result.update(schema_version=4, source_schema_version=brief["schema_version"], events=events,
                  timeline="output_instances", projection_mode=projection["mode"],
                  projection_input_hashes=copy.deepcopy(projection["input_hashes"]))
    source_ids = {event["source_semantic_id"] for event in events}

    def map_refs(holder: dict, field: str, segment_id: str | None) -> None:
        refs = holder[field]
        _require(isinstance(refs, list), f"{field} references must be a list")
        normalized = [_id(ref, "proof semantic ID") for ref in refs]
        _require(len(normalized) == len(set(normalized)) and set(normalized) <= source_ids,
                 f"{field} refers to missing or duplicated source semantic ID")
        source_field = f"source_{field}"
        _require(source_field not in holder, "source brief cannot carry projected proof metadata")
        eligible = [event for event in events
                    if segment_id is None or event["segment_id"] == segment_id]
        _require(set(normalized) <= {event["source_semantic_id"] for event in eligible},
                 f"{field} has no exact same-segment instance; cross-segment choice unavailable")
        holder[source_field] = copy.deepcopy(refs)
        holder[field] = [event["id"] for event in eligible
                         if event["source_semantic_id"] in set(normalized)]

    def map_nested(value: Any, segment_id: str | None = None, cover: bool = False) -> None:
        if isinstance(value, dict):
            # Snapshot original children; never recurse into newly added source metadata.
            children = list(value.items())
            for field, child in children:
                if field == "proof_event_ids" or (cover and field == "evidence_event_ids"):
                    map_refs(value, field, segment_id)
                else:
                    map_nested(child, segment_id, cover or field == "cover_direction")
        elif isinstance(value, list):
            for child in value:
                map_nested(child, segment_id, cover)

    # Global proof/cover claims expand to every known output instance in time order.
    # Event-local claims stay in that explicit instance, never guess hook vs body.
    global_fields = {field: value for field, value in result.items() if field != "events"}
    map_nested(global_fields)
    result.update(global_fields)
    for event in events:
        map_nested(event, event["segment_id"])
    result["projection_binding"] = {
        "source_brief": copy.deepcopy(brief), "projection": copy.deepcopy(projection),
        "source_brief_canonical_sha256": _canonical_hash(brief),
        "projection_canonical_sha256": _canonical_hash(projection),
        "hash_scope": "canonical_json_integrity_not_identity_or_current_file_verification",
    }
    return result


def _canonical_hash(value: dict) -> str:
    data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def validate_output_semantics(brief: dict, source_brief: dict | None = None,
                              projection: dict | None = None) -> list[str]:
    """Return v4 derivation errors without weakening source v1-v3 validators.

    Non-file consumers can recompute from embedded detached authorities. The
    Director must also bind those authorities to current files, and the compiler
    must run its unchanged legacy validator against ``source_brief`` (embedded
    or supplied). Canonical hashes prove integrity, not current-file provenance.
    """
    try:
        _finite(brief)
        _require(isinstance(brief, dict) and type(brief.get("schema_version")) is int
                 and brief["schema_version"] == 4, "output semantic schema must be integer v4")
        binding = brief.get("projection_binding")
        _require(isinstance(binding, dict), "v4 source/projection binding missing")
        source = source_brief if source_brief is not None else binding.get("source_brief")
        timeline = projection if projection is not None else binding.get("projection")
        _require(isinstance(source, dict) and isinstance(timeline, dict), "v4 source/projection authorities missing")
        _require(binding.get("source_brief_canonical_sha256") == _canonical_hash(source)
                 and binding.get("projection_canonical_sha256") == _canonical_hash(timeline), "v4 authority hash drift")
        _require(brief == project_semantics(source, timeline), "output semantic v4 differs from exact source projection")
    except (ProjectionError, KeyError, TypeError, ValueError) as exc:
        return [str(exc)]
    return []
