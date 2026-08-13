#!/usr/bin/env python3
"""Create and immediately validate one explicit, SHA-256-bound WP6 window receipt."""
from __future__ import annotations

import argparse
from pathlib import Path

from director_contracts import read_json
from portrait_style_reel import (
    StyleReelError, create_style_reel_window_confirmation,
    validate_style_reel_window_confirmation,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--plan", required=True)
    parser.add_argument("--authorities", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--authorized-root", required=True)
    args = parser.parse_args()
    plan = Path(args.plan)
    authorities = Path(args.authorities)
    output = Path(args.output)
    create_style_reel_window_confirmation(
        plan_path=plan, authority_manifest_path=authorities,
        actor="HongRun", output=output, authorized_root=Path(args.authorized_root),
    )
    errors = validate_style_reel_window_confirmation(
        read_json(output), plan_path=plan, authority_manifest_path=authorities,
    )
    if errors:
        raise StyleReelError("window confirmation revalidation failed:\n- " + "\n- ".join(errors))
    print(output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
