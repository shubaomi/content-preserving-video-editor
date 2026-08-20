#!/usr/bin/env python3
"""Build a deterministic, preview-only modular CTA outro HyperFrames project.

The builder produces editable source, text/icon instructions, and rights records.
It does not render media or authorize a final outro without user preview approval.
"""
from __future__ import annotations

import hashlib
import html
import json
import math
import os
import shutil
import subprocess
import time
import uuid
import zipfile
from pathlib import Path
from typing import Any, Mapping

from director_contracts import read_json, sha256_file
from safe_generated_output import (
    SafeGeneratedOutputError,
    atomic_replace_file,
    atomic_write_text,
    safe_generated_directory,
    safe_generated_target,
)


class NleOutroError(ValueError):
    """Raised when the modular outro cannot be built truthfully and safely."""


_IMPLEMENTATION = Path(__file__).resolve()
_DIRECTION = "luminous_intelligence"
_ICON_SVGS = {
    "like": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96"><path fill="none" stroke="#34D399" stroke-width="8" stroke-linecap="round" stroke-linejoin="round" d="M29 42v38H13V42h16Zm0 32h35c7 0 11-4 13-10l7-22c2-7-2-12-9-12H58l3-13c2-9-10-14-15-6L29 42"/></svg>""",
    "favorite": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96"><path fill="none" stroke="#F6C177" stroke-width="8" stroke-linejoin="round" d="m48 10 11 24 26 3-19 18 5 26-23-13-23 13 5-26L11 37l26-3 11-24Z"/></svg>""",
    "share": """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 96 96"><path fill="none" stroke="#22D3EE" stroke-width="8" stroke-linecap="round" stroke-linejoin="round" d="M34 50 69 19m0 0H47m22 0v22M78 53v25H18V31h26"/></svg>""",
}


def _stable_hash(payload: Mapping[str, Any]) -> str:
    value = dict(payload)
    value.pop("integrity_sha256", None)
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


def _finite(value: Any, *, positive: bool = False) -> bool:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    number = float(value)
    return math.isfinite(number) and (not positive or number > 0)


def _write_json(path: Path, payload: Any) -> None:
    atomic_write_text(
        path,
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False) + "\n",
    )


def _file_ref(path: Path, root: Path) -> dict[str, str]:
    resolved = path.resolve()
    return {
        "path": str(resolved.relative_to(root.resolve())).replace("\\", "/"),
        "sha256": sha256_file(resolved),
    }


def _replace_directory(staging: Path, output: Path) -> None:
    backup = output.parent / f".{output.name}.backup-{uuid.uuid4().hex}"
    had_previous = output.exists()

    def replace(source: Path, target: Path) -> None:
        deadline = time.monotonic() + 5.0
        while True:
            try:
                os.replace(source, target)
                return
            except PermissionError:
                if time.monotonic() >= deadline:
                    raise
                time.sleep(0.01)

    if had_previous:
        replace(output, backup)
    try:
        replace(staging, output)
    except Exception:
        if had_previous and backup.exists():
            replace(backup, output)
        raise
    if backup.exists():
        shutil.rmtree(backup, ignore_errors=True)


