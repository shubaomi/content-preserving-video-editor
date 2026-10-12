"""Create one request-bound hook workspace, never an EDL or render authority.

The current explicit-review ledger is the approval authority; JSON booleans and
style approval cannot substitute for it. Hashes detect drift, not human identity.
Existing initialized workspaces are validated read-only, never repaired in place.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import re

from safe_generated_output import safe_generated_directory
from director_contracts import sha256_file

AUTHORITY_RELATIVE = Path('work/director/motion-editorial/variant-authority.json')
INITIALIZATION_NAME = '.motion-editorial-variant-init.json'


class VariantError(ValueError):
    """A request cannot safely create or resume its isolated workspace."""


def _require(ok, message):
    if not ok:
        raise VariantError(message)


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode('utf-8')).hexdigest()


def _safe_path(value):
    path = Path(value)
    _require(path.is_absolute() and '..' not in path.parts, 'absolute canonical path required')
    for part in (path, *path.parents):
        _require(not part.is_symlink() and not getattr(os.path, 'isjunction', lambda _: False)(part),
                 'variant path or ancestor is redirected')
    _require(path == path.resolve(), 'noncanonical variant path')
    return path


def _load(path):
    def pairs(items):
        result = {}
        for key, value in items:
            _require(key not in result, 'duplicate contract key')
            result[key] = value
        return result
    path = _safe_path(path)
    value = json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=pairs)
    _require(isinstance(value, dict), 'contract must be an object')
    _digest(value)
    return value


def _ref(path):
    path = _safe_path(path)
    return {'path': str(path), 'sha256': sha256_file(path)}


def _current(record, parent=None):
    _require(isinstance(record, dict) and set(record) == {'path', 'sha256'}, 'current file reference required')
    path = _safe_path(record['path'])
    _require(parent is None or path.is_relative_to(parent), 'evidence leaves authorized parent')
    _require(path.is_file() and _ref(path) == record, 'file reference missing or hash stale')
    return path


def _request(request_path):
    """Revalidate the exact command-emitted request and its current human ledger."""
    request_path = _safe_path(request_path)
    request = _load(request_path)
    parent = _safe_path(request.get('parent_root', ''))
    _require(parent.is_dir(), 'parent project is missing')
    request_id = request.get('request_id')
    _require(isinstance(request_id, str) and re.fullmatch('[a-f0-9]{64}', request_id), 'invalid request id')
    expected_path = parent/'work'/'director'/'motion-editorial'/'variant-requests'/f'{request_id}.json'
    _require(request_path == expected_path, 'request must occupy its canonical parent ledger path')
    inputs = request.get('inputs')
    _require(isinstance(inputs, dict) and set(inputs) == {'source', 'transcript', 'base_edl', 'hook_plan'},
             'request requires exact source/transcript/base EDL/hook-plan inputs')
    dependencies = [request_path]
    paths = {}
    for name, value in inputs.items():
        paths[name] = _current(value, None if name == 'source' else parent)
        dependencies.append(paths[name])
    hashes = {name: value['sha256'] for name, value in inputs.items()}
    _require(request_id == _digest({'inputs': hashes, 'candidate_id': request.get('candidate_id')}),
             'request id does not bind exact inputs and hook candidate')
    approval_path = _current(request.get('approval'), parent)
    decision = _load(approval_path)
    expected_approval = parent/'work'/'director'/'motion-editorial'/'human-decisions'/f'{_digest(decision)}.json'
    _require(approval_path == expected_approval, 'approval is not the canonical explicit-decision ledger receipt')
    _require(decision.get('kind') == 'hook_excerpt' and decision.get('scope') == 'short_preview'
             and decision.get('recorded_by') == 'explicit_hook_review_command'
             and decision.get('candidate_id') == request.get('candidate_id')
             and decision.get('input_hashes') == hashes, 'exact current hook approval required')
    operator, message = decision.get('operator'), decision.get('original_user_message')
    _require(isinstance(operator, str) and operator.strip()
             and operator.strip().lower() not in {'agent', 'assistant', 'model', 'codex'}, 'named human approval required')
    _require(isinstance(message, str) and message.strip() and isinstance(decision.get('timestamp'), str)
             and decision['timestamp'].strip(), 'verbatim user decision and timestamp required')
    dependencies.append(approval_path)
    target = parent/'work'/'motion-editorial-variants'/request_id[:20]
    expected = {'schema_version': 1, 'request_id': request_id, 'owner': 'video-use',
                'parent_root': str(parent), 'parent_readonly': True, 'inputs': inputs,
                'approval': request['approval'], 'candidate_id': request['candidate_id'],
                'mode': 'approved_duplicate', 'scope': 'short_preview', 'target_variant': str(target),
                'expected_variant_authority': {'parent_root': str(parent),
                                              'base_edl': inputs['base_edl'], 'hook_plan': inputs['hook_plan']},
                'expected_edl': 'edit/video-use/edl.json', 'body_order_ranges_speed_gaps_unchanged': True,
                'one_dispatch_per_request': True, 'full_render_authorized': False}
    _require(request == expected, 'request differs from the closed canonical variant contract')
    plan = _load(paths['hook_plan'])
    chosen = [row for row in plan.get('candidates', []) if isinstance(row, dict) and row.get('id') == request['candidate_id']]
    _require(plan.get('state') == 'proposed' and len(chosen) == 1, 'current exact proposed hook candidate required')
    frame_ids = chosen[0].get('frame_refs')
    _require(isinstance(frame_ids, list) and bool(frame_ids) and all(isinstance(x, str) for x in frame_ids)
             and len(frame_ids) == len(set(frame_ids)), 'unique current frame evidence required')
    frame_records = plan.get('frame_evidence') or {}
    _require(isinstance(frame_records, dict), 'frame reference table required')
    dependencies.extend(_current(frame_records.get(frame_id), parent) for frame_id in frame_ids)
    _safe_path(target)
    return request, target, dependencies


def _initialization(request_path, request, target):
    return {'schema_version': 1, 'kind': 'motion_editorial_variant_initialization',
            'initialized_by': 'motion_editorial_variant.initialize_variant',
            'request_ref': _ref(request_path), 'request_id': request['request_id'],
            'parent_root': request['parent_root'], 'target_root': str(target),
            'parent_readonly': True, 'edl_created': False, 'full_render_authorized': False}


def _authority(request_path, request, target):
    return {'schema_version': 1, 'kind': 'motion_editorial_variant_authority',
            'parent_root': request['parent_root'], 'request_ref': _ref(request_path),
            'initialization_ref': _ref(target/INITIALIZATION_NAME),
            **deepcopy(request['inputs']), 'approval': deepcopy(request['approval']),
            'mode': 'approved_duplicate', 'scope': 'short_preview', 'full_render_authorized': False}


def validate_variant(root: Path, authority: dict) -> list[Path]:
    """Validate an initialized root without writing; return current dependencies."""
    try:
        root = _safe_path(root)
        _require(root.is_dir() and isinstance(authority, dict), 'initialized variant directory required')
        request_path = _current(authority.get('request_ref'))
        request, target, dependencies = _request(request_path)
        _require(root == target, 'variant root differs from canonical request target')
        initialization_path = root/INITIALIZATION_NAME
        _require(_load(initialization_path) == _initialization(request_path, request, root),
                 'variant initialization receipt is missing or differs')
        expected = _authority(request_path, request, root)
        authority_path = root/AUTHORITY_RELATIVE
        _require(authority == expected and _load(authority_path) == expected,
                 'variant authority differs from initialized request')
        return list(dict.fromkeys([*dependencies, initialization_path, authority_path]))
    except (OSError, ValueError, KeyError, TypeError) as error:
        if isinstance(error, VariantError):
            raise
        raise VariantError(f'variant validation failed: {error}') from error


def _create_json(path, value):
    """Exclusive creation only; a failed partial workspace is preserved for review."""
    _safe_path(path)
    with path.open('x', encoding='utf-8', newline='\n') as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write('\n')
        handle.flush()
        os.fsync(handle.fileno())


def initialize_variant(request_path: Path) -> Path:
    """Create only the canonical new target, or verify the same request read-only.

    A partial/foreign directory is never overwritten, removed, or adopted. This
    creates no project config, EDL, media, render, or human approval receipt.
    """
    try:
        request_path = _safe_path(request_path)
        request, target, _ = _request(request_path)
        if target.exists():
            validate_variant(target, _load(target/AUTHORITY_RELATIVE))
            return target
        parent = Path(request['parent_root'])
        safe_generated_directory(parent, Path('work/motion-editorial-variants'))
        _safe_path(target)
        target.mkdir(exist_ok=False)
        _safe_path(target)
        _create_json(target/INITIALIZATION_NAME, _initialization(request_path, request, target))
        directory = safe_generated_directory(target, AUTHORITY_RELATIVE.parent)
        _create_json(directory/AUTHORITY_RELATIVE.name, _authority(request_path, request, target))
        validate_variant(target, _load(target/AUTHORITY_RELATIVE))
        return target
    except (OSError, ValueError, KeyError, TypeError) as error:
        if isinstance(error, VariantError):
            raise
        raise VariantError(f'variant initialization failed: {error}') from error
