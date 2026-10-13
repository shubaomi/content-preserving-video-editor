"""QA-A: validate approved A01 source reframing, never waive graphic clipping.

The raw renderer crop measurement remains unchanged. This adapter is opt-in,
source/plan/protection bound and deliberately supports only the existing A01
uniform, axis-aligned power2.inOut camera. It does not infer subject tracking.
"""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from director_contracts import read_json, sha256_file
from motion_editorial import compile_shot_plan, digest
from protected_region_evidence import load_protected_region_evidence


def _number(value):
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError('finite measured number required')
    return float(value)


def _box(value):
    return {k: _number(value[k]) for k in ('x', 'y', 'width', 'height')}


def _ease(value):
    t = min(1., max(0., value))
    return 4*t*t*t if t < .5 else 1 - (-2*t+2)**3/2


def expected_camera_rect(shot: dict, timestamp: float) -> dict:
    crop, source = _box(shot['source_crop']), _box(shot['source_box'])
    local = _number(timestamp) - _number(shot['output_start'])
    explain, leave = shot['phases']['explain'], shot['phases']['exit']
    if local < explain['start']:
        amount = 0.
    elif local < explain['end']:
        amount = _ease((local-explain['start'])/(explain['end']-explain['start']))
    elif local < leave['start']:
        amount = 1.
    else:
        amount = 1-_ease((local-leave['start'])/(leave['end']-leave['start']))
    scale = 1 + (1/crop['width']-1)*amount
    return dict(x=source['x']-crop['x']*source['width']/crop['width']*amount,
                y=source['y']-crop['y']*source['height']/crop['width']*amount,
                width=source['width']*scale, height=source['height']*scale)


def validate_camera_geometry(shot: dict, timestamp: float, observed: dict,
                             regions: list, *, width: float, height: float,
                             caption_top: float) -> list[str]:
    try:
        if shot['recipe_id'] != 'A01' or shot['decision'] != 'shot':
            raise ValueError('only approved A01 source shots may use reframe evidence')
        if not shot['output_start'] <= timestamp < shot['output_end']:
            raise ValueError('camera observation outside approved window')
        if observed.get('visible') is not True or observed.get('added_paint') != []:
            raise ValueError('camera missing or added graphic paint present')
        if not regions:
            raise ValueError('source protection missing')
        expected = expected_camera_rect(shot, timestamp)
        actual = _box(observed['source_rect'])
        if max(abs(actual[k]-expected[k]) for k in actual) > .02:
            raise ValueError('actual source rectangle differs from approved camera')
        placement = shot['source_box']
        scale = expected['width']/placement['width']
        matrix = [scale, 0, 0, scale, expected['x']-placement['x'], expected['y']-placement['y']]
        measured = observed['matrix']
        if not isinstance(measured, list) or len(measured) != 6 or any(
                abs(_number(a)-b) > .02 for a,b in zip(measured,matrix)):
            raise ValueError('actual camera matrix differs from approved transform')
        if observed.get('transform_origin') != [0,0]:
            raise ValueError('camera transform origin differs')
        width, height, caption_top = map(_number, (width,height,caption_top))
        if not 0 < caption_top <= height or width <= 0:
            raise ValueError('invalid canvas/caption boundary')
        for item in regions:
            box = _box(item)
            if (min(box.values()) < 0 or min(box['width'],box['height']) <= 0
                    or box['x']+box['width'] > 1 or box['y']+box['height'] > 1):
                raise ValueError('unknown/invalid source protection')
            left, top = actual['x']+box['x']*actual['width'], actual['y']+box['y']*actual['height']
            right, bottom = left+box['width']*actual['width'], top+box['height']*actual['height']
            if left < -.01 or top < -.01 or right > width+.01 or bottom > caption_top+.01:
                raise ValueError('protected source subject is cropped or enters caption lane')
        # Only empty background may leave the canvas; source pixels cannot cover captions.
        if actual['y']+actual['height'] > caption_top+.01:
            raise ValueError('source picture enters caption lane')
        return []
    except (ValueError, TypeError, KeyError, ZeroDivisionError) as exc:
        return [str(exc)]


def _current(ref):
    if not isinstance(ref, dict) or not isinstance(ref.get('path'), str):
        raise ValueError('reframe artifact reference missing')
    path = Path(ref['path'])
    if not path.is_absolute() or not path.is_file() or ref.get('sha256') != sha256_file(path):
        raise ValueError('reframe artifact path/hash stale')
    return path.resolve()


