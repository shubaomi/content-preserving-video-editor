#!/usr/bin/env python3
"""Finalize an already-rendered real WP6 portrait Style Reel review package.

This command never renders media. It binds existing HyperFrames projects,
caption-last review media, phase snapshots, semantic decisions, and audio
audition evidence into one pending HongRun review dashboard.
"""
from __future__ import annotations

import argparse
import json
import math
import tempfile
from pathlib import Path
from typing import Any, Mapping

from PIL import Image, ImageChops, ImageStat

from director_contracts import read_json, sha256_file
from portrait_style_reel import (
    DIRECTIONS, PHASES, StyleReelError, _basis_hash, _file_ref, _full_decode,
    _probe_duration, _probe_signature, _semantic_projection,
    build_style_reel_review, generate_style_reel_dashboard,
    validate_style_reel_context,
)
from safe_generated_output import (
    atomic_replace_file, atomic_write_text, safe_generated_target,
)


DIRECTION_MEDIA = {
    "luminous_intelligence": "luminous-intelligence.mp4",
    "high_energy_creator": "high-energy-creator.mp4",
    "humanist_cinema": "humanist-cinema.mp4",
}
DIRECTION_QA = {
    "luminous_intelligence": "luminous-intelligence",
    "high_energy_creator": "high-energy-creator",
    "humanist_cinema": "humanist-cinema",
}
PHASE_SOURCE_NAMES = (
    "frame-00-at-0.7s.png", "frame-01-at-4.8s.png",
    "frame-02-at-9.2s.png", "frame-03-at-10.3s.png",
)


class Wp6ReviewError(ValueError):
    """Raised when existing real Style Reel evidence is incomplete or stale."""


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Wp6ReviewError(f"{label} must be a mapping")
    return value


def _write_json(root: Path, relative: Path, payload: Any) -> Path:
    target = safe_generated_target(root, relative)
    atomic_write_text(target, json.dumps(
        payload, ensure_ascii=False, indent=2, allow_nan=False,
    ) + "\n")
    return target.resolve()


def _mean_absolute_pixel_error(left: Path, right: Path) -> float:
    with Image.open(left) as left_image, Image.open(right) as right_image:
        lhs = left_image.convert("RGB")
        rhs = right_image.convert("RGB")
        if lhs.size != rhs.size:
            raise Wp6ReviewError(f"QA image dimensions differ: {left} / {right}")
        return sum(ImageStat.Stat(ImageChops.difference(lhs, rhs)).mean) / 3.0


def _semantic_rows(path: Path) -> list[Mapping[str, Any]]:
    payload = _mapping(read_json(path), "semantic brief")
    rows = payload.get("events")
    if not isinstance(rows, list) or any(not isinstance(row, Mapping) for row in rows):
        raise Wp6ReviewError("semantic brief events must be mappings")
    return rows


def _copy_phase_evidence(
    *, style_root: Path, direction_id: str, event_id: str,
) -> list[Path]:
    result: list[Path] = []
    for phase, source_name, timestamp in zip(
        PHASES, PHASE_SOURCE_NAMES, ("0.70", "4.80", "9.20", "10.30"), strict=True,
    ):
        source = style_root / "hyperframes" / direction_id / "phase-snapshots" / source_name
        baseline = style_root / "qa" / "final" / "baseline-captioned" / f"at-{timestamp}.png"
        candidate = (
            style_root / "qa" / "final" / DIRECTION_QA[direction_id]
            / f"at-{timestamp}.png"
        )
        if not source.is_file() or not baseline.is_file() or not candidate.is_file():
            raise Wp6ReviewError(
                f"missing HyperFrames or same-time phase evidence: {source} / {baseline} / {candidate}"
            )
        target = safe_generated_target(
            style_root, Path("phases") / direction_id / f"{event_id}-{phase}.png",
        )
        with Image.open(baseline) as baseline_image, Image.open(candidate) as candidate_image:
            lhs = baseline_image.convert("RGB")
            rhs = candidate_image.convert("RGB")
            if lhs.size != rhs.size:
                raise Wp6ReviewError(f"same-time phase evidence dimensions differ: {direction_id}")
            difference = ImageChops.difference(lhs, rhs).convert("L")
            isolation = difference.point(lambda value: 255 if value >= 18 else 0).convert("RGB")
            with tempfile.NamedTemporaryFile(
                dir=target.parent, suffix=".png", delete=False,
            ) as handle:
                temporary = Path(handle.name)
            try:
                isolation.save(temporary, format="PNG")
                atomic_replace_file(temporary, target)
            finally:
                temporary.unlink(missing_ok=True)
        result.append(target.resolve())
    return result


