#!/usr/bin/env python3
"""Promote the editorially recommended generated cover without inventing performance evidence."""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path


def promote(report_path: Path, out: Path, manifest_out: Path):
    report = json.loads(report_path.read_text(encoding="utf-8"))
    if not report.get("passed"):
        raise ValueError("A/B report must pass before promotion")
    selected = report["recommended_variant"]
    source_manifest_path = Path(report["variants"][selected]["manifest"])
    manifest = json.loads(source_manifest_path.read_text(encoding="utf-8"))
    source = Path(manifest["output"])
    if out.exists() or manifest_out.exists():
        raise FileExistsError("Refusing to overwrite an existing promoted cover or manifest")
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, out)
    manifest["output"] = str(out.resolve())
    manifest["selection"] = {
        "source_variant": selected,
        "ab_report": str(report_path.resolve()),
        "editorial_rationale": report["editorial_rationale"],
        "performance_claim": report["performance_claim"],
    }
    manifest_out.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--report", required=True)
    parser.add_argument("--out", required=True)
    parser.add_argument("--manifest", required=True)
    args = parser.parse_args()
    promote(Path(args.report), Path(args.out), Path(args.manifest))
    print(args.out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
