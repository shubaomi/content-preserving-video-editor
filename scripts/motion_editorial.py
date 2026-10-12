"""Opt-in motion editorial integration; EDL and human decisions remain authorities.

The shipped design receipt records a real conversation approval, not a cryptographic
identity. Hook approval is a separate local explicit-review command, never a plan flag.
"""
from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import math
from pathlib import Path
import shutil
from typing import Any

from director_contracts import sha256_file, write_json

ROOT = Path(__file__).resolve().parents[1]
DESIGN_APPROVAL_SHA256 = '1ef14b6444c37bc89e5f7289c7c965c587fdf3916ccd437eaf2d0de094024429'
DIRECTIONS = {'authentic_product_editorial': 'authentic-product-editorial.js',
              'professional_software_demo': 'professional-software-demo.js'}
RECIPES = {'authentic_product_editorial': ('A01', 'A02', 'A03'),
           'professional_software_demo': ('B01', 'B02', 'B03')}


def digest(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def load(path: Path) -> dict:
    def pairs(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError(f'duplicate JSON key: {key}')
            result[key] = value
        return result
    def invalid(value):
        raise ValueError(f'non-finite JSON: {value}')
    value = json.loads(path.read_text(encoding='utf-8-sig'), object_pairs_hook=pairs,
                       parse_constant=invalid)
    if not isinstance(value, dict):
        raise ValueError('contract must be a JSON object')
    return value


def ref(path: Path) -> dict:
    return {'path': str(path.resolve()), 'sha256': sha256_file(path)}


def current_ref(value: dict, roots: list[Path]) -> Path:
    if not isinstance(value, dict) or set(value) != {'path', 'sha256'}:
        raise ValueError('file reference must be exactly path and sha256')
    raw = Path(str(value['path']))
    path = raw.resolve()
    if not raw.is_absolute() or not any(path.is_relative_to(root.resolve()) for root in roots):
        raise ValueError('file reference escapes authorized roots')
    if not path.is_file() or value['sha256'] != sha256_file(path):
        raise ValueError('file reference is missing or stale')
    return path


def validate_design_approval(path: Path, direction: str) -> dict:
    if direction not in DIRECTIONS or not path.is_file() or sha256_file(path) != DESIGN_APPROVAL_SHA256:
        raise ValueError('current approved design receipt required; booleans cannot authorize a style')
    receipt = load(path)
    if direction not in {row['direction'] for row in receipt['accepted_styles']}:
        raise ValueError('direction is not covered by approved design')
    return receipt


def validate_sample_purpose(purpose: str, output_start: float, mode: str) -> None:
    if purpose not in {'motion_style', 'opening_edit', 'delivery_sample'}:
        raise ValueError('unknown sample purpose')
    if isinstance(output_start, bool) or not math.isfinite(output_start) or output_start < 0:
        raise ValueError('invalid sample start')
    if purpose == 'opening_edit' and (mode != 'approved_duplicate' or output_start != 0):
        raise ValueError('opening_edit requires approved_duplicate at output zero')


def validate_sample_window(validation: dict, projection: dict, storyboard: dict,
                           observed_duration: float) -> None:
    """Bind sample intent to the composition's EDL-output window and measured media."""
    validate_sample_purpose(validation['purpose'], validation['output_start'], projection['mode'])
    composition = storyboard.get('composition') or {}
    if composition.get('timeline_basis') != 'edl_output':
        raise ValueError('editorial sample composition must explicitly use edl_output time')
    start, end = composition.get('source_start'), composition.get('source_end')
    values = (start, end, observed_duration)
    if any(isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v) for v in values):
        raise ValueError('finite measured sample window is required')
    if not 0 <= start < end <= projection['output_duration'] or validation['output_start'] != start:
        raise ValueError('declared sample start differs from actual composition window')
    duration = end - start
    limits = {'motion_style': (10, 15), 'opening_edit': (45, 60), 'delivery_sample': (45, 90)}
    lower, upper = limits[validation['purpose']]
    if not lower <= duration <= upper:
        raise ValueError('sample window exceeds purpose duration bounds')
    frame = projection['fps']['denominator'] / projection['fps']['numerator']
    if abs(observed_duration - duration) > frame + 0.001:
        raise ValueError('measured sample media duration differs from composition')


def config_invalidation_stage(previous: dict, current: dict) -> str:
    """Narrow only understood changes; unknown changes keep conservative inspect."""
    before, after = deepcopy(previous), deepcopy(current)
    old_me, new_me = before.pop('motion_editorial', {}), after.pop('motion_editorial', {})
    old_edit, new_edit = before.get('editing', {}), after.get('editing', {})
    captions_changed = old_edit.get('caption_treatment') != new_edit.get('caption_treatment')
    old_edit.pop('caption_treatment', None)
    new_edit.pop('caption_treatment', None)
    if before != after:
        return 'inspect'
    if old_me != new_me:
        if any(old_me.get(k) != new_me.get(k) for k in ('opening', 'hook_approval_path')):
            return 'video_use_timeline'
        return 'production_contract'
    return 'sample_qa' if captions_changed else 'inspect'


def refresh_unchanged_governance(directory: Path, config: dict, old_hash: str,
                                 new_hash: str) -> list[Path]:
    """Rebind an unchanged policy, retaining every reservation and cost receipt."""
    from provider_governance import build_decision_report, validate_cost_ledger, validate_decision_report
    decision_path, ledger_path = directory / 'provider-decision.json', directory / 'cost-ledger.json'
    decision, ledger = load(decision_path), load(ledger_path)
    if (ledger.get('config') != config or validate_decision_report(decision, config, old_hash)
            or validate_cost_ledger(ledger, old_hash)):
        raise ValueError('prior governance is stale; cannot rebind or reset recorded costs')
    before = {'decision': ref(decision_path), 'ledger': ref(ledger_path)}
    snapshot = directory / 'motion-editorial' / 'governance-history' / f'{old_hash}.json'
    archived = {'decision': decision, 'ledger': ledger}
    if snapshot.is_file() and load(snapshot) != archived:
        raise ValueError('governance history collision; preserving existing evidence')
    write_json(snapshot, archived)
    new_decision = build_decision_report(config=config, project_hash=new_hash)
    updated = deepcopy(ledger)
    updated['project_sha256'] = new_hash
    for row in updated.get('reservations', []):
        row['decision_integrity_sha256'] = new_decision['integrity_sha256']
    updated['integrity_sha256'] = digest({k: v for k, v in updated.items() if k != 'integrity_sha256'})
    errors = validate_cost_ledger(updated, new_hash)
    if errors:
        raise ValueError('governance rebind failed: ' + '; '.join(errors))
    write_json(decision_path, new_decision)
    write_json(ledger_path, updated)
    receipt = directory / 'motion-editorial' / 'governance-history' / f'{new_hash}-rebind.json'
    write_json(receipt, {'schema_version': 1, 'reason': 'unchanged provider policy; editorial configuration only',
                        'before': before, 'snapshot': ref(snapshot), 'after': {
                            'decision': ref(decision_path), 'ledger': ref(ledger_path)},
                        'reservation_count': len(updated.get('reservations', [])),
                        'totals_preserved': updated['totals'] == ledger['totals']})
    return [decision_path, ledger_path, snapshot, receipt]


def validate_edl_source(edl: dict, source: Path) -> None:
    sources = edl.get('sources')
    rows = edl.get('segments', edl.get('ranges', []))
    keys = {str(row.get('source', edl.get('source', ''))) for row in rows}
    if not isinstance(sources, dict) or len(keys) != 1 or keys != set(sources):
        raise ValueError('motion editorial requires one explicitly bound video-use source')
    mapped_source = Path(str(sources[next(iter(keys))]))
    if not mapped_source.is_absolute() or mapped_source.resolve() != source.resolve():
        raise ValueError('EDL source file differs from the current authorized source')


def prepare_projection(*, project: dict, root: Path, source: Path, transcript: Path,
                       edl: Path, fps: str, director_root: Path | None = None) -> tuple[dict | None, list[Path]]:
    config = project.get('motion_editorial') or {}
    if not config.get('enabled'):
        return None, []
    from editorial_projection import build_projection
    approval_path = Path(config['design_approval_path'])
    if not approval_path.is_absolute():
        approval_path = root / approval_path
    validate_design_approval(approval_path, config['direction'])
    directory = (director_root or root / 'work' / 'director') / 'motion-editorial'
    current_edl = load(edl)
    validate_edl_source(current_edl, source)
    inputs = {'source': sha256_file(source), 'transcript': sha256_file(transcript),
              'base_edl': sha256_file(edl), 'candidate_edl': sha256_file(edl)}
    dependencies = [source, transcript, edl, approval_path]
    kwargs = {}
    baseline = current_edl
    mode = 'preserve_order'
    if config['opening'] == 'approved_duplicate':
        mode = 'approved_duplicate'
        variant = load(directory / 'variant-authority.json')
        from motion_editorial_variant import validate_variant
        dependencies.extend(validate_variant(root, variant))
        if variant.get('source') != ref(source) or variant.get('transcript', {}).get('sha256') != sha256_file(transcript):
            raise ValueError('variant source/transcript differs from exact approved request')
        # Only a project-local isolated variant may adopt a duplicated EDL.
        parent = Path(variant['parent_root']).resolve()
        if parent == root.resolve() or root.resolve().is_relative_to(parent / 'edit'):
            raise ValueError('hook variant must not replace or nest inside parent edit outputs')
        base_path = current_ref(variant['base_edl'], [parent])
        plan_path = current_ref(variant['hook_plan'], [parent])
        hook_path = Path(config['hook_approval_path'])
        if not hook_path.is_absolute():
            hook_path = root / hook_path
        if variant.get('approval') != ref(hook_path):
            raise ValueError('variant hook approval differs from exact initialized request')
        receipt = load(hook_path)
        ledger_path = parent / 'work' / 'director' / 'motion-editorial' / 'human-decisions' / f"{digest(receipt)}.json"
        def authority(candidate, context):
            return (ledger_path.is_file() and load(ledger_path) == candidate
                    and candidate.get('recorded_by') == 'explicit_hook_review_command'
                    and bool(candidate.get('original_user_message', '').strip())
                    and candidate.get('scope') == 'short_preview')
        kwargs = {'hook_plan': load(plan_path), 'approval': receipt, 'authority': authority}
        inputs.update(base_edl=sha256_file(base_path), hook_plan=sha256_file(plan_path))
        baseline = load(base_path)
        validate_edl_source(baseline, source)
        chosen = next((row for row in kwargs['hook_plan'].get('candidates', [])
                       if row.get('id') == receipt.get('candidate_id')), {})
        for frame_id in chosen.get('frame_refs', []):
            dependencies.append(current_ref(kwargs['hook_plan'].get('frame_evidence', {}).get(frame_id), [parent]))
        dependencies += [directory / 'variant-authority.json', base_path, plan_path, hook_path, ledger_path]
    projection = build_projection(baseline_edl=baseline, candidate_edl=current_edl,
                                  transcript=load(transcript), fps=fps, mode=mode,
                                  input_hashes=inputs, **kwargs)
    output = directory / 'timeline-projection.json'
    write_json(output, projection)
    return projection, [output, *dependencies]


def materialize_components(project_dir: Path, direction: str) -> list[Path]:
    filename = DIRECTIONS[direction]
    source = ROOT / 'assets' / 'motion-editorial-v3' / filename
    destination = project_dir / 'motion-editorial-v3' / filename
    destination.parent.mkdir(parents=True, exist_ok=True)
    if not destination.is_file() or sha256_file(destination) != sha256_file(source):
        shutil.copyfile(source, destination)
    return [source, destination]


def validate_recipe_event(event: dict) -> None:
    """Match the reusable component preconditions before any renderer handoff."""
    def need(ok, message):
        if not ok:
            raise ValueError(message)
    def number(value):
        return not isinstance(value, bool) and isinstance(value, (int, float)) and math.isfinite(value)
    def box(value):
        return (isinstance(value, dict) and set(value) == {'x', 'y', 'width', 'height'}
                and all(number(v) for v in value.values()) and value['x'] >= 0 and value['y'] >= 0
                and value['width'] > 0 and value['height'] > 0)
    recipe, crop, evidence, phases = event['recipe_id'], event['source_crop'], event['evidence'], event['phases']
    copy = event['approved_visible_copy']
    need(isinstance(copy, list) and all(isinstance(t, str) and t.strip() and not any(c in t for c in '<>\r\n') for t in copy)
         and len(copy) == len(set(copy)), 'copy must be unique single-line literal text')
    overlay = event.get('overlay_box')
    need(overlay is None or box(overlay), 'overlay box must use finite output pixels')
    if crop is not None:
        need(abs(crop['width'] - crop['height']) < 1e-9 and box(event.get('source_box')),
             'crop must be uniform and have measured source placement')
    if recipe.startswith('B'):
        need(isinstance(evidence.get('frame_refs'), list) and bool(evidence['frame_refs']), 'B recipe requires source frame refs')
    if recipe == 'A01':
        need(crop is not None and not copy and overlay is None, 'A01 requires only real source camera movement')
    elif recipe == 'A02':
        target = evidence.get('target_window') or {}
        need(crop is None and box(overlay) and len(copy) == 1, 'A02 requires one anchored label')
        need(isinstance(evidence.get('target_binding_ref'), str) and bool(evidence['target_binding_ref']), 'A02 requires target binding')
        need(number(target.get('start')) and number(target.get('end'))
             and target['start'] <= event['output_start'] < event['output_end'] <= target['end'], 'A02 target window does not cover event')
    elif recipe == 'A03':
        need(crop is None and box(overlay) and len(copy) == 2, 'A03 requires two real sequential state labels')
        before, after = evidence.get('before_state_ref'), evidence.get('after_state_ref')
        need(isinstance(before, dict) and isinstance(after, dict) and before.get('sha256') != after.get('sha256'), 'A03 needs distinct real state refs')
        at = evidence.get('after_at')
        need(number(at) and phases['explain']['start'] <= at < phases['exit']['start'], 'A03 state handoff outside explanation')
    elif recipe == 'B01':
        need((crop is not None or box(overlay)) and len(copy) <= 1 and (not copy or box(overlay)), 'B01 needs a real locator or camera focus')
    elif recipe == 'B02':
        steps = event.get('steps')
        need(crop is None and isinstance(steps, list) and len(steps) >= 2, 'B02 requires explicit progressive steps')
        previous = phases['entrance']['start']
        for step in steps:
            need(isinstance(step, dict) and set(step) == {'start', 'end', 'copy', 'overlay_box', 'frame_ref'}, 'invalid B02 step fields')
            need(number(step['start']) and number(step['end']) and previous <= step['start'] < step['end'] <= phases['exit']['end'], 'B02 steps overlap or leave event')
            need(box(step['overlay_box']), 'B02 requires step geometry')
            previous = step['end']
        need([s['copy'] for s in steps] == copy, 'B02 step copy differs from semantic copy')
    elif recipe == 'B03':
        states = evidence.get('states')
        need(crop is None and box(overlay) and event.get('comparison_mode') == 'sequential_source', 'B03 only supports explicit sequential-source fallback')
        need(isinstance(states, list) and len(states) == 2, 'B03 requires two real states')
        need(all(isinstance(s, dict) and number(s.get('source_time')) and s['source_time'] >= 0 and isinstance(s.get('frame_ref'), dict) for s in states), 'B03 state is invalid')
        need(states[0]['source_time'] < states[1]['source_time'] and states[0]['frame_ref'].get('sha256') != states[1]['frame_ref'].get('sha256'), 'B03 states must be different and ordered')
        need([s.get('label') for s in states] == copy, 'B03 state labels differ from semantics')
        at = event.get('after_at')
        need(number(at) and phases['entrance']['end'] < at < phases['exit']['start'], 'B03 state handoff outside event')


def compile_shot_plan(plan: dict, *, projection: dict, output_brief: dict,
                      direction: str, roots: list[Path], source_media: dict | None = None,
                      target_bindings: dict | None = None) -> dict:
    """Compile authored shots, never select motion from keywords or quotas."""
    allowed = {'schema_version', 'kind', 'direction', 'projection_sha256',
               'semantic_sha256', 'events', 'default_decorations'}
    if set(plan) != allowed or plan['schema_version'] != 2 or plan['kind'] != 'shot_motion_plan':
        raise ValueError('shot plan requires the closed runtime schema v2')
    if plan['direction'] != direction or plan['default_decorations'] is not False:
        raise ValueError('shot direction differs or default decorations were enabled')
    if plan['projection_sha256'] != digest(projection) or plan['semantic_sha256'] != digest(output_brief):
        raise ValueError('shot plan projection/semantic hash is stale')
    semantics = {row['id']: row for row in output_brief['events']}
    if not isinstance(plan['events'], list) or [r.get('instance_id') for r in plan['events']] != list(semantics):
        raise ValueError('shot decisions must exactly cover ordered semantic instances')
    compiled = []
    dependencies = []
    for event in plan['events']:
        semantic = semantics[event['instance_id']]
        required = {'instance_id', 'decision', 'recipe_id', 'viewer_task', 'information_gain',
                    'primary_focus', 'rationale', 'source_crop', 'approved_visible_copy',
                    'phases', 'evidence', 'sound', 'output_start', 'output_end'}
        optional = {'source_box', 'overlay_box', 'active_end', 'target_window', 'after_at',
                    'comparison_mode', 'steps', 'target_binding_ids'}
        if required - set(event) or set(event) - required - optional:
            raise ValueError('shot event fields are incomplete or unsupported')
        for field in ('viewer_task', 'information_gain', 'primary_focus', 'rationale'):
            if not isinstance(event[field], str) or not event[field].strip():
                raise ValueError(f'shot event requires {field}')
        for field in ('output_start', 'output_end'):
            if event[field] != semantic[field]:
                raise ValueError('shot timing must equal projected semantic instance')
        if event['approved_visible_copy'] != semantic.get('approved_visible_copy', []):
            raise ValueError('shot visible copy must exactly match approved semantics')
        evidence = event['evidence']
        if not isinstance(evidence, dict) or not evidence:
            raise ValueError('shot requires current evidence')
        def check_refs(value):
            if isinstance(value, dict):
                if 'path' in value or 'sha256' in value:
                    dependencies.append(str(current_ref(value, roots)))
                else:
                    for child in value.values():
                        check_refs(child)
            elif isinstance(value, list):
                for child in value:
                    check_refs(child)
        before_refs = len(dependencies)
        check_refs(evidence)
        if len(dependencies) == before_refs:
            raise ValueError('shot evidence requires file references')
        check_refs(event.get('steps', []))
        allowed_frames = {str(Path(value['path'] if isinstance(value, dict) else value).resolve())
                          for value in semantic.get('target_frame_evidence', [])}
        if not allowed_frames or any(path not in allowed_frames for path in dependencies[before_refs:]):
            raise ValueError('shot evidence must belong to the current semantic instance frames')
        sound = event['sound']
        if not isinstance(sound, dict) or sound.get('decision') not in {'cue', 'intentionally_silent'}:
            raise ValueError('shot sound decision required')
        if sound['decision'] == 'intentionally_silent' and not str(sound.get('reason') or '').strip():
            raise ValueError('intentional silence requires a reason')
        if sound['decision'] == 'cue':
            dependencies.append(str(current_ref(sound.get('asset_ref'), roots)))
        selected = semantic.get('decision') == 'render'
        if selected != (event['decision'] in {'shot', 'overlay'}):
            raise ValueError('shot render decisions must equal semantic render subset')
        if not selected:
            if event['decision'] not in {'source', 'quiet', 'caption_only'} or event['recipe_id'] is not None or event['source_crop'] is not None or event['phases']:
                raise ValueError('non-render decisions cannot carry crop/recipe/phases')
            continue
        if event['recipe_id'] not in RECIPES[direction]:
            raise ValueError('recipe does not belong to direction')
        if semantic.get('editorial_copy_policy') == 'source_only' and event['recipe_id'] not in {'A01', 'B01'}:
            raise ValueError('source_only copy policy is limited to A01 or text-free B01')
        declared_targets = event.get('target_binding_ids', [])
        if declared_targets != semantic.get('target_binding_ids', []):
            raise ValueError('shot target bindings differ from semantic instance')
        if event['recipe_id'] == 'A02':
            target_id = evidence.get('target_binding_ref')
            binding = (target_bindings or {}).get(target_id)
            if target_id not in declared_targets or not isinstance(binding, dict) or binding.get('semantic_event_id') != event['instance_id']:
                raise ValueError('anchored label requires resolved current instance target binding')
            window = binding.get('output_window') or {}
            if window.get('start_seconds') != event['output_start'] or window.get('end_seconds') != event['output_end']:
                raise ValueError('anchored label target window differs from semantic instance')
        if event['recipe_id'] == 'A01' and (event['source_crop'] is None or 'source_box' not in event):
            raise ValueError('camera recipe requires explicit crop and source placement')
        phases = event['phases']
        if not isinstance(phases, dict) or list(phases) != ['entrance', 'explain', 'hold', 'exit']:
            raise ValueError('four ordered phases required')
        previous = 0.0
        duration = event['output_end'] - event['output_start']
        for phase in phases.values():
            if not isinstance(phase, dict) or set(phase) != {'start', 'end'}:
                raise ValueError('phase must have start and end')
            a, b = phase['start'], phase['end']
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in (a, b)) or not previous <= a < b <= duration:
                raise ValueError('phase is unordered or outside event')
            previous = b
        active_end = event.get('active_end', event['output_end'])
        if isinstance(active_end, bool) or not isinstance(active_end, (int, float)) or not math.isfinite(active_end) or active_end > event['output_end'] or event['output_start'] + phases['exit']['end'] > active_end:
            raise ValueError('effect must exit before source state boundary')
        crop = event['source_crop']
        if crop is not None:
            if event['decision'] != 'shot' or set(crop) != {'x', 'y', 'width', 'height'}:
                raise ValueError('crop belongs only to source shot')
            if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v) for v in crop.values()):
                raise ValueError('crop must be finite')
            if not (0 <= crop['x'] < 1 and 0 <= crop['y'] < 1 and 0 < crop['width'] <= 1 and 0 < crop['height'] <= 1 and crop['x'] + crop['width'] <= 1 and crop['y'] + crop['height'] <= 1):
                raise ValueError('crop outside source')
            maximum = evidence.get('maximum_scale')
            if isinstance(maximum, bool) or not isinstance(maximum, (int, float)) or not math.isfinite(maximum) or 1/min(crop['width'], crop['height']) > maximum:
                raise ValueError('crop exceeds measured resolution allowance')
            if source_media is not None:
                placement = event.get('source_box') or {}
                if not all(isinstance(placement.get(k), (int, float)) and not isinstance(placement[k], bool)
                           and math.isfinite(placement[k]) and placement[k] > 0 for k in ('width', 'height')):
                    raise ValueError('measured source placement is required for crop')
                physical_maximum = min(source_media['width']/placement['width'],
                                       source_media['height']/placement['height'])
                if 1/min(crop['width'], crop['height']) > max(1, physical_maximum) + 1e-6:
                    raise ValueError('crop exceeds source-pixel resolution at output size')
        item = deepcopy(event)
        item['active_end'] = active_end
        item.setdefault('overlay_box', None)
        validate_recipe_event(item)
        compiled.append(item)
    return {'schema_version': 1, 'direction': direction, 'events': compiled,
            'plan_sha256': digest(plan), 'projection_sha256': digest(projection),
            'dependencies': sorted(set(dependencies)), 'renderer': 'hyperframes',
            'default_decorations': False, 'production_default': False}


