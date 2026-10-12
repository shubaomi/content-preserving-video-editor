"""Record an explicit, exact user hook decision and request a video-use variant.

This local command is a review action, not an identity-authentication service.
Agents may invoke it only after the named human actually approves the exact plan.
It never creates an EDL, starts an editor, renders, or edits the parent project.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path

from director_contracts import write_json
from editorial_projection import build_projection
from motion_editorial import current_ref, digest, load, ref, validate_edl_source


def record_hook_decision(*, parent_root: Path, source: Path, transcript: Path,
                         base_edl: Path, hook_plan: Path, candidate_id: str,
                         operator: str, user_message: str, fps: str) -> Path:
    if not operator.strip() or operator.strip().lower() in {'agent', 'assistant', 'model', 'codex'}:
        raise ValueError('a named human operator is required')
    if not user_message.strip():
        raise ValueError('verbatim explicit user approval is required')
    parent_root = parent_root.resolve()
    for path in (transcript, base_edl, hook_plan):
        if not path.resolve().is_relative_to(parent_root):
            raise ValueError('parent evidence must stay within its authorized project')
    plan = load(hook_plan)
    candidates = plan.get('candidates') or []
    chosen = next((row for row in candidates if row.get('id') == candidate_id), None)
    if plan.get('state') != 'proposed' or chosen is None:
        raise ValueError('exact proposed hook candidate required')
    # Frame references must resolve before a proposal can be approved.
    frame_records = plan.get('frame_evidence') or {}
    for frame_id in chosen.get('frame_refs') or []:
        current_ref(frame_records.get(frame_id), [parent_root])
    bindings = {name: ref(path) for name, path in (
        ('source', source), ('transcript', transcript), ('base_edl', base_edl), ('hook_plan', hook_plan))}
    hashes = {name: value['sha256'] for name, value in bindings.items()}
    decision = {'kind': 'hook_excerpt', 'scope': 'short_preview', 'candidate_id': candidate_id,
                'original_user_message': user_message, 'operator': operator,
                'timestamp': datetime.now(timezone.utc).isoformat(), 'input_hashes': hashes,
                'recorded_by': 'explicit_hook_review_command'}
    # Build only an in-memory validation candidate. video-use alone materializes its EDL.
    import copy
    baseline = load(base_edl)
    validate_edl_source(baseline, source)
    candidate = copy.deepcopy(baseline)
    rows = candidate.get('segments', candidate.get('ranges'))
    if not isinstance(rows, list):
        raise ValueError('video-use ranges required')
    window = chosen['source_range']
    duration = window['end'] - window['start']
    cursor = 0.0
    for row in rows:
        start = row.get('timeline_start', cursor)
        row['timeline_start'] = start + duration
        cursor = start + row['end'] - row['start']
    rows.insert(0, {'source': chosen['source_ref'], 'start': window['start'], 'end': window['end'],
                    'timeline_start': 0, 'role': 'hook'})
    candidate['total_duration_s'] = baseline.get('total_duration_s', cursor) + duration
    build_projection(baseline_edl=baseline, candidate_edl=candidate, transcript=load(transcript),
                     fps=fps, mode='approved_duplicate', input_hashes={**hashes, 'candidate_edl': digest(candidate)},
                     hook_plan=plan, approval=decision, authority=lambda *_: True)
    directory = parent_root / 'work' / 'director' / 'motion-editorial'
    receipt = directory / 'human-decisions' / f'{digest(decision)}.json'
    write_json(receipt, decision)
    request_id = digest({'inputs': hashes, 'candidate_id': candidate_id})
    request = directory / 'variant-requests' / f'{request_id}.json'
    payload = {'schema_version': 1, 'request_id': request_id, 'owner': 'video-use',
               'parent_root': str(parent_root), 'parent_readonly': True, 'inputs': bindings,
               'approval': ref(receipt), 'candidate_id': candidate_id,
               'mode': 'approved_duplicate', 'scope': 'short_preview',
               'target_variant': str(parent_root / 'work' / 'motion-editorial-variants' / request_id[:20]),
               'expected_variant_authority': {'parent_root': str(parent_root),
                   'base_edl': bindings['base_edl'], 'hook_plan': bindings['hook_plan']},
               'expected_edl': 'edit/video-use/edl.json',
               'body_order_ranges_speed_gaps_unchanged': True,
               'one_dispatch_per_request': True, 'full_render_authorized': False}
    if request.is_file():
        old = load(request)
        # Repeated identical requests retain the first exact review, not a second dispatch.
        if {k: v for k, v in old.items() if k != 'approval'} != {k: v for k, v in payload.items() if k != 'approval'}:
            raise ValueError('existing variant request differs; do not overwrite')
        return request
    write_json(request, payload)
    return request


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    for arg in ('parent-root', 'source', 'transcript', 'base-edl', 'hook-plan',
                'candidate-id', 'operator', 'user-message', 'fps'):
        parser.add_argument('--' + arg, required=True)
    args = vars(parser.parse_args())
    for key in ('parent_root', 'source', 'transcript', 'base_edl', 'hook_plan'):
        args[key] = Path(args[key]).resolve()
    print(record_hook_decision(**args))
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