def validate_source_reframe_phase(context: Any, *, phase: dict, event_id: str,
                                  project_artifact: Path, motion_contract_path: Path) -> list[str]:
    """Recompute plan, source identity, protection coverage and actual phase geometry."""
    try:
        intent_path = _current(context)
        intent = read_json(intent_path)
        if intent.get('schema_version') != 1 or intent.get('kind') != 'source_reframe_intent':
            raise ValueError('unknown source reframe adapter')
        inputs = {k: _current(v) for k,v in intent['inputs'].items()}
        if inputs['project_artifact'] != project_artifact.resolve() or inputs['motion_contract'] != motion_contract_path.resolve():
            raise ValueError('reframe project/contract binding differs')
        source = inputs['source_media']
        approval = read_json(inputs['plan_approval'])
        if (approval.get('kind') != 'explicit_user_plan_and_bounded_sample_authorization'
                or not approval.get('approved_by') or not approval.get('user_message')
                or approval.get('restrictions', {}).get('full_render_authorized') is not False):
            raise ValueError('explicit bounded sample approval missing')
        for ref in approval.get('documents', []):
            _current(ref)
        source_group = next(r for r in approval['source_bindings']
                            if any(_current(v) == source for v in r['bindings']))
        authorized = next(r for r in approval['authorized_samples'] if r['id'] == source_group['id'])
        plan, projection, brief = (read_json(inputs[k]) for k in ('shot_plan','projection','semantic_brief'))
        contract = read_json(motion_contract_path)
        if (contract['source_media']['sha256'] != sha256_file(source)
                or projection['input_hashes']['source'] != sha256_file(source)):
            raise ValueError('reframe source differs from authority')
        shot = next(r for r in plan['events'] if r['instance_id'] == event_id)
        # The existing compiler rechecks exact semantic decisions, windows/copy,
        # recipe constraints and nested frame references instead of trusting a hash string.
        bindings = {r['binding_id']: r for r in (read_json(p) for k,p in inputs.items()
                    if k.startswith('target_binding_'))}
        compile_shot_plan(plan, projection=projection, output_brief=brief,
            direction=plan['direction'], roots=[source.parent.parent, intent_path.parent],
            source_media=intent['display'], target_bindings=bindings)
        if plan['projection_sha256'] != digest(projection) or plan['semantic_sha256'] != digest(brief):
            raise ValueError('reframe plan changed')
        window = next(r['output_window'] for r in contract['opportunities'] if r['semantic_event_id'] == event_id)
        if window != dict(start_seconds=shot['output_start'],end_seconds=shot['output_end']):
            raise ValueError('reframe event window differs from contract')
        timestamp = _number(phase['timestamp_seconds'])
        segment = next(r for r in projection['segments'] if r['output_start'] <= timestamp < r['output_end'])
        approved_start, approved_end = authorized['source_range_seconds']
        if not (approved_start <= segment['source_range']['start'] < segment['source_range']['end'] <= approved_end):
            raise ValueError('source segment outside approved sample')
        if segment.get('speed') != 1:
            raise ValueError('reframe adapter does not support retiming')
        source_time = segment['source_range']['start'] + timestamp-segment['output_start']
        protection_result, _ = load_protected_region_evidence(inputs['protected_review'],
            project_root=source.parent.parent, source_path=source, display=intent['display'],
            required_window=(source_time,source_time+.000001))
        if protection_result.get('status') != 'pass':
            raise ValueError('source protection coverage unresolved')
        protection = read_json(inputs['protected_review'])
        if not {'faces','hands'}.issubset(set(protection['required_region_types'])):
            raise ValueError('face/hand protection not declared')
        regions = []
        for rows in protection['observations'].values():
            for row in rows:
                if row['source_start'] <= source_time < row['source_end']:
                    if row['status'] not in {'present','absent'}:
                        raise ValueError('unknown or lost source protection')
                    if row['status'] == 'present':
                        regions.append(row['bbox'])
        product = read_json(inputs['product_review'])
        product_result, _ = load_protected_region_evidence(inputs['product_review'],
            project_root=source.parent.parent, source_path=source, display=intent['display'],
            required_window=(source_time,source_time+.000001))
        if product_result.get('status') != 'pass' or product.get('required_region_types') != ['products']:
            raise ValueError('product protection coverage unresolved')
        products = [r for r in product['observations']['products'] if r['source_start'] <= source_time < r['source_end']]
        if not products or any(r.get('status') != 'present' for r in products):
            raise ValueError('product evidence missing/unknown/lost')
        for row in products:
            if not row.get('evidence'):
                raise ValueError('product frame evidence missing')
            for ref in row['evidence']:
                _current(ref)
            regions.append(row['bbox'])
        observed = phase.get('source_reframe_observation') or {}
        storyboard = read_json(project_artifact.parent / 'storyboard.json')
        canvas = {key:storyboard['composition'][key] for key in ('width','height')}
        if (intent['canvas'] != canvas or observed.get('canvas') != canvas
                or observed.get('caption_top') != intent['caption_top']):
            raise ValueError('observed canvas/caption lane differs from source intent')
        treatment = read_json(inputs['caption_plan'])['treatment']
        layout = treatment['layout']
        # A conservative single-line envelope: two scaled em plus four pixels
        # of glyph/outline clearance. The captured lane may only be larger.
        if layout.get('single_line') is not True:
            raise ValueError('reframe adapter requires bounded single-line caption layout')
        maximum_top = canvas['height'] - _number(layout['margin_bottom_px']) - math.ceil(
            2*_number(layout['font_size_px'])*_number(treatment['max_scale_percent'])/100+4)
        if _number(intent['caption_top']) > maximum_top:
            raise ValueError('caption lane weakens current caption style protection')
        selector = intent['event_sources'][event_id]
        if observed.get('selector') != selector or observed.get('source_asset') != intent['inputs']['media_asset']:
            raise ValueError('actual DOM source identity differs')
        if phase.get('visible_text') != []:
            raise ValueError('source-only camera has added text')
        return validate_camera_geometry(shot,timestamp,observed,regions,
            width=intent['canvas']['width'],height=intent['canvas']['height'],
            caption_top=intent['caption_top'])
    except (ValueError, TypeError, KeyError, StopIteration, OSError) as exc:
        return [f'source reframe: {exc}']
