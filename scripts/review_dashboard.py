#!/usr/bin/env python3
"""Generate a dependency-free, read-only HTML view of existing Director evidence."""
from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from director_contracts import sha256_file


ARTIFACTS = (
    ("Production Contract", "production-contract.json"),
    ("Provider Decision", "provider-decision.json"),
    ("Cost Ledger", "cost-ledger.json"),
    ("Brand Motion Playbook", "brand-motion/brand-motion-playbook.json"),
    ("Sample Visual Dynamics QA", "sample-qa/visual-dynamics-qa.json"),
    ("Visual Dynamics QA", "full-qa/visual-dynamics-qa.json"),
    ("Preview/Render Parity", "full-qa/preview-render-parity.json"),
    ("Audio QA", "full-hyperframes/audio-plan.json"),
    ("Delivery QA", "delivery-contract.json"),
    ("Correction Ledger", "manual-finish/correction-ledger.json"),
    ("Action Required", "action-required.json"),
)


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _card(label: str, path: Path) -> str:
    if not path.is_file():
        return (
            f'<article><h3>{html.escape(label)}</h3><p class="missing">unavailable</p>'
            f'<p>{html.escape(str(path.resolve()))}</p></article>'
        )
    payload = _read(path)
    summary = json.dumps(payload, ensure_ascii=False, indent=2) if payload is not None else "binary artifact"
    return (
        f'<article><h3>{html.escape(label)}</h3><p><a href="{path.resolve().as_uri()}">open artifact</a></p>'
        f'<p class="hash">SHA-256 {sha256_file(path)}</p><pre>{html.escape(summary)}</pre></article>'
    )


def generate_dashboard(*, project_root: Path, director_root: Path, output: Path) -> Path:
    project_root = project_root.resolve()
    director_root = director_root.resolve()
    state_path = director_root / "director-state.json"
    state = _read(state_path) or {"status": "unavailable", "stages": {}}
    stage_rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{html.escape(str(row.get('status')))}</td>"
        f"<td>{html.escape(str(row.get('error') or ''))}</td></tr>"
        for name, row in (state.get("stages") or {}).items()
    )
    known_cards = "".join(_card(label, director_root / relative) for label, relative in ARTIFACTS)
    evidence_paths = sorted({
        *director_root.rglob("*.png"), *director_root.rglob("*.jpg"),
        *director_root.rglob("*.jpeg"), *director_root.rglob("*.mp4"),
        *project_root.glob("edit/video-use/transcripts/*.json"),
        *project_root.glob("edit/video-use/edl.json"),
        *project_root.glob("exports/*.mp4"), *project_root.glob("exports/*cover*"),
    })
    evidence = "".join(
        f'<li><a href="{path.resolve().as_uri()}">{html.escape(path.name)}</a> '
        f'<span>{html.escape(str(path.resolve()))} · SHA-256 {sha256_file(path)}</span></li>'
        for path in evidence_paths if path.is_file()
    ) or "<li>unavailable</li>"
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Director Review</title><style>
body{{font-family:system-ui,sans-serif;margin:0;background:#f5f7f3;color:#10251e}}header{{padding:28px;background:#0b3328;color:#fff}}
main{{max-width:1180px;margin:auto;padding:24px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}}
article,section{{background:#fff;border:1px solid #dbe6df;border-radius:16px;padding:18px;margin-bottom:18px;box-shadow:0 8px 24px #10251e12}}
pre{{max-height:320px;overflow:auto;white-space:pre-wrap;font-size:12px}}table{{width:100%;border-collapse:collapse}}td,th{{padding:8px;border-bottom:1px solid #e5ece8;text-align:left}}
.missing{{color:#8a4b3d}}.hash,li span{{font-size:11px;color:#62736c;word-break:break-all}}a{{color:#087e64}}
</style></head><body><header><h1>Director Review</h1><p>Read-only evidence dashboard — it does not edit media or replace human aesthetic and identity approval.</p>
<p>Status: <strong>{html.escape(str(state.get('status')))}</strong> · Current stage: {html.escape(str(state.get('current_stage') or 'none'))}</p></header>
<main><section><h2>Stage progress</h2><table><thead><tr><th>Stage</th><th>Status</th><th>Note</th></tr></thead><tbody>{stage_rows}</tbody></table></section>
<section><h2>Sample / Full snapshots, covers, source evidence and Universal MP4</h2><p>Snapshot phases include entrance, midpoint, pre-exit and post-exit when available.</p><ul>{evidence}</ul></section>
<div class="grid">{known_cards}</div></main></body></html>"""
    output.write_text(document, encoding="utf-8")
    return output
