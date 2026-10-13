"""Hash-bound, owner-authored caption screens without inventing word timing."""
from __future__ import annotations

import copy
import hashlib
import json
import math
import re

from build_word_aligned_captions import _join


def words_hash(words: list[dict]) -> str:
    data = json.dumps(words, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def token_ids(word: dict) -> list[str]:
    values = word.get("word_occurrence_ids")
    if values is None:
        value = word.get("word_occurrence_id")
        if value is None:
            value = f"{word['source']}:{word['source_word_id']}:{word['start']:.6f}:{word['end']:.6f}"
        values = [value]
    if not isinstance(values, list) or not values or any(not isinstance(v, str) or not v for v in values):
        raise ValueError("invalid caption word occurrence identities")
    return values


def _keys(value, expected: set[str], label: str) -> None:
    if not isinstance(value, dict) or set(value) != expected:
        raise ValueError(f"{label}: missing or unknown fields")


def _text(value, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{label} must be nonempty text")
    return value


def _binding(document: dict, inputs: dict, *, corrections: bool) -> None:
    expected = {k: inputs[k] for k in ("edl", "transcripts")}
    if corrections:
        expected["corrections"] = inputs.get("corrections")
    if document.get("input_hashes") != expected:
        raise ValueError("caption input hashes are stale or incomplete")
    hashes = [expected["edl"], *expected["transcripts"].values()]
    if corrections and expected["corrections"] is not None:
        hashes.append(expected["corrections"])
    if not expected["transcripts"] or any(not isinstance(h, str) or not re.fullmatch(r"[a-f0-9]{64}", h) for h in hashes):
        raise ValueError("caption input hashes must be SHA-256")


def _word_order(words: list[dict]) -> list[str]:
    result = []
    previous_end = -1.0
    for word in words:
        start, end = word.get("start"), word.get("end")
        if any(type(v) not in (int, float) or not math.isfinite(v) for v in (start, end)):
            raise ValueError("caption word time must be finite")
        if start < previous_end - 1e-6 or end <= start or start < 0:
            raise ValueError("caption word timing overlaps or is invalid")
        previous_end = end
        result.extend(token_ids(word))
    if len(set(result)) != len(result):
        raise ValueError("duplicate caption occurrence identity")
    return result


def apply_span_corrections(words: list[dict], document: dict, input_hashes: dict) -> tuple[list[dict], list[dict]]:
    """Replace a reviewed span as ONE token, retaining its real first/last times."""
    _keys(document, {"schema_version", "kind", "owner", "input_hashes", "replacements"}, "corrections")
    if document["schema_version"] != 2 or document["kind"] != "word_span_corrections" or document["owner"] != "video-use":
        raise ValueError("unsupported word-span correction contract")
    _binding(document, input_hashes, corrections=False)
    _word_order(words)
    if not isinstance(document["replacements"], list):
        raise ValueError("replacements must be an array")
    spans = []
    covered = set()
    for row in document["replacements"]:
        _keys(row, {"word_occurrence_ids", "from", "to", "evidence"}, "replacement")
        ids = row["word_occurrence_ids"]
        if not isinstance(ids, list) or not ids or any(not isinstance(v, str) for v in ids):
            raise ValueError("replacement requires word occurrence IDs")
        for name in ("from", "to", "evidence"):
            _text(row[name], name)
        if any(c in row["to"] for c in "\r\n"):
            raise ValueError("replacement may not introduce caption line breaks")
        matches = [i for i, word in enumerate(words) if token_ids(word)[0] == ids[0]]
        if len(matches) != 1:
            raise ValueError("replacement occurrence not found uniquely")
        begin = matches[0]
        end, found = begin, []
        while end < len(words) and len(found) < len(ids):
            found.extend(token_ids(words[end]))
            end += 1
        if found != ids or covered.intersection(ids):
            raise ValueError("replacement must be contiguous, unique, and token-complete")
        retained = words[begin:end]
        if len({(w.get("segment_id"), w.get("source")) for w in retained}) != 1:
            raise ValueError("replacement crosses EDL segment")
        if _join(retained) != row["from"]:
            raise ValueError("replacement original text guard failed")
        covered.update(ids)
        spans.append((begin, end, row))
    by_start = {begin: (end, row) for begin, end, row in spans}
    output, applied, index = [], [], 0
    while index < len(words):
        if index not in by_start:
            output.append(copy.deepcopy(words[index]))
            index += 1
            continue
        end, row = by_start[index]
        retained = words[index:end]
        token = copy.deepcopy(retained[0])
        token.update(text=row["to"], end=retained[-1]["end"],
                     source_end=retained[-1].get("source_end", retained[-1]["end"]),
                     word_occurrence_ids=list(row["word_occurrence_ids"]),
                     source_word_ids=[v for w in retained for v in w.get("source_word_ids", [w["source_word_id"]])],
                     source_word_count=sum(w.get("source_word_count", 1) for w in retained))
        output.append(token)
        applied.append({**copy.deepcopy(row), "start": token["start"], "end": token["end"],
                        "timing_policy": "retain_original_span_no_interpolation"})
        index = end
    return output, applied


def build_grouped_captions(words: list[dict], document: dict, *, raw_words: list[dict],
                           input_hashes: dict, max_chars: int = 24, max_duration: float = 6.5,
                           punctuation_style: str = "spoken_clean") -> list[dict]:
    from video_use_bridge import _display_caption_text, _visible_chars

    _keys(document, {"schema_version", "kind", "owner", "input_hashes", "mapped_words_sha256", "groups"}, "caption groups")
    if document["schema_version"] != 1 or document["kind"] != "semantic_caption_groups" or document["owner"] != "video-use":
        raise ValueError("unsupported semantic caption grouping contract")
    _binding(document, input_hashes, corrections=True)
    if document["mapped_words_sha256"] != words_hash(raw_words):
        raise ValueError("mapped word hash is stale")
    original_ids = _word_order(raw_words)
    if _word_order(words) != original_ids:
        raise ValueError("corrected words lost/reordered source occurrence IDs")
    if not isinstance(document["groups"], list) or not document["groups"]:
        raise ValueError("semantic groups must be a nonempty array")
    all_ids, screen_ids = [], set()
    captions, cursor = [], 0
    closed_semantics, current_semantic = set(), None
    for row in document["groups"]:
        _keys(row, {"id", "semantic_group_id", "word_occurrence_ids", "rationale"}, "caption screen")
        for field in ("id", "semantic_group_id", "rationale"):
            _text(row[field], field)
        if row["semantic_group_id"] != current_semantic:
            if row["semantic_group_id"] in closed_semantics:
                raise ValueError("semantic group screens must be consecutive")
            if current_semantic is not None:
                closed_semantics.add(current_semantic)
            current_semantic = row["semantic_group_id"]
        if row["id"] in screen_ids:
            raise ValueError("duplicate screen id")
        screen_ids.add(row["id"])
        ids = row["word_occurrence_ids"]
        if not isinstance(ids, list) or not ids or any(not isinstance(v, str) for v in ids):
            raise ValueError("caption screen requires word occurrence IDs")
        start, found = cursor, []
        while cursor < len(words) and len(found) < len(ids):
            found.extend(token_ids(words[cursor]))
            cursor += 1
        if found != ids:
            raise ValueError("caption screen loses/reorders words or splits a correction span")
        selected = words[start:cursor]
        if len({(w.get("segment_id"), w.get("source")) for w in selected}) != 1:
            raise ValueError("caption screen crosses an EDL segment")
        text = _display_caption_text(_join(selected), punctuation_style)
        if not text or _visible_chars(text) > max_chars:
            raise ValueError(f"caption screen {row['id']} exceeds max_chars or is empty; owner must split semantically")
        if selected[-1]["end"] - selected[0]["start"] > max_duration + 1e-6:
            raise ValueError(f"caption screen {row['id']} exceeds max_duration; owner must split semantically")
        all_ids.extend(ids)
        captions.append(dict(start=round(selected[0]["start"], 3), end=round(selected[-1]["end"], 3),
                             text=text, timeline="output", alignment="word_timestamp", mapping_owner="video-use",
                             source_word_start=start, source_word_end=cursor - 1,
                             source_word_ids=[v for w in selected for v in w.get("source_word_ids", [w["source_word_id"]])],
                             word_occurrence_ids=list(ids), semantic_group_id=row["semantic_group_id"],
                             caption_group_id=row["id"], **({"segment_id": selected[0]["segment_id"]} if "segment_id" in selected[0] else {})))
    if cursor != len(words) or all_ids != original_ids:
        raise ValueError("caption groups must cover every retained word once in order")
    return captions
