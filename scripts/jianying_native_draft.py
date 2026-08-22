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
from jianying_native_install import (
    WP4_TEST_STORE_MARKER_FILENAME, WP4_TEST_TARGET_NAME,
    install_isolated_test_draft, rollback_isolated_test_draft,
    validate_install_receipt,
)

__all__ = [
    "ADAPTER_ID", "ADAPTER_VERSION", "ADAPTER_WHEEL_SHA256",
    "WP4_TEST_STORE_MARKER_FILENAME", "WP4_TEST_TARGET_NAME",
    "JianyingNativeDraftError", "build_fixture_compatibility_profile",
    "compile_draft_plan", "discover_jianying_executable",
    "install_isolated_test_draft",
    "materialize_synthetic_fixture", "rollback_isolated_test_draft",
    "validate_adapter_lock",
    "validate_compatibility_profile", "validate_draft_package",
    "validate_install_receipt",
    "validate_draft_plan",
]