def validate_storyboard_binding(storyboard: dict, payload: dict) -> list[str]:
    rows = storyboard.get('events') or []
    by_id = {row['instance_id']: row for row in payload['events']}
    seen = []
    errors = []
    for row in rows:
        instance = row.get('editorial_instance_id')
        expected = by_id.get(instance)
        if expected is None or row.get('editorial_plan_sha256') != payload['plan_sha256']:
            errors.append('Storyboard must bind current editorial instance and plan hash')
        elif row.get('editorial_recipe_id') != expected['recipe_id']:
            errors.append('Storyboard editorial recipe differs from plan')
        elif row.get('visible_copy_manifest') != expected['approved_visible_copy']:
            errors.append('Storyboard visible text must exactly equal editorial copy inventory')
        seen.append(instance)
    if seen != list(by_id):
        errors.append('Storyboard must equal editorial render subset in order')
    return errors


def project_caption_occurrences(captions: list[dict], projection: dict) -> list[dict]:
    """Bind already output-timed caption screens; never regroup across EDL cuts."""
    result = []
    for index, caption in enumerate(captions):
        start, end = caption['start'], caption['end']
        matches = [s for s in projection['segments']
                   if s['output_start'] <= start < end <= s['output_end'] + 0.001]
        if len(matches) != 1:
            raise ValueError('caption crosses segment boundary or output gap')
        segment = matches[0]
        words = [w for w in projection['words'] if w['segment_id'] == segment['segment_id']
                 and w['output_start'] < end and w['output_end'] > start]
        result.append({**caption, 'instance_id': f"caption-{index}@{segment['segment_id']}",
                       'segment_id': segment['segment_id'],
                       'word_occurrence_ids': [w['occurrence_id'] for w in words]})
    return result