def _technical_evidence(
    *, style_root: Path, project_manifest: Mapping[str, Any],
    media_paths: Mapping[str, Path], baseline_path: Path, expected_duration: float,
) -> dict[str, Any]:
    baseline_signature = _probe_signature(baseline_path)
    baseline_decode = _full_decode(baseline_path)
    if baseline_decode:
        raise Wp6ReviewError("baseline full decode failed: " + "; ".join(baseline_decode))
    directions: list[dict[str, Any]] = []
    max_post_exit_mae = 0.0
    for direction_id in DIRECTIONS:
        media = media_paths[direction_id]
        decode_errors = _full_decode(media)
        if decode_errors:
            raise Wp6ReviewError(
                f"{direction_id} full decode failed: " + "; ".join(decode_errors)
            )
        duration = _probe_duration(media)
        if abs(duration - expected_duration) > 0.25:
            raise Wp6ReviewError(f"{direction_id} duration differs from confirmed window")
        if _probe_signature(media) != baseline_signature:
            raise Wp6ReviewError(f"{direction_id} stream signature differs from baseline")
        project_row = _mapping(
            _mapping(project_manifest.get("projects"), "HyperFrames projects").get(direction_id),
            f"{direction_id} HyperFrames project",
        )
        project = Path(str(project_row.get("project") or "")).resolve()
        index_path = project / "index.html"
        check_path = project / "check-strict.json"
        visual_render = next((project / "renders").glob("*-visual.mp4"), None)
        if (
            not index_path.is_file()
            or sha256_file(index_path) != project_row.get("index_sha256")
            or not check_path.is_file()
            or visual_render is None
        ):
            raise Wp6ReviewError(f"{direction_id} HyperFrames project evidence is incomplete")
        check = _mapping(read_json(check_path), f"{direction_id} HyperFrames check")
        if check.get("ok") is not True:
            raise Wp6ReviewError(f"{direction_id} HyperFrames check did not pass")
        post_exit: list[dict[str, Any]] = []
        for timestamp in ("10.30", "18.00"):
            baseline_qa = style_root / "qa" / "final" / "baseline-captioned" / f"at-{timestamp}.png"
            direction_qa = (
                style_root / "qa" / "final" / DIRECTION_QA[direction_id]
                / f"at-{timestamp}.png"
            )
            if not baseline_qa.is_file() or not direction_qa.is_file():
                raise Wp6ReviewError(f"{direction_id} post-exit QA snapshot is missing")
            mae = _mean_absolute_pixel_error(baseline_qa, direction_qa)
            max_post_exit_mae = max(max_post_exit_mae, mae)
            post_exit.append({
                "timestamp_seconds": float(timestamp),
                "baseline": _file_ref(baseline_qa), "candidate": _file_ref(direction_qa),
                "rgb_mae": round(mae, 6),
            })
        directions.append({
            "direction_id": direction_id, "media": _file_ref(media),
            "duration_seconds": round(duration, 6), "hyperframes_index": _file_ref(index_path),
            "hyperframes_check": _file_ref(check_path),
            "visual_render": _file_ref(visual_render), "post_exit": post_exit,
        })
    if max_post_exit_mae > 5.0:
        raise Wp6ReviewError(
            f"post-exit candidate differs materially from baseline: RGB MAE {max_post_exit_mae:.3f}"
        )
    return {
        "schema_version": 1, "status": "pass", "kind": "wp6_real_style_reel_technical_evidence",
        "confirmed_window": {
            "original_start_seconds": 83.86, "original_end_seconds": 122.44,
            "source_start_seconds": 17.71, "source_end_seconds": 56.29,
            "local_start_seconds": 0.0, "local_end_seconds": 38.58,
        },
        "baseline": _file_ref(baseline_path), "directions": directions,
        "checks": {
            "full_decode": True, "duration_alignment": True,
            "stream_signature": True, "hyperframes_checks": True,
            "post_exit_clean": True, "maximum_post_exit_rgb_mae": round(max_post_exit_mae, 6),
            "caption_last": True, "background_music": "disabled_for_common_basis",
        },
    }


