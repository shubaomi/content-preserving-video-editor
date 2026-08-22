#!/usr/bin/env python3
"""Narrow public facade for the default-off Jianying native-draft adapter v1."""
from jianying_native_common import (
    ADAPTER_ID, ADAPTER_VERSION, ADAPTER_WHEEL_SHA256,
    JianyingNativeDraftError,
)
from jianying_native_compatibility import (
    build_fixture_compatibility_profile, discover_jianying_executable,
    validate_adapter_lock, validate_compatibility_profile,
)
from jianying_native_plan import compile_draft_plan, validate_draft_plan
from jianying_native_package import (
    materialize_synthetic_fixture, validate_draft_package,
)

__all__ = [
    "ADAPTER_ID", "ADAPTER_VERSION", "ADAPTER_WHEEL_SHA256",
    "JianyingNativeDraftError", "build_fixture_compatibility_profile",
    "compile_draft_plan", "discover_jianying_executable",
    "materialize_synthetic_fixture", "validate_adapter_lock",
    "validate_compatibility_profile", "validate_draft_package",
    "validate_draft_plan",
]
