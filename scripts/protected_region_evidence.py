"""Validate explicit, time-bounded visual protection evidence without inventing tracking."""
from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from PIL import Image

from director_contracts import read_json, sha256_file

REGION_TYPES = {'faces', 'hands', 'products', 'poses', 'cursor', 'critical_ui', 'captions', 'platform_safe_zones'}


def _number(value: Any, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise ValueError(f'{name} must be a finite number')
    return float(value)


def _local_file(value: Any, root: Path) -> Path:
    if not isinstance(value, str) or not Path(value).is_absolute():
        raise ValueError('evidence file paths must be absolute')
    path = Path(value).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError('evidence file must exist inside project_root')
    return path


def _covered(rows: list[dict], start: float, end: float) -> bool:
    cursor = start
    for row in sorted(rows, key=lambda item: item['source_start']):
        if row['source_end'] <= cursor:
            continue
        if row['source_start'] > cursor + 1e-6:
            return False
        if row['status'] not in {'present', 'absent'}:
            return False
        cursor = max(cursor, row['source_end'])
        if cursor >= end - 1e-6:
            return True
    return False


def load_protected_region_evidence(
    manifest_path: Path, *, project_root: Path, source_path: Path,
    display: dict[str, Any], required_window: tuple[float, float] | None = None,
) -> tuple[dict[str, Any], list[Path]]:
    """Return validated observations; unresolved temporal coverage is never a pass.

    Image hashes bind the review to local pixels, not independent proof of source
    capture or a continuous detector track. Those claims remain reviewer provenance.
    """
    root = Path(project_root).resolve()
    manifest_path = _local_file(str(Path(manifest_path).resolve()), root)
    source_path = Path(source_path).resolve()
    data = read_json(manifest_path)
    if data.get('schema_version') != 2 or data.get('kind') != 'protected_region_evidence':
        raise ValueError('expected protected_region_evidence schema_version 2')
    source = data.get('source', {})
    if (not isinstance(source.get('path'), str) or not Path(source['path']).is_absolute()
            or Path(source['path']).resolve() != source_path
            or source.get('sha256') != sha256_file(source_path)):
        raise ValueError('source path/hash mismatch')
    if data.get('coordinate_space') != 'normalized_display_v1':
        raise ValueError('coordinate_space mismatch')
    for key in ('width', 'height', 'rotation_degrees'):
        if key not in display or data.get('display', {}).get(key) != display[key]:
            raise ValueError('display geometry/rotation mismatch')
    provenance = data.get('provenance', {})
    method = provenance.get('method')
    if method not in {'manual_visual_review', 'detector_observation'}:
        raise ValueError('explicit evidence provenance required')
    if method == 'manual_visual_review':
        required_provenance = ('reviewer', 'reviewed_at')
    else:
        required_provenance = ('detector', 'reviewed_at')
    if any(not isinstance(provenance.get(key), str) or not provenance[key].strip() for key in required_provenance):
        raise ValueError('incomplete review/detector provenance')
    required = data.get('required_region_types')
    if (not isinstance(required, list) or not required or any(item not in REGION_TYPES for item in required)
            or len(set(required)) != len(required)):
        raise ValueError('required_region_types must be unique supported types')
    observations = data.get('observations')
    if not isinstance(observations, dict) or any(key not in REGION_TYPES for key in observations):
        raise ValueError('invalid observations')
    if required_window is not None:
        start, end = (_number(value, 'required_window') for value in required_window)
        if start < 0 or end <= start:
            raise ValueError('invalid required_window')
    else:
        start = end = 0.0
    artifacts = [manifest_path]
    verified_frames: dict[str, dict[str, Any]] = {}
    payload: dict[str, Any] = {key: [] for key in REGION_TYPES}
    summaries = {}
    unresolved = []
    for region_type in sorted(set(required) | set(observations)):
        rows = observations.get(region_type, [])
        if not isinstance(rows, list):
            raise ValueError('observations for each region type must be a list')
        identities: dict[str, list[dict]] = {}
        hashes = set()
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get('region_id'), str) or not row['region_id'].strip():
                raise ValueError('region_id is required')
            left = _number(row.get('source_start'), 'source_start')
            right = _number(row.get('source_end'), 'source_end')
            status = row.get('status')
            if left < 0 or right <= left or status not in {'present', 'absent', 'unknown', 'lost'}:
                raise ValueError('invalid observation interval/status')
            previous = identities.setdefault(row['region_id'], [])
            if any(left < other['source_end'] and right > other['source_start'] for other in previous):
                raise ValueError('overlapping observations for one region_id')
            previous.append(row)
            bbox = row.get('bbox')
            if status == 'present':
                if not isinstance(bbox, dict) or row.get('geometry_method') != 'bounded_review_envelope':
                    raise ValueError('present requires a bounded_review_envelope bbox')
                x, y, w, h = (_number(bbox.get(key), 'bbox') for key in ('x', 'y', 'width', 'height'))
                if x < 0 or y < 0 or w <= 0 or h <= 0 or x + w > 1 or y + h > 1:
                    raise ValueError('bbox outside normalized display')
            elif bbox is not None:
                raise ValueError('non-present observation cannot supply geometry')
            evidence = row.get('evidence', [])
            if not isinstance(evidence, list):
                raise ValueError('evidence must be a list')
            times = []
            frame_paths = set()
            frame_hashes = set()
            for frame in evidence:
                if not isinstance(frame, dict):
                    raise ValueError('invalid evidence frame')
                path = _local_file(frame.get('path'), root)
                digest = sha256_file(path)
                if frame.get('sha256') != digest:
                    raise ValueError('evidence frame hash mismatch')
                timestamp = _number(frame.get('timestamp_seconds'), 'frame timestamp')
                if timestamp < 0:
                    raise ValueError('negative frame timestamp')
                prior_frame = verified_frames.get(str(path))
                if prior_frame is not None and prior_frame['timestamp_seconds'] != timestamp:
                    raise ValueError('one evidence frame cannot claim conflicting timestamps')
                try:
                    with Image.open(path) as image:
                        image.load()
                except (OSError, ValueError) as exc:
                    raise ValueError('evidence frame is not decodable') from exc
                times.append(timestamp)
                frame_paths.add(path)
                frame_hashes.add(digest)
                hashes.add(digest)
                artifacts.append(path)
                verified_frames[str(path)] = {
                    'path': str(path), 'sha256': digest, 'timestamp_seconds': timestamp,
                    'coverage': {'status': 'unknown', 'reason': 'discrete reviewed frame, not continuous tracking'},
                    'provenance': {'kind': 'protected_region_review', 'path': str(manifest_path),
                                   'sha256': sha256_file(manifest_path), 'method': method},
                }
            if status in {'present', 'absent'}:
                # A conservative interval review needs start/middle/end pixels,
                # not one duplicated image labeled as a continuous track.
                if len(frame_paths) < 3 or len(frame_hashes) < 3 or len(set(times)) < 3:
                    raise ValueError('present/absent requires three distinct review frames')
                if not (min(times) <= left and max(times) >= right and any(left < t < right for t in times)):
                    raise ValueError('review frames must bracket interval and include its interior')
            if status == 'present' and (required_window is None or right > start and left < end):
                payload[region_type].append({
                    'region_id': row['region_id'], 'bbox': dict(bbox), 'source_start': left, 'source_end': right,
                    'method': method, 'geometry_method': row['geometry_method'],
                    'evidence_frame_sha256': sorted(frame_hashes),
                })
        relevant = [row for row in rows if required_window is None or row['source_end'] > start and row['source_start'] < end]
        complete = required_window is not None and bool(identities) and all(_covered(items, start, end) for items in identities.values())
        if region_type in required and not complete:
            unresolved.append({'region_type': region_type, 'reason': 'missing_window_or_unknown_lost_or_coverage_gap'})
        summaries[region_type] = {
            'status': ('observed_absent' if complete and relevant and all(row['status'] == 'absent' for row in relevant)
                       else 'observed_present' if complete else 'unknown'),
            'evidence_frame_sha256': sorted(hashes),
        }
    payload.update(status='action_required' if unresolved else 'pass', observations=summaries,
        coverage={'required_window': list(required_window) if required_window is not None else None, 'unresolved': unresolved},
        provenance=dict(provenance), review_sha256=sha256_file(manifest_path),
        verified_frames=sorted(verified_frames.values(), key=lambda frame: (frame['timestamp_seconds'], frame['path'])))
    return payload, list(dict.fromkeys(artifacts))
