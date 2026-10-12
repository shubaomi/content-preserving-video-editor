"""Additive 1.1 instance-ID schema, leaving frozen 1.0 definitions unchanged."""
from copy import deepcopy

INSTANCE_CONTRACTS = {'motion-design-contract', 'target-binding', 'keyframe-receipt',
                      'motion-audio-decision', 'creative-review'}


def runtime_schema(name, frozen, payload):
    if not isinstance(payload, dict) or payload.get('schema_version') != '1.1.0':
        return frozen
    if name not in INSTANCE_CONTRACTS:
        return frozen
    schema = deepcopy(frozen)
    schema['$id'] = schema['$id'].replace('1.0.0', '1.1.0')
    schema['properties']['schema_version'] = {'const': '1.1.0'}
    # @ is a literal segment-instance separator, not permission to change time.
    # Instance derivation and current EDL bindings are checked separately.
    schema['$defs']['id']['pattern'] = r'^[A-Za-z0-9][A-Za-z0-9._:@-]{0,255}$'
    return schema