def _profile_tokens(profile_path: Path) -> tuple[dict[str, Any], dict[str, str]]:
    try:
        profile = read_json(profile_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        raise NleOutroError("modular outro brand profile is unreadable") from error
    if not isinstance(profile, Mapping):
        raise NleOutroError("modular outro brand profile must be an object")
    if (
        profile.get("profile_id") != "hongrun"
        or profile.get("identity_mode") != "self"
        or profile.get("direction") != _DIRECTION
    ):
        raise NleOutroError(
            "modular outro requires the HongRun luminous_intelligence profile"
        )
    palettes = profile.get("palettes")
    dark = palettes.get("dark") if isinstance(palettes, Mapping) else None
    required = ("canvas", "ink", "mint", "cyan", "warm", "violet")
    if not isinstance(dark, Mapping) or any(
        not isinstance(dark.get(key), str) or not dark[key].startswith("#")
        for key in required
    ):
        raise NleOutroError("modular outro brand palette is incomplete")
    typography = profile.get("typography")
    font = typography.get("font_family") if isinstance(typography, Mapping) else None
    if not isinstance(font, str) or not font.strip():
        raise NleOutroError("modular outro typography is incomplete")
    tokens = {key: str(dark[key]) for key in required}
    tokens["font"] = font.strip()
    return dict(profile), tokens


def _copy_payload(value: Any) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise NleOutroError("modular outro copy must be an object")
    headline = value.get("headline")
    supporting = value.get("supporting")
    actions = value.get("actions")
    if (
        not isinstance(headline, str) or not headline.strip()
        or len(headline.strip()) > 30
        or not isinstance(supporting, str) or not supporting.strip()
        or len(supporting.strip()) > 40
        or not isinstance(actions, list) or not 1 <= len(actions) <= 3
        or any(not isinstance(item, str) or not item.strip() or len(item.strip()) > 8 for item in actions)
        or len({item.strip() for item in actions}) != len(actions)
    ):
        raise NleOutroError("modular outro copy is invalid")
    return {
        "headline": headline.strip(),
        "actions": [item.strip() for item in actions],
        "supporting": supporting.strip(),
    }


def _rights_payload(
    *, asset_path: Path, asset_sha256: str, role: str, rights_basis: str,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "kind": "nle_asset_rights",
        "status": "authorized",
        "asset": {"path": str(asset_path.resolve()), "sha256": asset_sha256},
        "allowed_roles": [role],
        "identity_mode": "self",
        "rights_basis": rights_basis,
        "redistribution_authorized": True,
    }


def _html_document(
    *, width: int, height: int, duration: float, frame_rate: float,
    copy: Mapping[str, Any],
    tokens: Mapping[str, str],
) -> str:
    action_rows = []
    fallback_icons = list(_ICON_SVGS)
    used_icons: set[str] = set()
    for index, label in enumerate(copy["actions"]):
        normalized = str(label).strip().lower()
        if "赞" in normalized or normalized in {"like", "thumbs up"}:
            icon = "like"
        elif "收藏" in normalized or normalized in {"favorite", "favourite", "save"}:
            icon = "favorite"
        elif "转发" in normalized or "分享" in normalized or normalized == "share":
            icon = "share"
        else:
            icon = next(name for name in fallback_icons if name not in used_icons)
        used_icons.add(icon)
        action_rows.append(
            f'<div class="action" id="action-{index}"><img src="icons/{icon}.svg" '
            f'alt=""/><span>{html.escape(str(label))}</span></div>'
        )
    actions = "".join(action_rows)
    variables = json.dumps([
        {"id": "showCopy", "type": "boolean", "label": "显示参考文案", "default": True},
        {"id": "showBackground", "type": "boolean", "label": "显示参考背景", "default": True},
    ], ensure_ascii=False, separators=(",", ":"))
    return f"""<!doctype html>
<html lang="zh-CN" data-composition-variables='{variables}'>
<head>
  <meta charset="UTF-8" />
  <meta name="viewport" content="width={width}, height={height}" />
  <title>HongRun modular CTA outro</title>
  <script src="assets/gsap-3.14.2.min.js"></script>
  <style>
    * {{ box-sizing: border-box; }}
    html, body {{ margin: 0; width: {width}px; height: {height}px; overflow: hidden; background: transparent; }}
    @font-face {{ font-family: "HongRun NLE Sans"; src: local("{html.escape(tokens['font'])}"), local("Microsoft YaHei UI"), local("Microsoft YaHei"); font-display: block; }}
    body {{ font-family: "HongRun NLE Sans", system-ui, sans-serif; color: {tokens['ink']}; }}
    #outro {{ position: relative; width: {width}px; height: {height}px; overflow: hidden; }}
    .module {{ position: absolute; inset: 0; transform-origin: center center; }}
    .clip {{ position: absolute; inset: 0; }}
    .preview-bg {{ position: absolute; inset: 0; background: {tokens['canvas']}; opacity: .98; }}
    .glow {{ position: absolute; width: 720px; height: 720px; left: 180px; top: 510px; border-radius: 50%;
      background: radial-gradient(circle, {tokens['cyan']}55 0%, {tokens['mint']}22 42%, transparent 72%); }}
    .orbit {{ position: absolute; width: 690px; height: 690px; left: 195px; top: 525px; border: 4px solid {tokens['cyan']}88;
      border-radius: 50%; box-shadow: 0 0 54px {tokens['cyan']}44; }}
    .orbit::after {{ content: ""; position: absolute; inset: 72px; border: 3px solid {tokens['violet']}77; border-radius: 50%; }}
    .core {{ position: absolute; width: 230px; height: 230px; left: 425px; top: 755px; border-radius: 50%;
      background: {tokens['canvas']}; border: 5px solid {tokens['mint']}; box-shadow: 0 0 80px {tokens['mint']}66;
      display: grid; place-items: center; }}
    .core-mark {{ width: 94px; height: 94px; border: 10px solid {tokens['mint']}; border-radius: 28px; position: relative; }}
    .core-mark::after {{ content: ""; position: absolute; width: 24px; height: 24px; border-radius: 50%; background: {tokens['warm']}; right: -20px; top: -18px; }}
    .actions {{ position: absolute; width: 920px; left: 80px; top: 1090px; display: flex; justify-content: center; gap: 34px; }}
    .action {{ width: 260px; height: 172px; border-radius: 44px; border: 3px solid {tokens['cyan']}99;
      background: {tokens['canvas']}E8; box-shadow: 0 24px 80px #00000055; display: flex; flex-direction: column;
      align-items: center; justify-content: center; gap: 12px; }}
    .action img {{ width: 72px; height: 72px; }}
    .action span {{ font-size: 34px; font-weight: 800; letter-spacing: .08em; }}
    .copy-layer {{ position: absolute; width: 920px; left: 80px; top: 190px; text-align: left; }}
    .eyebrow {{ display: inline-block; padding: 14px 26px; border: 3px solid {tokens['mint']}; color: {tokens['mint']};
      border-radius: 999px; font-size: 26px; font-weight: 800; letter-spacing: .16em; }}
    h1 {{ margin: 42px 0 16px; max-width: 900px; font-size: 94px; line-height: 1.02; letter-spacing: -.035em; font-weight: 900; }}
    .supporting {{ margin: 0; font-size: 40px; line-height: 1.35; color: {tokens['warm']}; font-weight: 700; }}
    .rail {{ position: absolute; left: 80px; right: 80px; bottom: 136px; height: 8px; border-radius: 8px; background: {tokens['mint']}; transform-origin: left center; }}
    .meta {{ position: absolute; left: 80px; bottom: 82px; font-size: 24px; letter-spacing: .22em; color: {tokens['cyan']}; font-weight: 700; }}
  </style>
</head>
<body>
  <div id="outro" data-hf-id="hongrun-modular-cta" data-composition-id="hongrun-modular-cta" data-start="0" data-width="{width}" data-height="{height}" data-duration="{duration:.3f}" data-fps="{frame_rate:g}">
    <section id="outro-scene" class="clip" data-start="0" data-duration="{duration:.3f}" data-track-index="1">
      <div class="preview-bg" id="preview-bg"></div>
      <div id="module" class="module" data-hf-id="outro-module">
        <div class="glow" id="glow"></div><div class="orbit" id="orbit"></div>
        <div class="core" id="core"><div class="core-mark"></div></div>
        <div class="copy-layer" id="copy-layer"><div class="eyebrow">HONGRUN · LUMINOUS</div>
          <h1>{html.escape(str(copy['headline']))}</h1><p class="supporting">{html.escape(str(copy['supporting']))}</p></div>
        <div class="actions">{actions}</div><div class="rail" id="rail"></div>
        <div class="meta" id="meta">FOLLOW · LIKE · SHARE</div>
      </div>
    </section>
  </div>
  <script>
    const vars = window.__hyperframes.getVariables();
    const copyLayer = document.getElementById("copy-layer");
    const meta = document.getElementById("meta");
    const actionLabels = Array.from(document.querySelectorAll(".action span"));
    if (!vars.showCopy) {{
      copyLayer.remove();
      meta.remove();
      actionLabels.forEach((node) => node.remove());
    }}
    if (!vars.showBackground) document.getElementById("preview-bg").remove();
    window.__timelines = window.__timelines || {{}};
    const tl = gsap.timeline({{paused:true}});
    tl.fromTo("#glow", {{scale:.35, opacity:0}}, {{scale:1, opacity:1, duration:.72, ease:"power3.out"}}, 0.05)
      .fromTo("#orbit", {{scale:.4, rotation:-95, opacity:0}}, {{scale:1, rotation:0, opacity:1, duration:.78, ease:"back.out(1.7)"}}, 0.12)
      .fromTo("#core", {{scale:0, rotation:-24, opacity:0}}, {{scale:1, rotation:0, opacity:1, duration:.62, ease:"back.out(2.1)"}}, 0.24);
    if (vars.showCopy) tl.fromTo(".copy-layer", {{x:-72, opacity:0}}, {{x:0, opacity:1, duration:.58, ease:"power4.out"}}, 0.34);
    tl
      .fromTo(".action", {{y:80, scale:.7, opacity:0}}, {{y:0, scale:1, opacity:1, duration:.5, stagger:.12, ease:"back.out(1.8)"}}, .78)
      .fromTo("#rail", {{scaleX:0, opacity:0}}, {{scaleX:1, opacity:1, duration:.72, ease:"power3.inOut"}}, 1.08)
    if (vars.showCopy) tl.fromTo("#meta", {{x:54, opacity:0}}, {{x:0, opacity:1, duration:.46, ease:"power2.out"}}, 1.26);
    tl.to("#orbit", {{rotation:36, duration:1.7, ease:"sine.inOut"}}, 1.28)
      .to("#glow", {{scale:1.08, opacity:.76, duration:1.7, ease:"sine.inOut"}}, 1.28)
      .to("#module", {{scale:.92, opacity:0, duration:.52, ease:"power3.in"}}, {max(2.8, duration - .62):.3f});
    window.__timelines["hongrun-modular-cta"] = tl;
  </script>
</body>
</html>
"""


def validate_modular_outro_contract(contract_path: Path) -> list[str]:
    try:
        payload = read_json(Path(contract_path))
    except (OSError, ValueError, json.JSONDecodeError):
        return ["modular outro contract is unreadable"]
    if not isinstance(payload, Mapping):
        return ["modular outro contract must be an object"]
    errors: list[str] = []
    root = Path(contract_path).resolve().parent
    if (
        payload.get("schema_version") != 1
        or payload.get("kind") != "manual_nle_modular_outro"
        or payload.get("status") != "preview_pending"
        or payload.get("direction") != _DIRECTION
    ):
        errors.append("modular outro contract identity is invalid")
    canvas = payload.get("canvas")
    if not isinstance(canvas, Mapping) or any(
        isinstance(canvas.get(key), bool) or not isinstance(canvas.get(key), int) or canvas[key] < 1
        for key in ("width", "height")
    ):
        errors.append("modular outro canvas is invalid")
    if not _finite(payload.get("frame_rate"), positive=True) or not _finite(
        payload.get("duration_seconds"), positive=True
    ):
        errors.append("modular outro timing is invalid")
    if payload.get("render_authorized") is not False:
        errors.append("modular outro render must remain preview-gated")
    files = payload.get("files")
    if not isinstance(files, list) or not files:
        errors.append("modular outro file inventory is missing")
    else:
        seen: set[str] = set()
        for row in files:
            if not isinstance(row, Mapping):
                errors.append("modular outro file record is malformed")
                continue
            value = row.get("path")
            digest = row.get("sha256")
            if not isinstance(value, str) or not value or value in seen:
                errors.append("modular outro file path is missing or duplicate")
                continue
            seen.add(value)
            relative = Path(value)
            path = (root / relative).resolve()
            if relative.is_absolute() or ".." in relative.parts or not path.is_relative_to(root) or not path.is_file():
                errors.append(f"modular outro file is missing or outside project: {value}")
            elif not isinstance(digest, str) or digest != sha256_file(path):
                errors.append(f"modular outro file is stale: {value}")
    if payload.get("integrity_sha256") != _stable_hash(payload):
        errors.append("modular outro contract integrity is stale")
    return errors


def record_modular_outro_render_approval(
    *, contract_path: Path, snapshot_path: Path, output_path: Path,
    authorized_root: Path, actor: str, decision: str, reason: str,
    approved_at: str,
) -> dict[str, Any]:
    """Record explicit preview approval without claiming identity authentication."""
    contract_path = Path(contract_path).resolve()
    snapshot_path = Path(snapshot_path).resolve()
    if validate_modular_outro_contract(contract_path):
        raise NleOutroError("modular outro approval requires a current preview contract")
    if not snapshot_path.is_file():
        raise NleOutroError("modular outro approval snapshot is missing")
    if actor != "HongRun" or decision != "approve_render":
        raise NleOutroError("modular outro render requires explicit HongRun approval")
    if not isinstance(reason, str) or not reason.strip():
        raise NleOutroError("modular outro approval reason is missing")
    if not isinstance(approved_at, str) or not approved_at.endswith("Z"):
        raise NleOutroError("modular outro approval time is invalid")
    payload = {
        "schema_version": 1,
        "kind": "manual_nle_outro_render_approval",
        "status": "approved",
        "actor": actor,
        "decision": decision,
        "scope": ["four_second_transparent_outro_layer", "reference_composite"],
        "reason": reason.strip(),
        "approved_at": approved_at,
        "preview_contract": {"path": str(contract_path), "sha256": sha256_file(contract_path)},
        "approved_snapshot": {"path": str(snapshot_path), "sha256": sha256_file(snapshot_path)},
        "integrity_notice": "SHA-256 detects drift only; this receipt is not identity authentication or encryption.",
    }
    payload["integrity_sha256"] = _stable_hash(payload)
    authorized_root = Path(os.path.abspath(authorized_root))
    output_lexical = Path(os.path.abspath(output_path))
    try:
        target = safe_generated_target(authorized_root, output_lexical.relative_to(authorized_root))
    except (ValueError, SafeGeneratedOutputError) as error:
        raise NleOutroError(str(error)) from error
    _write_json(target, payload)
    return payload


def validate_modular_outro_render_approval(path: Path) -> list[str]:
    try:
        payload = read_json(Path(path))
    except (OSError, ValueError, json.JSONDecodeError):
        return ["modular outro render approval is unreadable"]
    if not isinstance(payload, Mapping):
        return ["modular outro render approval must be an object"]
    errors: list[str] = []
    if (
        payload.get("schema_version") != 1
        or payload.get("kind") != "manual_nle_outro_render_approval"
        or payload.get("status") != "approved"
        or payload.get("actor") != "HongRun"
        or payload.get("decision") != "approve_render"
        or payload.get("scope") != ["four_second_transparent_outro_layer", "reference_composite"]
    ):
        errors.append("modular outro render approval identity/scope is invalid")
    for key in ("preview_contract", "approved_snapshot"):
        ref = payload.get(key)
        if not isinstance(ref, Mapping) or not isinstance(ref.get("path"), str):
            errors.append(f"modular outro approval {key} is invalid")
            continue
        ref_path = Path(ref["path"])
        if not ref_path.is_file() or ref.get("sha256") != sha256_file(ref_path):
            errors.append(f"modular outro approval {key} is stale")
    contract = payload.get("preview_contract")
    if isinstance(contract, Mapping) and isinstance(contract.get("path"), str):
        errors.extend(validate_modular_outro_contract(Path(contract["path"])))
    try:
        expected = _stable_hash(payload)
    except (TypeError, ValueError):
        errors.append("modular outro render approval is not canonical")
    else:
        if payload.get("integrity_sha256") != expected:
            errors.append("modular outro render approval integrity is stale")
    return errors


def materialize_modular_outro_render_receipt(
    *, approval_path: Path, source_contract_path: Path, approved_reference_path: Path,
    overlay_path: Path, reference_path: Path, alpha_evidence_path: Path,
    output_path: Path, authorized_root: Path,
) -> dict[str, Any]:
    """Bind approved appearance to the verified transparent and reference renders."""
    approval_path = Path(approval_path).resolve()
    source_contract_path = Path(source_contract_path).resolve()
    approved_reference_path = Path(approved_reference_path).resolve()
    overlay_path = Path(overlay_path).resolve()
    reference_path = Path(reference_path).resolve()
    alpha_evidence_path = Path(alpha_evidence_path).resolve()
    approval_errors = validate_modular_outro_render_approval(approval_path)
    if approval_errors:
        raise NleOutroError("modular outro approval is stale:\n- " + "\n- ".join(approval_errors))
    contract_errors = validate_modular_outro_contract(source_contract_path)
    if contract_errors:
        raise NleOutroError("modular outro render source is stale:\n- " + "\n- ".join(contract_errors))
    for candidate in (approved_reference_path, overlay_path, reference_path, alpha_evidence_path):
        if not candidate.is_file():
            raise NleOutroError("modular outro render artifact is missing")
    if sha256_file(approved_reference_path) != sha256_file(reference_path):
        raise NleOutroError("modular outro reference differs from the approved preview")
    contract = read_json(source_contract_path)
    canvas = contract["canvas"]
    from nle_layer_materializer import _probe_video, _run, validate_alpha_evidence
    reference_probe = _probe_video(reference_path)
    if (
        reference_probe["width"] != canvas["width"]
        or reference_probe["height"] != canvas["height"]
        or abs(reference_probe["duration_seconds"] - contract["duration_seconds"]) > 0.05
        or abs(reference_probe["frame_rate"] - contract["frame_rate"]) > 0.001
    ):
        raise NleOutroError("modular outro reference media differs from its contract")
    try:
        _run(["ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(reference_path),
              "-map", "0:v:0", "-f", "null", os.devnull], timeout=180)
    except (OSError, RuntimeError, subprocess.SubprocessError) as error:
        raise NleOutroError("modular outro reference full decode failed") from error
    alpha_payload = read_json(alpha_evidence_path)
    alpha_probe = alpha_payload.get("probe") if isinstance(alpha_payload, Mapping) else None
    expected_video = {
        "codec_name": alpha_probe.get("codec_name") if isinstance(alpha_probe, Mapping) else None,
        "profile": alpha_probe.get("profile") if isinstance(alpha_probe, Mapping) else None,
        "width": canvas["width"], "height": canvas["height"],
        "pixel_format": alpha_probe.get("pixel_format") if isinstance(alpha_probe, Mapping) else None,
        "alpha_status": "verified",
        "decode_receipt": {"path": str(alpha_evidence_path), "sha256": sha256_file(alpha_evidence_path)},
    }
    alpha_errors = validate_alpha_evidence(
        alpha_evidence_path, overlay=overlay_path, expected_video=expected_video,
        expected_duration=float(contract["duration_seconds"]),
        expected_frame_rate=float(contract["frame_rate"]),
    )
    if alpha_errors:
        raise NleOutroError("modular outro alpha evidence is stale:\n- " + "\n- ".join(alpha_errors))
    authorized_root = Path(os.path.abspath(authorized_root))
    output_lexical = Path(os.path.abspath(output_path))
    try:
        target = safe_generated_target(authorized_root, output_lexical.relative_to(authorized_root))
    except (ValueError, SafeGeneratedOutputError) as error:
        raise NleOutroError(str(error)) from error
    rights_dir = safe_generated_directory(authorized_root, target.parent.relative_to(authorized_root) / "rights")
    rights: dict[str, dict[str, str]] = {}
    for role, asset in (("outro_overlay", overlay_path), ("outro_reference", reference_path)):
        rights_path = safe_generated_target(rights_dir, Path(f"{role}.json"))
        _write_json(rights_path, _rights_payload(
            asset_path=asset, asset_sha256=sha256_file(asset), role=role,
            rights_basis="user-approved project-generated HongRun modular outro render",
        ))
        rights[role] = {"path": str(rights_path), "sha256": sha256_file(rights_path)}
    payload = {
        "schema_version": 1,
        "kind": "manual_nle_outro_render_receipt",
        "status": "pass",
        "approval": {"path": str(approval_path), "sha256": sha256_file(approval_path)},
        "source_contract": {"path": str(source_contract_path), "sha256": sha256_file(source_contract_path)},
        "approved_reference": {"path": str(approved_reference_path), "sha256": sha256_file(approved_reference_path)},
        "overlay": {"path": str(overlay_path), "sha256": sha256_file(overlay_path)},
        "reference": {"path": str(reference_path), "sha256": sha256_file(reference_path)},
        "alpha_evidence": {"path": str(alpha_evidence_path), "sha256": sha256_file(alpha_evidence_path)},
        "rights": rights,
        "canvas": dict(canvas),
        "duration_seconds": float(contract["duration_seconds"]),
        "frame_rate": float(contract["frame_rate"]),
        "full_decode": True,
        "approved_appearance_exact_sha256_match": True,
    }
    payload["integrity_sha256"] = _stable_hash(payload)
    _write_json(target, payload)
    return payload


def archive_modular_outro_project(
    *, source_root: Path, archive_path: Path, authorized_root: Path,
) -> dict[str, Any]:
    """Create a deterministic editable-source archive plus current rights receipt."""
    source_root = Path(source_root).resolve()
    contract_path = source_root / "outro-contract.json"
    errors = validate_modular_outro_contract(contract_path)
    if errors:
        raise NleOutroError("modular outro source cannot be archived:\n- " + "\n- ".join(errors))
    contract = read_json(contract_path)
    members: list[Path] = [contract_path]
    for row in contract["files"]:
        relative = Path(row["path"])
        member = (source_root / relative).resolve()
        if not member.is_relative_to(source_root) or not member.is_file():
            raise NleOutroError("modular outro archive member is outside the source project")
        members.append(member)
    members = sorted(set(members), key=lambda path: path.relative_to(source_root).as_posix())
    authorized_root = Path(os.path.abspath(authorized_root))
    archive_lexical = Path(os.path.abspath(archive_path))
    try:
        relative_archive = archive_lexical.relative_to(authorized_root)
        target = safe_generated_target(authorized_root, relative_archive)
    except (ValueError, SafeGeneratedOutputError) as error:
        raise NleOutroError(str(error)) from error
    temporary = safe_generated_target(
        authorized_root,
        relative_archive.parent / f".{relative_archive.name}.tmp-{uuid.uuid4().hex}",
    )
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for member in members:
                relative = member.relative_to(source_root).as_posix()
                info = zipfile.ZipInfo(relative, date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.external_attr = 0o100644 << 16
                archive.writestr(info, member.read_bytes())
        atomic_replace_file(temporary, target)
    finally:
        if temporary.exists():
            temporary.unlink(missing_ok=True)
    rights_path = safe_generated_target(
        authorized_root,
        relative_archive.with_name(relative_archive.name + ".rights.json"),
    )
    rights_basis = "project-owned deterministic HongRun modular outro source"
    _write_json(rights_path, _rights_payload(
        asset_path=target,
        asset_sha256=sha256_file(target),
        role="outro_source_project",
        rights_basis=rights_basis,
    ))
    return {
        "path": str(target),
        "rights_status": "redistribution_authorized",
        "provenance": rights_basis,
        "rights_evidence": {"path": str(rights_path), "sha256": sha256_file(rights_path)},
    }


def build_modular_outro_project(
    *, output_root: Path, authorized_root: Path, profile_path: Path,
    gsap_runtime_path: Path, width: int, height: int, frame_rate: float,
    duration_seconds: float, copy: Mapping[str, Any],
) -> dict[str, Any]:
    if any(isinstance(value, bool) or not isinstance(value, int) or value < 1 for value in (width, height)):
        raise NleOutroError("modular outro canvas is invalid")
    if not _finite(frame_rate, positive=True) or not _finite(duration_seconds, positive=True):
        raise NleOutroError("modular outro timing is invalid")
    duration = float(duration_seconds)
    if not 3.0 <= duration <= 6.0:
        raise NleOutroError("modular outro duration must be between 3 and 6 seconds")
    profile_path = Path(profile_path).resolve()
    runtime_path = Path(gsap_runtime_path).resolve()
    if not profile_path.is_file() or not runtime_path.is_file():
        raise NleOutroError("modular outro profile/runtime authority is missing")
    _profile, tokens = _profile_tokens(profile_path)
    copy_payload = _copy_payload(copy)
    authorized_root = Path(os.path.abspath(authorized_root))
    output_root = Path(os.path.abspath(output_root))
    try:
        relative = output_root.relative_to(authorized_root)
        parent = safe_generated_directory(authorized_root, relative.parent)
    except (ValueError, SafeGeneratedOutputError) as error:
        raise NleOutroError(str(error)) from error
    if output_root.exists() and (
        output_root.is_symlink()
        or bool(getattr(os.path, "isjunction", lambda _path: False)(output_root))
    ):
        raise NleOutroError("modular outro output root is redirected")
    staging = safe_generated_directory(
        authorized_root, relative.parent / f".{output_root.name}.staging-{uuid.uuid4().hex}",
    )
    try:
        runtime_target = safe_generated_target(staging, Path("assets/gsap-3.14.2.min.js"))
        atomic_replace_file(runtime_path, runtime_target)
        for name, svg in _ICON_SVGS.items():
            atomic_write_text(safe_generated_target(staging, Path(f"icons/{name}.svg")), svg + "\n")
        timing_payload = {
            "schema_version": 1,
            "duration_seconds": duration,
            "phases": {
                "entrance": [0.0, 1.5], "hold": [1.5, max(1.5, duration - 0.62)],
                "exit": [max(1.5, duration - 0.62), duration],
            },
            "text_free_render_variables": {"showCopy": False, "showBackground": False},
            "reference_render_variables": {"showCopy": True, "showBackground": True},
        }
        copy_and_timing = {
            "schema_version": 1,
            "kind": "manual_nle_outro_copy_and_timing",
            "direction": _DIRECTION,
            "copy": copy_payload,
            "timing": timing_payload,
            "native_text_recreation_required": True,
        }
        copy_path = safe_generated_target(staging, Path("copy.json")); _write_json(copy_path, copy_and_timing)
        timing_path = safe_generated_target(staging, Path("timing.json")); _write_json(timing_path, timing_payload)
        frame_path = safe_generated_target(staging, Path("frame.md"))
        atomic_write_text(frame_path, (
            "---\n"
            f"colors:\n  canvas: '{tokens['canvas']}'\n  ink: '{tokens['ink']}'\n"
            f"  mint: '{tokens['mint']}'\n  cyan: '{tokens['cyan']}'\n"
            f"  warm: '{tokens['warm']}'\n  violet: '{tokens['violet']}'\n"
            f"typography:\n  primary: '{tokens['font']}'\n"
            "---\n\n# HongRun luminous intelligence modular CTA\n\n"
            "Text-free render is the editable NLE layer. Reference copy is recreated as native NLE text.\n"
        ))
        index_path = safe_generated_target(staging, Path("index.html"))
        atomic_write_text(index_path, _html_document(
            width=width, height=height, duration=duration, frame_rate=float(frame_rate),
            copy=copy_payload, tokens=tokens,
        ))
        motion_path = safe_generated_target(staging, Path("index.motion.json"))
        _write_json(motion_path, {
            "duration": duration,
            "assertions": [
                {"kind": "appearsBy", "selector": "#core", "bySec": 0.9},
                {"kind": "before", "a": "#core", "b": "#action-0"},
                {"kind": "staysInFrame", "selector": "#module"},
                {"kind": "keepsMoving", "withinSelector": "#module", "maxStaticSec": 1.4},
            ],
        })
        package_path = safe_generated_target(staging, Path("package.json"))
        _write_json(package_path, {
            "name": "hongrun-modular-cta-outro", "private": True, "type": "module",
            "scripts": {
                "check": "npx --yes hyperframes@0.8.4 check --strict",
                "preview": "npx --yes hyperframes@0.8.4 preview",
                "render": "npx --yes hyperframes@0.8.4 render",
            },
        })
        hyperframes_path = safe_generated_target(staging, Path("hyperframes.json"))
        _write_json(hyperframes_path, {
            "$schema": "https://hyperframes.heygen.com/schema/hyperframes.json",
            "registry": "https://raw.githubusercontent.com/heygen-com/hyperframes/main/registry",
            "paths": {"blocks": "compositions", "components": "compositions/components", "assets": "assets"},
            "authoringSkill": "motion-graphics",
        })

        package_assets: dict[str, Any] = {"outro_icon": []}
        rights_basis = "project-owned deterministic HongRun modular outro source"
        asset_specs = [("outro_copy", copy_path)] + [
            ("outro_icon", staging / "icons" / f"{name}.svg") for name in _ICON_SVGS
        ]
        for index, (role, source) in enumerate(asset_specs):
            rights_path = safe_generated_target(
                staging, Path("rights") / f"{role}-{index}.json",
            )
            final_source = output_root / source.relative_to(staging)
            _write_json(rights_path, _rights_payload(
                asset_path=final_source, asset_sha256=sha256_file(source), role=role,
                rights_basis=rights_basis,
            ))
            record = {
                "path": str(final_source),
                "rights_status": "redistribution_authorized",
                "provenance": rights_basis,
                "rights_evidence": {
                    "path": str(output_root / rights_path.relative_to(staging)),
                    "sha256": sha256_file(rights_path),
                },
            }
            if role == "outro_icon":
                package_assets[role].append(record)
            else:
                package_assets[role] = record

        inventory_paths = sorted(path for path in staging.rglob("*") if path.is_file())
        contract = {
            "schema_version": 1,
            "kind": "manual_nle_modular_outro",
            "status": "preview_pending",
            "direction": _DIRECTION,
            "canvas": {"width": width, "height": height},
            "frame_rate": float(frame_rate),
            "duration_seconds": duration,
            "render_authorized": False,
            "profile": {"path": str(profile_path), "sha256": sha256_file(profile_path)},
            "runtime": {"path": "assets/gsap-3.14.2.min.js", "sha256": sha256_file(runtime_target)},
            "copy": copy_payload,
            "package_assets": package_assets,
            "files": [_file_ref(path, staging) for path in inventory_paths],
            "implementation": {"path": str(_IMPLEMENTATION), "sha256": sha256_file(_IMPLEMENTATION)},
        }
        contract["integrity_sha256"] = _stable_hash(contract)
        contract_path = safe_generated_target(staging, Path("outro-contract.json"))
        _write_json(contract_path, contract)
        errors = validate_modular_outro_contract(contract_path)
        if errors:
            raise NleOutroError("modular outro contract failed:\n- " + "\n- ".join(errors))
        _replace_directory(staging, output_root)
        return read_json(output_root / "outro-contract.json")
    except Exception:
        if staging.exists():
            shutil.rmtree(staging, ignore_errors=True)
        raise
