#!/usr/bin/env python3
"""Plan one universal social video unless platform media transforms truly differ."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


MEDIA_FIELDS = ("canvas_policy", "minimum_short_edge", "accepted_ratio_range", "video", "audio")


def _contract(preset: dict) -> dict:
    return {field: preset.get(field) for field in MEDIA_FIELDS}


def _intersection(zones: list[dict]) -> dict:
    result = {
        "x0": max(float(zone["x0"]) for zone in zones),
        "y0": max(float(zone["y0"]) for zone in zones),
        "x1": min(float(zone["x1"]) for zone in zones),
        "y1": min(float(zone["y1"]) for zone in zones),
    }
    if result["x0"] >= result["x1"] or result["y0"] >= result["y1"]:
        raise ValueError("Platform caption safe zones have no usable intersection")
    return result


def plan_delivery(presets: dict, platforms: list[str]) -> dict:
    selected = {name: presets["platforms"][name] for name in platforms}
    contracts = {name: _contract(preset) for name, preset in selected.items()}
    first = next(iter(contracts.values()))
    equivalent = all(contract == first for contract in contracts.values())
    safe_zone = _intersection([preset["caption_safe_zone"] for preset in selected.values()])
    if equivalent:
        outputs = [{"id": "universal", "platforms": platforms, "media_contract": first}]
        mode = "single_universal_export"
    else:
        outputs = [{"id": name, "platforms": [name], "media_contract": contracts[name]} for name in platforms]
        mode = "platform_specific_exports"
    return {
        "schema_version": 1,
        "mode": mode,
        "output_count": len(outputs),
        "outputs": outputs,
        "universal_caption_safe_zone": safe_zone,
        "file_size_warning_bytes": min(int(preset["file_size_warning_bytes"]) for preset in selected.values()),
        "rule": "Never duplicate byte-identical media only to attach a platform name; validate the same universal file separately.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--presets", required=True)
    parser.add_argument("--platform", action="append", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    presets = json.loads(Path(args.presets).read_text(encoding="utf-8"))
    report = plan_delivery(presets, args.platform)
    output = Path(args.out)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(output.resolve())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