def finalize_wp6_review(style_reel_root: Path) -> dict[str, Any]:
    style_root = style_reel_root.absolute()
    plan_path = style_root / "style-reel-plan.json"
    authority_path = style_root / "style-reel-authorities.json"
    projects_path = style_root / "wp6-hyperframes-projects.json"
    for path in (plan_path, authority_path, projects_path):
        if not path.is_file():
            raise Wp6ReviewError(f"required WP6 artifact is missing: {path}")
    plan = _mapping(read_json(plan_path), "Style Reel plan")
    authority = _mapping(read_json(authority_path), "Style Reel authority manifest")
    projects = _mapping(read_json(projects_path), "HyperFrames project manifest")
    basis = _mapping(plan.get("comparison_basis"), "Style Reel comparison basis")
    event_ids = list(basis.get("semantic_event_ids") or [])
    semantic_ref = _mapping(
        _mapping(authority.get("authorities"), "Style Reel authorities").get("semantic_brief"),
        "semantic brief authority",
    )
    semantic_path = Path(str(semantic_ref.get("path") or "")).resolve()
    semantic_rows = _semantic_rows(semantic_path)
    semantic_by_id = {str(row.get("id") or row.get("semantic_event_id") or ""): row for row in semantic_rows}
    if list(semantic_by_id) != event_ids:
        raise Wp6ReviewError("semantic event order differs from Style Reel plan")
    decisions = {event_id: str(semantic_by_id[event_id].get("decision") or "") for event_id in event_ids}
    render_ids = [event_id for event_id in event_ids if decisions[event_id] == "render"]
    if render_ids != ["life-halves-question"]:
        raise Wp6ReviewError("WP6 review expects exactly the confirmed render event")
    render_event = render_ids[0]

    media_paths = {
        direction: (style_root / "review-media" / DIRECTION_MEDIA[direction]).resolve()
        for direction in DIRECTIONS
    }
    baseline_path = (style_root / "review-media" / "baseline-captioned.mp4").resolve()
    for path in (baseline_path, *media_paths.values()):
        if not path.is_file():
            raise Wp6ReviewError(f"review media is missing: {path}")
    expected_duration = float(basis["end_seconds"]) - float(basis["start_seconds"])
    technical = _technical_evidence(
        style_root=style_root, project_manifest=projects, media_paths=media_paths,
        baseline_path=baseline_path, expected_duration=expected_duration,
    )
    technical_path = _write_json(style_root, Path("wp6-technical-evidence.json"), technical)

    phases: dict[str, list[Path]] = {}
    contracts: dict[str, Path] = {}
    recipes = {
        direction: str(_mapping(
            _mapping(projects.get("projects"), "HyperFrames projects").get(direction),
            f"{direction} project",
        ).get("recipe_id") or "")
        for direction in DIRECTIONS
    }
    direction_by_id = {
        str(row.get("direction_id") or ""): row
        for row in plan.get("directions") or [] if isinstance(row, Mapping)
    }
    for direction in DIRECTIONS:
        phases[direction] = _copy_phase_evidence(
            style_root=style_root, direction_id=direction, event_id=render_event,
        )
        contract = {
            "schema_version": 1, "direction_id": direction,
            "comparison_basis_sha256": _basis_hash(plan), "event_ids": event_ids,
            "event_decisions": [
                {"event_id": event_id, "decision": decisions[event_id]}
                for event_id in event_ids
            ],
            "event_recipes": [{"event_id": render_event, "recipe_id": recipes[direction]}],
            "structural_fingerprint": _mapping(
                direction_by_id.get(direction), f"{direction} plan direction",
            ).get("structural_fingerprint"),
            "phase_inventory": [
                {"event_id": render_event, "phase": phase, "evidence": _file_ref(path)}
                for phase, path in zip(PHASES, phases[direction], strict=True)
            ],
        }
        contracts[direction] = _write_json(
            style_root, Path("contracts") / f"{direction}.json", contract,
        )

    inventory = [{
        "direction_id": direction, "media": _file_ref(media_paths[direction]),
        "contract": _file_ref(contracts[direction]),
        "phase_evidence": [_file_ref(path) for path in phases[direction]],
    } for direction in DIRECTIONS]
    automated_report = {
        "schema_version": 1, "status": "pass", "plan": _file_ref(plan_path),
        "comparison_basis_sha256": _basis_hash(plan), "directions": inventory,
        "checks": {
            "full_decode": True, "duration_alignment": True, "stream_signature": True,
            "event_alignment": True, "phase_inventory": True,
        },
    }
    report_path = _write_json(style_root, Path("automated-report.json"), automated_report)
    review_path = style_root / "style-reel-review.json"
    build_style_reel_review(
        plan_path=plan_path, authority_manifest_path=authority_path,
        media_paths=media_paths, contract_paths=contracts,
        phase_evidence_paths=phases, automated_report_path=report_path,
        output=review_path, authorized_root=style_root,
    )

    audition_path = style_root / "auditions" / f"{render_event}-audition-receipt.json"
    audition = _mapping(read_json(audition_path), "render-event audition receipt")
    context_events: list[dict[str, Any]] = []
    for event_id in event_ids:
        semantic = semantic_by_id[event_id]
        row = {"event_id": event_id, **_semantic_projection(
            semantic, window_start=float(basis["start_seconds"]),
        )}
        row["decision"] = decisions[event_id]
        row["recipes"] = {
            direction: recipes[direction] if decisions[event_id] == "render" else None
            for direction in DIRECTIONS
        }
        if decisions[event_id] == "render":
            row["audio_auditions"] = {
                "voice_sfx_off": audition["voice_sfx_off"],
                "sfx_on": audition["sfx_on"], "receipt": _file_ref(audition_path),
            }
        else:
            row["audio_auditions"] = {
                "status": "not_applicable",
                "reason": (
                    f"{decisions[event_id]} preserves the original voice and source performance; "
                    "no additional SFX audition is authorized."
                ),
            }
        context_events.append(row)
    context = {
        "schema_version": 1, "plan": _file_ref(plan_path),
        "authority_manifest": _file_ref(authority_path), "review": _file_ref(review_path),
        "comparison_basis_sha256": _basis_hash(plan), "baseline_media": _file_ref(baseline_path),
        "baseline_duration_seconds": round(_probe_duration(baseline_path), 6),
        "events": context_events,
    }
    context_path = _write_json(style_root, Path("style-reel-context.json"), context)
    context_errors = validate_style_reel_context(
        context, plan_path=plan_path, authority_manifest_path=authority_path,
        review_path=review_path, contract_paths=contracts,
    )
    if context_errors:
        raise Wp6ReviewError("Style Reel context is invalid:\n- " + "\n- ".join(context_errors))
    dashboard_path = style_root / "review" / "style-reel-review.html"
    dashboard_manifest = generate_style_reel_dashboard(
        plan_path=plan_path, authority_manifest_path=authority_path,
        review_path=review_path, context_path=context_path,
        contract_paths=contracts, output=dashboard_path,
    )
    package = {
        "schema_version": 1, "status": "awaiting_user", "kind": "wp6_real_style_reel_review_package",
        "window_confirmation": _file_ref(style_root / "window-confirmation.json"),
        "technical_evidence": _file_ref(technical_path), "review": _file_ref(review_path),
        "context": _file_ref(context_path), "dashboard": dashboard_manifest["html"],
        "dashboard_manifest": _file_ref(dashboard_path.with_suffix(".manifest.json")),
        "contracts": {direction: _file_ref(path) for direction, path in contracts.items()},
        "full_video_render_authorized": False,
    }
    package_path = _write_json(style_root, Path("wp6-review-package.json"), package)
    return {
        **package, "package_path": package_path,
        "dashboard_path": dashboard_path.resolve(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--style-reel-root", required=True, type=Path)
    args = parser.parse_args()
    try:
        payload = finalize_wp6_review(args.style_reel_root)
    except (OSError, KeyError, TypeError, ValueError, StyleReelError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps({
        "status": "awaiting_user", "package": str(payload["package_path"]),
        "dashboard": str(payload["dashboard_path"]),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
