"""Read-only instance linkage for the existing editable-delivery chain.

This exports JSON, not captions, assets, a renderer, or a native editor draft.
File arguments bind current bytes; inline values bind canonical JSON integrity
only. Neither proves EDL provenance or human approval: the caller must rebuild
the projection from current video-use inputs using its trusted approval gate.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
from typing import Any

from editorial_projection import validate_output_semantics, validate_projection


class HandoffError(ValueError):
    """An output-instance linkage cannot be established without guessing."""


def _require(ok: bool, message: str) -> None:
    if not ok:
        raise HandoffError(message)


def _digest(value: Any) -> str:
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True,
                         separators=(',', ':'), allow_nan=False).encode('utf-8')
    except (ValueError, TypeError) as exc:
        raise HandoffError('input must be finite JSON') from exc
    return hashlib.sha256(raw).hexdigest()


def _pairs(pairs: list) -> dict:
    result = {}
    for key, value in pairs:
        _require(key not in result, f'duplicate JSON key: {key}')
        result[key] = value
    return result


def _load(value: Any) -> tuple[Any, dict]:
    expected = None
    if isinstance(value, dict) and 'path' in value and 'sha256' in value:
        _require(set(value) == {'path', 'sha256'}, 'file reference must contain only path and sha256')
        expected, value = value['sha256'], value['path']
    if isinstance(value, (str, Path)):
        path = Path(value)
        _require(path.is_absolute() and path.is_file(), 'input file must exist at an absolute path')
        _require(path.suffix.lower() == '.json', 'only existing JSON inputs are supported; SRT/ASS stay in editable delivery')
        raw = path.read_bytes()
        sha = hashlib.sha256(raw).hexdigest()
        _require(expected is None or expected == sha, 'input file hash differs from expected current bytes')
        try:
            data = json.loads(raw.decode('utf-8-sig'), object_pairs_hook=_pairs)
        except (UnicodeError, json.JSONDecodeError) as exc:
            raise HandoffError('input is not strict UTF-8 JSON') from exc
        canonical = _digest(data)
        return data, {'path': str(path.resolve()), 'sha256': sha,
                      'canonical_sha256': canonical, 'hash_scope': 'current_file_bytes'}
    detached = deepcopy(value)
    return detached, {'canonical_sha256': _digest(detached),
                      'hash_scope': 'canonical_json_integrity_only'}


def _number(value: Any) -> float:
    _require(type(value) in (int, float) and math.isfinite(value) and value >= 0,
             'time must be finite, nonnegative, and not boolean')
    return float(value)


def _window(start: Any, end: Any) -> tuple[float, float]:
    start, end = _number(start), _number(end)
    _require(start < end, 'window must have positive duration')
    return start, end


def _section(rows: list, unavailable: list | None = None) -> dict:
    unavailable = unavailable or []
    return {'status': ('partial' if rows else 'unavailable') if unavailable else 'linked',
            'rows': rows, 'unavailable': unavailable}


def _unavailable(reason: str) -> dict:
    return _section([], [{'reason': reason}])


def _link(event: dict) -> dict:
    return {'semantic_event_id': event['id'], 'source_semantic_id': event['source_semantic_id'],
            'segment_id': event['segment_id'], 'source_ref': event['source_ref'],
            'semantic_output_window': {'start': event['output_start'], 'end': event['output_end']},
            'word_occurrence_ids': deepcopy(event['word_occurrence_ids'])}


def _event(row: dict, events: dict) -> dict | None:
    instance = row.get('semantic_event_id')
    _require(instance is None or isinstance(instance, str), 'semantic_event_id must be a string')
    if instance in events:
        return events[instance]
    # Unknown explicit output IDs indicate stale/corrupt bindings, not legacy data.
    _require(not isinstance(instance, str) or '@' not in instance,
             'unknown output semantic instance')
    return None


def _captions(data: Any, projection: dict) -> dict:
    if isinstance(data, dict):
        _require(data.get('timeline', 'output') == 'output', 'captions must use output timeline')
        _require(not ('segments' in data and 'captions' in data), 'ambiguous caption row containers')
        rows = data.get('segments', data.get('captions'))
    else:
        rows = data
    _require(isinstance(rows, list) and bool(rows), 'captions require existing nonempty output-timed segments')
    result, unavailable, previous_end = [], [], 0.0
    for index, row in enumerate(rows):
        _require(isinstance(row, dict), 'caption must be an object')
        _require(row.get('timeline', 'output') == 'output', 'caption must use output timeline')
        start, end = _window(row.get('start'), row.get('end'))
        _require(start >= previous_end, 'caption screens overlap or are out of order')
        previous_end = end
        _require(isinstance(row.get('text'), str) and bool(row['text'].strip()), 'caption text is empty')
        segments = [s for s in projection['segments'] if s['output_start'] <= start < end <= s['output_end']]
        _require(len(segments) == 1, 'caption window crosses segment boundary or output gap')
        segment = segments[0]
        _require(row.get('segment_id', segment['segment_id']) == segment['segment_id'],
                 'declared caption segment differs from output window')
        segment_words = [w for w in projection['words'] if w['segment_id'] == segment['segment_id']]
        words = [w for w in segment_words
                 if w['output_start'] < end and w['output_end'] > start]
        temporal_ids = [w['occurrence_id'] for w in words]
        declared = row.get('word_occurrence_ids')
        if declared is not None:
            _require(isinstance(declared, list) and bool(declared)
                     and all(isinstance(value, str) for value in declared)
                     and len(declared) == len(set(declared)), 'caption occurrence IDs must be unique nonempty strings')
            ids = [w['occurrence_id'] for w in segment_words if w['occurrence_id'] in declared]
            _require(ids == declared, 'caption occurrence IDs are unknown, reordered, or belong to another segment')
            words = [w for w in segment_words if w['occurrence_id'] in declared]
            basis = 'video_use_declared_occurrence_ids'
        elif words and all(start <= w['output_start'] < w['output_end'] <= end for w in words):
            ids = [w['occurrence_id'] for w in words]
            basis = 'fully_contained_output_word_times'
        else:
            ids, basis = [], 'unavailable'
            unavailable.append({'row': index, 'reason': 'existing caption has ambiguous or missing word-time linkage; caption text/times preserved'})
        result.append({**deepcopy(row), 'instance_id': f"caption-{index}@{segment['segment_id']}",
                       'segment_id': segment['segment_id'], 'word_occurrence_ids': ids,
                       'word_linkage_basis': basis,
                       'temporal_overlap_occurrence_ids': temporal_ids,
                       'source_word_ids': [w['source_word_id'] for w in words] if ids else []})
    return _section(result, unavailable)


def _audio(data: Any, events: dict) -> dict:
    if not isinstance(data, dict) or not isinstance(data.get('motion_sfx'), dict):
        return _unavailable('unsupported audio-plan shape; no audio transformation attempted')
    rows = data['motion_sfx'].get('event_decisions')
    if not isinstance(rows, list):
        return _unavailable('audio-plan lacks event_decisions')
    linked, unavailable, seen = [], [], set()
    for index, row in enumerate(rows):
        _require(isinstance(row, dict), 'audio decision must be an object')
        event = _event(row, events)
        if event is None:
            unavailable.append({'row': index, 'reason': 'explicit output semantic_event_id required; source-ID fallback disabled'})
            continue
        event_id = row.get('event_id')
        _require(isinstance(event_id, str) and bool(event_id.strip()) and event_id not in seen,
                 'audio event_id must be unique and nonempty')
        seen.add(event_id)
        if 'output_start' in row or 'output_end' in row:
            _require(_window(row.get('output_start'), row.get('output_end')) ==
                     (event['output_start'], event['output_end']),
                     'audio semantic output window differs from exact event window')
        decision = row.get('decision')
        if decision not in {'cue', 'intentionally_silent'}:
            unavailable.append({'row': index, 'reason': 'unsupported audio decision'})
            continue
        if decision == 'cue':
            start, duration = _number(row.get('start')), _number(row.get('duration_seconds'))
            _require(duration > 0 and event['output_start'] <= start < start + duration <= event['output_end'],
                     'audio cue window outside semantic instance window')
        else:
            _require(isinstance(row.get('reason'), str) and bool(row['reason'].strip()),
                     'intentional silence requires a reason')
        linked.append({**deepcopy(row), **_link(event), 'asset_verification': 'delegated_to_audio_production'})
    return _section(linked, unavailable)


def _targets(data: Any, events: dict) -> dict:
    rows = data.get('bindings') if isinstance(data, dict) else data
    if not isinstance(rows, list):
        return _unavailable('unsupported target bindings shape; geometry not transformed')
    linked, unavailable, seen = [], [], set()
    for index, row in enumerate(rows):
        _require(isinstance(row, dict), 'target binding must be an object')
        event = _event(row, events)
        if event is None:
            unavailable.append({'row': index, 'reason': 'explicit output semantic_event_id required; source-ID fallback disabled'})
            continue
        binding_id = row.get('binding_id')
        _require(isinstance(binding_id, str) and bool(binding_id.strip()) and binding_id not in seen,
                 'target binding_id must be unique and nonempty')
        seen.add(binding_id)
        for key, expected in (('source_window', (event['source_start'], event['source_end'])),
                              ('output_window', (event['output_start'], event['output_end']))):
            value = row.get(key)
            _require(isinstance(value, dict), f'target {key} required')
            actual = _window(value.get('start_seconds'), value.get('end_seconds'))
            _require(actual == expected, f'target {key} differs from exact semantic window')
        active = row.get('active_windows', [])
        _require(isinstance(active, list), 'target active_windows must be a list')
        for window in active:
            _require(isinstance(window, dict), 'target active window must be an object')
            start, end = _window(window.get('start_seconds'), window.get('end_seconds'))
            _require(event['output_start'] <= start < end <= event['output_end'], 'target active window outside event')
        linked.append({**deepcopy(row), **_link(event), 'geometry_verification': 'delegated_to_target_binding'})
    return _section(linked, unavailable)


def _promises(data: Any, events: dict) -> dict:
    promise = data.get('single_promise') if isinstance(data, dict) else None
    if not isinstance(promise, dict) or not isinstance(promise.get('proof_event_ids'), list):
        return _unavailable('unsupported promise ledger shape')
    ids = promise['proof_event_ids']
    _require(all(isinstance(i, str) for i in ids) and len(ids) == len(set(ids)), 'promise proof IDs must be unique strings')
    linked, unavailable = [], []
    for index, instance in enumerate(ids):
        event = _event({'semantic_event_id': instance}, events)
        if event is None:
            unavailable.append({'row': index, 'reason': 'proof must reference an explicit output instance; source-ID fallback disabled'})
        else:
            linked.append(_link(event))
    return _section(linked, unavailable)


def build_handoff(projection, output_brief, captions, audio_plan=None,
                  target_bindings=None, promise_ledger=None) -> dict:
    """Build a hash-bound JSON bundle; optional unsupported adapters are explicit.

    Each input accepts inline JSON, an absolute JSON path, or ``{path, sha256}``.
    Output captions are referenced without regrouping, text edits or re-timing.
    Optional audio/target/promise rows require exact *instance* references. This
    validates linkage only; downstream owners retain their existing checks.
    """
    _require(all(value is not None for value in (projection, output_brief, captions)),
             'projection, output brief and existing captions are required')
    values, inputs = {}, {}
    for name, value in (('projection', projection), ('output_brief', output_brief),
                        ('captions', captions), ('audio_plan', audio_plan),
                        ('target_bindings', target_bindings), ('promise_ledger', promise_ledger)):
        if value is not None:
            values[name], inputs[name] = _load(value)
    projection, brief = values['projection'], values['output_brief']
    validate_projection(projection)
    errors = validate_output_semantics(brief, projection=projection)
    _require(not errors, f'output semantic binding invalid: {errors}')
    events = {row['id']: row for row in brief['events']}
    bundle = {'schema_version': 1, 'kind': 'editorial_instance_handoff', 'inputs': inputs,
              'mode': projection['mode'], 'output_duration': projection['output_duration'],
              'fps': deepcopy(projection['fps']), 'segments': deepcopy(projection['segments']),
              'semantic_instances': [_link(row) for row in brief['events']],
              'word_occurrences': deepcopy(projection['words']),
              'captions': _captions(values['captions'], projection),
              'native_editor_verified': False, 'assets_copied': False,
              'caption_files_generated': False, 'full_render_authorized': False,
              'verification_scope': 'output_instance_linkage_only',
              'repair_kit_owner': 'existing_editable_delivery_srt_ass_caption_free_chain'}
    for key, source, adapter in (('audio', 'audio_plan', _audio),
                                  ('targets', 'target_bindings', _targets),
                                  ('promises', 'promise_ledger', _promises)):
        bundle[key] = adapter(values[source], events) if source in values else {'status': 'not_provided', 'rows': [], 'unavailable': []}
    bundle['bundle_sha256'] = _digest(bundle)
    return bundle
