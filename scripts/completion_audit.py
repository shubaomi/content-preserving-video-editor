#!/usr/bin/env python3
"""Produce an evidence-backed audit of the director Goal acceptance criteria."""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

from aesthetic_qa import validate as validate_aesthetic_review
from audio_qa import validate as validate_audio_plan
from brand_motion_playbook import validate_playbook
from capability_registry import CAPABILITY_LEVELS, build_capability_inventory, build_toolchain_report
from director_contracts import (
    REQUIRED_VISUAL_FIELDS,
    VISUAL_VOCABULARY,
    load_project_context,
    read_json,
    sha256_file,
    validate_semantic_brief,
    validate_semantic_evidence_binding,
    validate_video_use_final_correctness,
    validate_visual_vocabulary_audit,
    visual_signature,
    write_json,
)
from correction_ledger import validate_ledger
from creative_review import validate_review as validate_creative_review
from clip_factory import validate_clip_manifest
from editorial_regression import validate_baseline, validate_regression
from localization_pipeline import validate_localization_manifest
from manual_finish import validate_handoff_manifest, validate_returned_final_qa
from podcast_pipeline import validate_podcast_manifest
from production_contract import validate_contract
from provider_governance import validate_cost_ledger, validate_decision_report
from fixture_acceptance import CHECK_NAMES, evaluate_suite
from keyframe_receipt import validate_keyframe_receipt, validate_renderer_export
from motion_contracts import DEFAULT_RECIPE_REGISTRY
from preview_render_parity import validate as validate_preview_render_parity
from six_media_acceptance import validate_manifest as validate_six_media_manifest
from test_acceptance_report import validate_report as validate_test_suite_report
from technical_qa import validate_report as validate_technical_report
from validate_platform_export import validate_bound_report as validate_platform_report
from visual_dynamics_qa import validate_report as validate_visual_dynamics_report
from current_golden_regression import validate_report as validate_current_golden_report
from representative_short_media import validate as validate_representative_short_media
from delivery_readiness import asset_is_required, validate_required_asset_readiness
from caption_treatment import validate_materialized as validate_caption_treatment


REQUIRED_FIXTURE_TYPES = {
    "landscape_screen_tutorial", "portrait_talking_head", "published_edit_polish",
    "two_person_interview", "noisy_audio_hotwords", "screen_camera_mixed",
}


def _required_asset_readiness_errors(
    project: dict[str, Any], stages: dict[str, Any],
) -> list[str]:
    return validate_required_asset_readiness(project, stages)


def _sample_structure_gate(
    project: dict[str, Any], visual_events: list[dict[str, Any]],
    signatures: set[tuple[str, ...]],
) -> bool:
    """Keep the legacy variety quota while MQE uses compiler decisions."""
    if project.get("motion_quality", {}).get("enabled") is True:
        return bool(visual_events)
    return len(visual_events) >= 4 and len(signatures) >= 4


def _stable_hash(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _safe_int(value: Any, default: int = -1) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _motion_render_evidence_errors(
    *, root: Path, project: dict[str, Any], full_project: Path,
) -> list[str]:
    """Recompute the Motion Quality full-project renderer evidence gate."""
    if project.get("motion_quality", {}).get("enabled") is not True:
        return []
    contract_path = root / "work" / "director" / "motion-design" / "full" / "motion-design-contract.json"
    evidence_contract_path = full_project / "renderer-evidence-contract.json"
    project_manifest_path = full_project / "renderer-project-manifest.json"
    renderer_export_path = full_project / "renderer-export.json"
    receipt_dir = full_project / "keyframe-receipts"
    parity_path = root / "work" / "director" / "full-qa" / "preview-render-parity.json"
    storyboard_path = full_project / "storyboard.json"
    source_value = str((project.get("source") or {}).get("path") or "")
    source_path = Path(source_value)
    if source_value and not source_path.is_absolute():
        source_path = root / source_path
    required = [
        contract_path, evidence_contract_path, project_manifest_path,
        renderer_export_path, parity_path, storyboard_path, source_path,
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if not receipt_dir.is_dir():
        missing.append(str(receipt_dir))
    if missing:
        return ["motion render evidence is missing: " + ", ".join(missing)]

    errors: list[str] = []
    try:
        motion_contract = read_json(contract_path)
        evidence_contract = read_json(evidence_contract_path)
        renderer_export = read_json(renderer_export_path)
        storyboard = read_json(storyboard_path)
    except (OSError, ValueError, json.JSONDecodeError) as error:
        return [f"motion render evidence JSON is invalid: {error}"]
    if not all(isinstance(value, dict) for value in (
        motion_contract, evidence_contract, renderer_export, storyboard,
    )):
        return ["motion render evidence JSON roots must be mappings"]

    if evidence_contract.get("schema_version") != 1 or evidence_contract.get("owner") != "director":
        errors.append("renderer evidence contract metadata is invalid")
    expected_inputs = {
        "project_entrypoint": full_project / "index.html",
        "storyboard": storyboard_path,
        "motion_design_contract": contract_path,
        "source_media": source_path,
    }
    for name, expected_path in expected_inputs.items():
        row = (evidence_contract.get(name) or {})
        expected_path = expected_path.resolve()
        if Path(str(row.get("path") or "")).resolve() != expected_path:
            errors.append(f"renderer evidence contract {name} path is stale")
        if not expected_path.is_file() or row.get("sha256") != (
            sha256_file(expected_path) if expected_path.is_file() else None
        ):
            errors.append(f"renderer evidence contract {name} hash is stale")
    expected_outputs = {
        "renderer_export": renderer_export_path,
        "renderer_project_manifest": project_manifest_path,
        "keyframe_receipt_directory": receipt_dir,
        "preview_render_parity": parity_path,
    }
    for name, expected_path in expected_outputs.items():
        actual = Path(str((evidence_contract.get("outputs") or {}).get(name) or ""))
        if actual.resolve() != expected_path.resolve():
            errors.append(f"renderer evidence contract {name} output is stale")

    errors.extend(validate_renderer_export(
        renderer_export,
        project_artifact=project_manifest_path,
        motion_design_contract_path=contract_path,
    ))
    expected_ids = [str(value) for value in motion_contract.get("selected_event_ids") or []]
    receipt_paths: dict[str, Path] = {}
    for path in sorted(receipt_dir.glob("*.json")):
        try:
            event_id = str(read_json(path).get("event_id") or "")
        except (OSError, ValueError, json.JSONDecodeError):
            errors.append(f"invalid keyframe receipt JSON: {path}")
            continue
        if not event_id or event_id in receipt_paths:
            errors.append(f"duplicate or missing keyframe receipt event_id: {path}")
            continue
        receipt_paths[event_id] = path.resolve()
    if set(receipt_paths) != set(expected_ids):
        errors.append("keyframe receipt event set differs from compiler-selected events")

    bindings_by_id: dict[str, Path] = {}
    binding_dir = root / "work" / "director" / "target-bindings" / "full"
    for path in sorted(binding_dir.glob("*.json")):
        try:
            binding_id = str(read_json(path).get("binding_id") or "")
        except (OSError, ValueError, json.JSONDecodeError):
            continue
        if binding_id:
            bindings_by_id[binding_id] = path.resolve()
    opportunities = {
        str(row.get("semantic_event_id")): row
        for row in motion_contract.get("opportunities") or [] if isinstance(row, dict)
    }
    for event_id in expected_ids:
        receipt_path = receipt_paths.get(event_id)
        if receipt_path is None:
            continue
        opportunity = opportunities.get(event_id) or {}
        binding_ids = [str(value) for value in opportunity.get("target_binding_ids") or []]
        missing_bindings = [value for value in binding_ids if value not in bindings_by_id]
        if missing_bindings:
            errors.append(f"{event_id}: target bindings are missing: {', '.join(missing_bindings)}")
            continue
        errors.extend(
            f"{event_id}: {error}" for error in validate_keyframe_receipt(
                read_json(receipt_path),
                motion_design_contract_path=contract_path,
                recipe_registry_path=DEFAULT_RECIPE_REGISTRY,
                target_binding_paths=[bindings_by_id[value] for value in binding_ids],
                renderer_export_path=renderer_export_path,
                parity_path=parity_path,
                maximum_caption_overlap_ratio=0.0,
                minimum_composite_contrast_ratio=4.5,
                maximum_connector_error_pixels=4.0,
            )
        )
    errors.extend(validate_preview_render_parity(
        read_json(parity_path), storyboard,
        configured_tolerances=(
            (project.get("qa") or {}).get("preview_render_parity") or {}
        ).get("tolerances") or {},
        expected_bindings={
            "project_artifact": project_manifest_path,
            "motion_design_contract": contract_path,
            "source_media": source_path,
        },
        keyframe_receipt_paths=receipt_paths,
    ))
    return errors


def _cover_review_errors(review: dict[str, Any], cover_hash: str) -> list[str]:
    errors = []
    if review.get("status") != "pass":
        errors.append("cover review status is not pass")
    if review.get("topic_relevant") is not True:
        errors.append("cover review topic relevance is missing")
    if review.get("natural_expression_and_energy") is not True:
        errors.append("cover review composition or energy is missing")
    if review.get("cover_sha256") != cover_hash:
        errors.append("cover review hash is stale")
    if review.get("identity_applicable", True) is not False and (
        review.get("identity_approved_by_user") is not True
        or _safe_int(review.get("identity_reference_count"), 0) < 2
    ):
        errors.append("cover identity evidence or user approval is incomplete")
    return errors


def _row(status: str, finding: str, evidence: list[Path]) -> dict[str, Any]:
    return {
        "status": status,
        "finding": finding,
        "evidence": [str(path.resolve()) for path in evidence if path.exists()],
    }


def _artifact_record_errors(stages: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for stage, row in stages.items():
        if row.get("status") != "complete":
            continue
        records = row.get("artifact_records") or []
        declared = {str(Path(str(path)).resolve()) for path in row.get("artifacts") or []}
        recorded = {str(Path(str(record.get("path", ""))).resolve()) for record in records}
        if not records:
            errors.append(f"{stage} has no hash-bound artifact records")
            continue
        if not declared or declared != recorded:
            errors.append(f"{stage} artifacts and hash records do not match")
        for record in records:
            path = Path(str(record.get("path", "")))
            if not path.is_file():
                errors.append(f"{stage} artifact is missing: {path}")
                continue
            stat = path.stat()
            if (
                record.get("available") is not True
                or record.get("sha256") != sha256_file(path)
                or record.get("size") != stat.st_size
            ):
                errors.append(f"{stage} artifact record is stale: {path}")
    return errors


def _input_fingerprint_errors(
    state: dict[str, Any], project_file: Path, source_video: Path,
) -> list[str]:
    errors: list[str] = []
    records = state.get("input_fingerprints") or {}
    for name, path in (("project_file", project_file), ("source_video", source_video)):
        record = records.get(name) or {}
        if not path.is_file():
            errors.append(f"{name} is missing")
            continue
        stat = path.stat()
        if (
            record.get("path") != str(path.resolve())
            or record.get("available") is not True
            or record.get("size") != stat.st_size
            or record.get("sha256") != sha256_file(path)
        ):
            errors.append(f"{name} fingerprint is missing or stale")
    return errors


def _stage_binds_artifacts(
    stages: dict[str, Any], stage: str, required: list[Path],
) -> bool:
    records = (stages.get(stage) or {}).get("artifact_records") or []
    bound = {str(Path(str(row.get("path", ""))).resolve()) for row in records}
    return all(path.is_file() and str(path.resolve()) in bound for path in required)


def _review_evidence_files(review: dict[str, Any]) -> list[Path]:
    values: list[Any] = []
    for phases in (review.get("snapshots") or {}).values():
        if isinstance(phases, dict):
            values.extend(phases.values())
    for row in (review.get("criteria") or {}).values():
        if isinstance(row, dict):
            values.extend(row.get("evidence") or [])
    for row in [
        *(review.get("connector_geometry") or {}).values(),
        *(review.get("target_region_geometry") or {}).values(),
    ]:
        if isinstance(row, dict):
            values.append(row.get("evidence"))
    for row in (review.get("composite_contrast") or {}).values():
        if isinstance(row, dict):
            values.extend((row.get("composite_evidence"), row.get("source_evidence")))
    paths: set[Path] = set()
    for value in values:
        if not value:
            continue
        record = value if isinstance(value, dict) else {"path": value}
        if record.get("path"):
            path = Path(str(record["path"])).resolve()
            if path.is_file():
                paths.add(path)
    return sorted(paths)


def _technical_report_errors(report_path: Path, output: Path) -> list[str]:
    if not report_path.is_file():
        return ["technical media report is missing"]
    return validate_technical_report(read_json(report_path), output)


def _final_caption_delivery_errors(
    plan_path: Path, captions_path: Path, *, input_mode: str,
    caption_disabled: bool = False,
    caption_treatment_options: dict[str, Any] | None = None,
    caption_canvas: dict[str, Any] | None = None,
) -> list[str]:
    if not plan_path.is_file():
        return ["final compose caption delivery plan is missing"]
    try:
        plan = read_json(plan_path)
    except (OSError, json.JSONDecodeError):
        return ["final compose caption delivery plan is unreadable or malformed"]
    if not isinstance(plan, dict):
        return ["final compose caption delivery plan must be an object"]
    delivery = plan.get("caption_delivery")
    if not isinstance(delivery, dict):
        return ["final compose caption delivery must be an object"]
    if caption_disabled:
        return [] if delivery.get("mode") == "disabled_by_project" else [
            "final compose caption delivery does not match the explicit disabled policy"
        ]
    if input_mode == "preserve" or (
        input_mode == "polish_existing" and delivery.get("mode") == "burned_in_last"
    ):
        errors: list[str] = []
        if not captions_path.is_file():
            errors.append("video-use master.srt is missing from final caption delivery")
            return errors
        if delivery.get("mode") != "burned_in_last":
            errors.append("source-first final compose did not burn captions last")
        source = Path(str(delivery.get("source") or "")).resolve()
        treatment_enabled = (
            isinstance(caption_treatment_options, dict)
            and caption_treatment_options.get("enabled") is True
            and caption_treatment_options.get("mode") == "semantic_emphasis"
        )
        treatment_disabled = (
            caption_treatment_options is None
            or (
                isinstance(caption_treatment_options, dict)
                and caption_treatment_options.get("enabled") is False
                and caption_treatment_options.get("mode") == "plain"
            )
        )
        if not treatment_enabled and not treatment_disabled:
            errors.append("caption treatment project configuration is invalid")
        if source == captions_path.resolve():
            if treatment_enabled:
                errors.append("enabled semantic caption treatment did not deliver canonical ASS")
            if delivery.get("source_sha256") != sha256_file(captions_path):
                errors.append("final caption delivery source hash is stale")
        else:
            authority = delivery.get("text_authority")
            treatment_plan = delivery.get("treatment_plan")
            canonical_dir = plan_path.parent / "caption-treatment" / "full"
            canonical_ass = canonical_dir / "master.ass"
            canonical_plan = canonical_dir / "caption-emphasis-plan.json"
            styled_source_valid = (
                source == canonical_ass.resolve()
                and source.suffix.lower() == ".ass"
                and source.is_file()
            )
            if not styled_source_valid:
                errors.append("final caption delivery source path is stale")
                errors.append("final caption delivery source hash is stale")
            elif delivery.get("source_sha256") != sha256_file(source):
                errors.append("final caption delivery source hash is stale")
            if (
                not isinstance(authority, dict)
                or authority.get("path") != str(captions_path.resolve())
                or authority.get("sha256") != sha256_file(captions_path)
            ):
                errors.append("styled caption delivery lacks the current master.srt text authority")
            if (
                not isinstance(treatment_plan, dict)
                or treatment_plan.get("path") != str(canonical_plan.resolve())
                or not canonical_plan.is_file()
                or treatment_plan.get("sha256") != sha256_file(canonical_plan)
            ):
                errors.append("styled caption delivery lacks the canonical current treatment plan")
            elif styled_source_valid:
                if (
                    not isinstance(caption_treatment_options, dict)
                    or caption_treatment_options.get("enabled") is not True
                    or caption_treatment_options.get("mode") != "semantic_emphasis"
                    or not isinstance(caption_canvas, dict)
                ):
                    errors.append("styled caption treatment lacks current project configuration")
                else:
                    errors.extend(validate_caption_treatment(
                        plan_path=canonical_plan,
                        ass_path=canonical_ass,
                        expected_master_srt=captions_path,
                        expected_captions=captions_path.parent / "captions.json",
                        expected_semantic_brief=plan_path.parent / "full-semantic-brief.json",
                        expected_canvas=caption_canvas,
                        expected_options=caption_treatment_options,
                    ))
        raw_argv = plan.get("argv")
        if not isinstance(raw_argv, list) or any(not isinstance(value, str) for value in raw_argv):
            errors.append("final compose argv must be a list of strings")
            argv: list[str] = []
        else:
            argv = raw_argv
        caption_filter_path = source.resolve().as_posix().replace(":", "\\:")
        caption_filter_path = caption_filter_path.replace("'", "\\'")
        expected_filter = f"subtitles=filename='{caption_filter_path}':charenc=UTF-8"
        vf_indexes = [index for index, value in enumerate(argv) if value == "-vf"]
        subtitle_filters = [value for value in argv if "subtitles=" in value]
        canonical_filter_bound = (
            len(vf_indexes) == 1
            and vf_indexes[0] + 1 < len(argv)
            and argv[vf_indexes[0] + 1] == expected_filter
            and subtitle_filters == [expected_filter]
        )
        if not canonical_filter_bound:
            errors.append("final compose command lacks the canonical subtitles filter")
        return errors
    if delivery.get("mode") not in {"preserve_verified_existing", "burned_in_last"}:
        return ["polish-existing final compose lacks an explicit caption delivery decision"]
    return []


def _platform_report_errors(report_path: Path, output: Path, cover: Path) -> list[str]:
    if not report_path.is_file():
        return ["platform report is missing"]
    return validate_platform_report(read_json(report_path), output, cover)


def _full_hyperframes_errors(
    root: Path, full_project: Path, project: dict[str, Any], commands_path: Path,
) -> list[str]:
    errors: list[str] = []
    storyboard_path = full_project / "storyboard.json"
    vocabulary_path = full_project / "visual-vocabulary-audit.json"
    check_path = root / "full-qa" / "hyperframes-check.json"
    check_receipt_path = root / "full-qa" / "hyperframes-check-receipt.json"
    review_path = root / "full-qa" / "snapshot-review.json"
    parity_path = root / "full-qa" / "preview-render-parity.json"
    evidence_path = root / "full-qa" / "verified-evidence.json"
    required = [storyboard_path, vocabulary_path, commands_path, check_path, check_receipt_path,
                review_path, parity_path, evidence_path]
    missing = [path for path in required if not path.is_file()]
    if missing:
        return ["full HyperFrames evidence is missing: " + ", ".join(map(str, missing))]
    check = read_json(check_path)
    check_receipt = read_json(check_receipt_path)
    toolchain_path = root / "toolchain-compatibility.json"
    check_command = (read_json(commands_path).get("check") or {})
    receipt_bindings = {
        "storyboard_sha256": storyboard_path,
        "visual_vocabulary_sha256": vocabulary_path,
        "commands_sha256": commands_path,
        "toolchain_sha256": toolchain_path,
        "check_report_sha256": check_path,
        "stdout_sha256": Path(str(check_receipt.get("stdout_log", ""))),
        "stderr_sha256": Path(str(check_receipt.get("stderr_log", ""))),
    }
    if (
        check_receipt.get("owner") != "director"
        or check_receipt.get("capability") != "hyperframes_check"
        or check_receipt.get("status") != "pass"
        or _safe_int(check_receipt.get("exit_code")) != 0
        or check_receipt.get("command_sha256") != _stable_hash(check_command.get("argv") or [])
        or check_receipt.get("cwd") != str(Path(str(check_command.get("cwd", ""))).resolve())
        or any(not path.is_file() or check_receipt.get(field) != sha256_file(path)
               for field, path in receipt_bindings.items())
    ):
        errors.append("HyperFrames strict-check execution receipt is missing or stale")
    errors.extend(validate_visual_vocabulary_audit(
        read_json(vocabulary_path), read_json(storyboard_path), full_video=True,
        decision_complete=project.get("motion_quality", {}).get("enabled") is True,
    ))
    if check.get("ok") is not True:
        errors.append("full HyperFrames strict check is not passing")
    for section in ("lint", "runtime", "layout", "motion", "contrast"):
        row = check.get(section) or {}
        if row.get("ok") is not True or _safe_int(row.get("errorCount")) != 0:
            errors.append(f"full HyperFrames {section} check is not passing")
    if check.get("motion", {}).get("enabled") is not True:
        errors.append("full HyperFrames motion validation is not enabled")
    review = read_json(review_path)
    snapshots = [Path(str(path)) for path in review.get("reviewed_snapshots") or []]
    required_checks = {
        "content_relevance", "visual_variety", "overlap", "overflow",
        "caption_face_cursor_ui_safety", "motion_rhythm",
    }
    if (
        review.get("status") != "pass"
        or len(snapshots) < 4
        or any(not path.is_file() for path in snapshots)
        or any((review.get("checks") or {}).get(name) != "pass" for name in required_checks)
    ):
        errors.append("full HyperFrames snapshot review is incomplete or stale")
    parity = read_json(parity_path)
    if project.get("motion_quality", {}).get("enabled") is True:
        errors.extend(_motion_render_evidence_errors(
            root=root, project=project, full_project=full_project,
        ))
    else:
        try:
            errors.extend(validate_preview_render_parity(
                parity,
                read_json(storyboard_path),
                configured_tolerances=project.get("qa", {}).get(
                    "preview_render_parity", {}
                ).get("tolerances", {"position_px": 4, "size_px": 4, "time_seconds": 0.05}),
            ))
        except (TypeError, ValueError) as error:
            errors.append(f"preview/render parity report is malformed: {error}")
    evidence = read_json(evidence_path)
    bindings = {
        "storyboard_sha256": storyboard_path,
        "visual_vocabulary_sha256": vocabulary_path,
        "commands_sha256": commands_path,
        "hyperframes_check_sha256": check_path,
        "hyperframes_check_receipt_sha256": check_receipt_path,
        "snapshot_review_sha256": review_path,
        "preview_render_parity_sha256": parity_path,
    }
    for field, path in bindings.items():
        if evidence.get(field) != sha256_file(path):
            errors.append(f"full HyperFrames evidence binding is stale: {field}")
    if any(evidence.get(field) is not True for field in (
        "strict_check_passed", "snapshot_review_passed", "preview_render_parity_passed",
    )):
        errors.append("full HyperFrames verified evidence does not record all passing gates")
    return errors


def _authorization_errors(root: Path, full_project: Path, commands_path: Path) -> list[str]:
    path = root / "final-render-authorization.json"
    evidence_path = root / "full-qa" / "verified-evidence.json"
    if not path.is_file():
        return ["final render authorization is missing"]
    row = read_json(path)
    errors: list[str] = []
    if row.get("authorized") is not True or not str(row.get("authorized_by", "")).strip():
        errors.append("final render authorization lacks an explicit authorizer")
    bindings = {
        "storyboard_sha256": full_project / "storyboard.json",
        "visual_vocabulary_sha256": full_project / "visual-vocabulary-audit.json",
        "commands_sha256": commands_path,
        "full_qa_evidence_sha256": evidence_path,
    }
    for field, artifact in bindings.items():
        if not artifact.is_file() or row.get(field) != sha256_file(artifact):
            errors.append(f"final render authorization is stale: {field}")
    return errors


def _sample_qa_errors(root: Path, sample_project: Path, project: dict[str, Any]) -> list[str]:
    storyboard_path = sample_project / "storyboard.json"
    review_path = root / "sample-qa" / "aesthetic-review.json"
    audio_plan_path = sample_project / "audio-plan.json"
    gate_path = root / "sample-qa" / "gate-report.json"
    approval_path = root / "preview-approval.json"
    required = [storyboard_path, review_path, audio_plan_path, gate_path, approval_path]
    missing = [path for path in required if not path.is_file()]
    if missing:
        return ["sample QA evidence is missing: " + ", ".join(map(str, missing))]
    storyboard = read_json(storyboard_path)
    errors = validate_aesthetic_review(
        read_json(review_path), storyboard,
        decision_complete=project.get("motion_quality", {}).get("enabled") is True,
    )
    errors.extend(validate_audio_plan(
        read_json(audio_plan_path), storyboard, project, base_dir=sample_project,
    ))
    gate = read_json(gate_path)
    if gate.get("passed") is not True or gate.get("errors"):
        errors.append("sample QA gate is not passing")
    for field, artifact in {
        "storyboard_sha256": storyboard_path,
        "review_sha256": review_path,
        "audio_plan_sha256": audio_plan_path,
    }.items():
        if gate.get(field) != sha256_file(artifact):
            errors.append(f"sample QA gate is stale: {field}")
    approval = read_json(approval_path)
    if approval.get("approved") is not True or not str(approval.get("approved_by", "")).strip():
        errors.append("sample approval lacks an explicit approver")
    for field, artifact in {
        "storyboard_sha256": storyboard_path,
        "aesthetic_review_sha256": review_path,
        "gate_report_sha256": gate_path,
    }.items():
        if approval.get(field) != sha256_file(artifact):
            errors.append(f"sample approval is stale: {field}")
    if project.get("editorial_regression", {}).get("enabled") is True:
        baseline = root / "editorial-regression" / "golden-baseline.json"
        if (
            not baseline.is_file()
            or approval.get("golden_baseline") != str(baseline)
            or approval.get("golden_baseline_sha256") != (
                sha256_file(baseline) if baseline.is_file() else None
            )
        ):
            errors.append("sample approval is stale: golden editorial baseline")
    if project.get("motion_quality", {}).get("enabled") is True:
        creative_review_path = root / "sample-qa" / "creative-review.json"
        motion_contract_path = root / "motion-design" / "sample" / "motion-design-contract.json"
        receipt_paths: dict[str, Path] = {}
        for path in sorted((sample_project / "keyframe-receipts").glob("*.json")):
            try:
                event_id = str(read_json(path).get("event_id") or "")
            except (OSError, ValueError, json.JSONDecodeError):
                continue
            if event_id:
                receipt_paths[event_id] = path.resolve()
        if not creative_review_path.is_file():
            errors.append("paired creative review is missing")
        else:
            creative_review = read_json(creative_review_path)
            errors.extend(validate_creative_review(
                creative_review,
                motion_design_contract_path=motion_contract_path,
                storyboard_path=storyboard_path,
                keyframe_receipt_paths=receipt_paths,
                motion_audio_decisions_path=audio_plan_path,
                authorized_user_reviewers={str(approval.get("approved_by") or "")},
            ))
            if (
                creative_review.get("status") != "approved"
                or (creative_review.get("user_review") or {}).get("decision") != "approved"
            ):
                errors.append("paired creative review lacks explicit user approval")
            if approval.get("creative_review_sha256") != sha256_file(creative_review_path):
                errors.append("sample approval is stale: creative_review_sha256")
    return errors


def _render_receipt_errors(
    root: Path, full_project: Path, commands_path: Path, output: Path,
) -> list[str]:
    receipt_path = root / "final-render-receipt.json"
    authorization_path = root / "final-render-authorization.json"
    qa_evidence_path = root / "full-qa" / "verified-evidence.json"
    toolchain_path = root / "toolchain-compatibility.json"
    required = [receipt_path, commands_path]
    missing = [path for path in required if not path.is_file()]
    if missing:
        return ["final render execution evidence is missing: " + ", ".join(map(str, missing))]
    receipt = read_json(receipt_path)
    command_record = (read_json(commands_path).get("final_motion_render") or {})
    bindings = {
        "authorization_sha256": authorization_path,
        "full_qa_evidence_sha256": qa_evidence_path,
        "storyboard_sha256": full_project / "storyboard.json",
        "commands_sha256": commands_path,
        "toolchain_sha256": toolchain_path,
        "output_sha256": output,
        "stdout_sha256": Path(str(receipt.get("stdout_log", ""))),
        "stderr_sha256": Path(str(receipt.get("stderr_log", ""))),
    }
    errors: list[str] = []
    if (
        receipt.get("owner") != "director"
        or receipt.get("capability") != "hyperframes_render"
        or receipt.get("status") != "pass"
        or _safe_int(receipt.get("exit_code")) != 0
        or receipt.get("command_sha256") != _stable_hash(command_record.get("argv") or [])
        or receipt.get("cwd") != str(Path(str(command_record.get("cwd", ""))).resolve())
        or receipt.get("output") != str(output.resolve())
    ):
        errors.append("final render execution receipt contract is invalid")
    for field, artifact in bindings.items():
        if not artifact.is_file() or receipt.get(field) != sha256_file(artifact):
            errors.append(f"final render execution receipt is stale: {field}")
    return errors


def build(
    project_file: Path,
    test_report: Path | None = None,
    fixture_report: Path | None = None,
) -> dict[str, Any]:
    project, context = load_project_context(project_file)
    root = context.work_dir / "director"
    state_path = root / "director-state.json"
    state = read_json(state_path) if state_path.is_file() else {}
    sample_project = context.root / str(
        project.get("workflow", {}).get("director", {}).get("sample_hyperframes_project", "hyperframes-director")
    )
    full_project = context.root / str(
        project.get("workflow", {}).get("director", {}).get("full_hyperframes_project", "hyperframes-director-full")
    )
    if sample_project.is_absolute() is False:
        sample_project = (context.root / sample_project).resolve()
    if full_project.is_absolute() is False:
        full_project = (context.root / full_project).resolve()
    tests = read_json(test_report) if test_report and test_report.is_file() else {}
    test_report_errors = (
        validate_test_suite_report(tests, Path(__file__).parents[1], test_report)
        if test_report and test_report.is_file() else ["test-suite receipt is missing"]
    )
    fixture_report = fixture_report or (
        Path(__file__).parents[1] / "references" / "validation" / "six-fixture-acceptance.json"
    )
    fixtures = read_json(fixture_report) if fixture_report.is_file() else {}
    legacy_path = root / "legacy-script-audit.json"
    legacy = read_json(legacy_path) if legacy_path.is_file() else {}
    sync_path = context.edit_dir / "video-use" / "caption-sync-report.json"
    edl_path = context.edit_dir / "video-use" / "edl.json"
    captions_path = context.edit_dir / "video-use" / "captions.json"
    master_srt_path = context.edit_dir / "video-use" / "master.srt"
    media_analysis_path = context.edit_dir / "video-use" / "media-analysis.json"
    edit_preflight_path = context.edit_dir / "video-use" / "edit-correctness-preflight.json"
    sync = read_json(sync_path) if sync_path.is_file() else {}
    sample_storyboard_path = sample_project / "storyboard.json"
    sample_storyboard = read_json(sample_storyboard_path) if sample_storyboard_path.is_file() else {}
    visual_events = [
        event for event in (sample_storyboard.get("events") or [])
        if event.get("treatment") != "quiet_source"
    ]
    signatures = {
        visual_signature(event) for event in visual_events
        if len(visual_signature(event)) == len(REQUIRED_VISUAL_FIELDS)
        and all(visual_signature(event))
    }
    sample_gate_path = root / "sample-qa" / "gate-report.json"
    sample_gate = read_json(sample_gate_path) if sample_gate_path.is_file() else {}
    sample_qa_errors = _sample_qa_errors(root, sample_project, project)
    full_commands_path = root / "full-hyperframes-commands.json"
    full_commands = read_json(full_commands_path) if full_commands_path.is_file() else {}
    render_record = full_commands.get("final_motion_render") or {}
    render_output = Path(str(render_record.get("expected_artifact", "__missing__")))
    full_qa_evidence = root / "full-qa" / "verified-evidence.json"
    final_render_authorization = root / "final-render-authorization.json"
    delivery_output_value = project.get("delivery", {}).get(
        "output", f"exports/{project.get('video_id', 'video')}-universal.mp4"
    )
    manual_finish = project.get("delivery", {}).get("manual_finish", {})
    openmontage = project.get("delivery", {}).get("openmontage_handoff", {})
    if openmontage.get("enabled") is True and manual_finish.get("enabled") is not True:
        manual_finish = {**openmontage, "backend": "openmontage"}
    manual_active = (
        manual_finish.get("enabled") is True
        and manual_finish.get("backend") in {"opencut", "openmontage", "other_nle"}
    )
    if manual_active:
        delivery_output_value = manual_finish.get(
            "returned_final", f"exports/{project.get('video_id', 'video')}-manual-finish.mp4"
        )
    delivery_output = Path(str(delivery_output_value))
    if not delivery_output.is_absolute():
        delivery_output = (context.root / delivery_output).resolve()
    stages = state.get("stages") or {}
    final_correctness_path = context.edit_dir / "video-use" / "final-edit-correctness.json"
    final_aesthetic_path = root / "final-qa" / "aesthetic-review.json"
    cover_review_path = root / "final-qa" / "cover-review.json"
    platform_paths = {
        name: root / "final-qa" / f"platform-{name}.json"
        for name in ("douyin", "wechat_channels")
    }
    state_artifact_errors = [
        *_artifact_record_errors(stages),
        *_input_fingerprint_errors(state, context.project_file, context.source_video),
    ]
    full_hyperframes_errors = _full_hyperframes_errors(
        root, full_project, project, full_commands_path,
    )
    authorization_errors = _authorization_errors(root, full_project, full_commands_path)
    render_receipt_errors = _render_receipt_errors(
        root, full_project, full_commands_path, render_output,
    )
    caption_delivery_plan = root / "final-compose-command.json"
    caption_evidence_path = root / "evidence" / "evidence-bundle.json"
    caption_evidence = read_json(caption_evidence_path) if caption_evidence_path.is_file() else {}
    caption_display = caption_evidence.get("display") if isinstance(caption_evidence, dict) else None
    caption_canvas = (
        {"width": caption_display.get("width"), "height": caption_display.get("height")}
        if isinstance(caption_display, dict) else None
    )
    caption_delivery_errors = _final_caption_delivery_errors(
        caption_delivery_plan, master_srt_path,
        input_mode=context.input_mode,
        caption_disabled=project.get("editing", {}).get("caption_delivery") == "none",
        caption_treatment_options=(project.get("editing") or {}).get("caption_treatment"),
        caption_canvas=caption_canvas,
    ) if stages.get("final_compose", {}).get("status") == "complete" else []

    criteria: dict[str, dict[str, Any]] = {}
    criteria["1_tests_and_architecture_tests"] = _row(
        "pass" if not test_report_errors else "pending",
        f"Source-bound test count: {tests.get('test_count', 0)}; zero skipped/failed: {not test_report_errors}.",
        [test_report] if test_report else [],
    )
    criteria["2_single_resumable_entry"] = _row(
        "pass" if state_path.is_file() and "final_compose" in stages
        and not state_artifact_errors else "pending",
        "director.py is canonical and every completed stage is bound to current artifact bytes."
        if not state_artifact_errors else
        f"Resumable state has {len(state_artifact_errors)} missing or stale artifact binding(s).",
        [state_path, Path(__file__).with_name("director.py")],
    )
    criteria["3_no_project_hardcoded_execution"] = _row(
        "pass" if legacy.get("execution_allowed") is False else "pending",
        f"Legacy project script status: {legacy.get('status', 'missing')}; findings are quarantined, not executed.",
        [legacy_path],
    )
    rendered = (
        stages.get("full_hyperframes_qa", {}).get("status") == "complete"
        and stages.get("final_render", {}).get("status") == "complete"
        and render_output.is_file()
        and not full_hyperframes_errors
        and not authorization_errors
        and not render_receipt_errors
        and _stage_binds_artifacts(stages, "full_hyperframes_qa", [
            root / "full-qa" / "hyperframes-check.json",
            root / "full-qa" / "hyperframes-check-receipt.json",
            root / "full-qa" / "snapshot-review.json",
            root / "full-qa" / "preview-render-parity.json",
            root / "full-qa" / "verified-evidence.json",
        ])
        and _stage_binds_artifacts(stages, "final_render", [
            render_output, final_render_authorization, root / "final-render-receipt.json",
        ])
        and sample_project.resolve() != full_project.resolve()
    )
    criteria["4_actual_hyperframes_final_render"] = _row(
        "pass" if rendered else "pending",
        "Full HyperFrames QA, authorization, or render evidence is incomplete."
        if not rendered else "Full output was rendered from the exact QA-approved HyperFrames project.",
        [full_commands_path, full_qa_evidence, final_render_authorization, render_output],
    )
    video_use_chain_pass = (
        all(path.is_file() for path in (
            edl_path, captions_path, sync_path, media_analysis_path, edit_preflight_path
        ))
        and sync.get("passed") is True
        and stages.get("video_use_timeline", {}).get("status") == "complete"
    )
    final_correctness_pass = False
    if final_correctness_path.is_file() and edl_path.is_file() and delivery_output.is_file():
        final_correctness_pass = not validate_video_use_final_correctness(
            read_json(final_correctness_path), output_path=delivery_output, edl=read_json(edl_path),
        )
    video_use_pass = (
        video_use_chain_pass
        and (not rendered or final_correctness_pass)
        and not caption_delivery_errors
    )
    criteria["5_video_use_word_timeline_chain"] = _row(
        "pass" if video_use_pass else "pending",
        "video-use media analysis, EDL preflight, output-timeline captions, sampled sync, and final rendered-output correctness are present." if video_use_pass
        else "video-use execution evidence is incomplete, or the final render is not yet bound to a final correctness report.",
        [media_analysis_path, edl_path, edit_preflight_path, captions_path, master_srt_path,
         sync_path, final_correctness_path, caption_delivery_plan],
    )
    criteria["6_sample_has_distinct_structures"] = _row(
        "pass" if _sample_structure_gate(project, visual_events, signatures) else "pending",
        (
            f"Motion Quality sample contains {len(visual_events)} compiler-selected render "
            "event(s); no filler event or family quota is applied."
            if project.get("motion_quality", {}).get("enabled") is True else
            f"Sample contains {len(visual_events)} visual events and {len(signatures)} "
            "distinct five-field structures."
        ),
        [sample_storyboard_path, sample_project / "visual-vocabulary-audit.json"],
    )
    preview_artifacts = [root / "preview-approval.json"]
    if project.get("motion_quality", {}).get("enabled") is True:
        preview_artifacts.append(root / "sample-qa" / "creative-review.json")
    criteria["7_sample_content_and_layout_gate"] = _row(
        "pass" if not sample_qa_errors
        and _stage_binds_artifacts(stages, "sample_qa", [
            sample_project / "storyboard.json",
            root / "sample-qa" / "aesthetic-review.json",
            sample_project / "audio-plan.json", sample_gate_path,
        ])
        and _stage_binds_artifacts(stages, "preview_approval", preview_artifacts)
        else "pending",
        "Sample aesthetics, audio, gate hashes, and explicit preview approval were revalidated."
        if not sample_qa_errors else
        f"Sample QA or approval has {len(sample_qa_errors)} missing, failed, or stale item(s).",
        [sample_gate_path, root / "sample-qa" / "aesthetic-review.json",
         sample_project / "audio-plan.json", *preview_artifacts,
         root / "review" / "creative-review.html"],
    )
    single_output_config = state.get("single_universal_output") is True and project.get("delivery", {}).get("mode") in {
        None, "single_universal_export", "autonomous_pre_publish"
    }
    output_hash = sha256_file(delivery_output) if delivery_output.is_file() else None
    cover_value = project.get("delivery", {}).get("cover", "exports/cover-portrait.png")
    cover_path = Path(str(cover_value))
    if not cover_path.is_absolute():
        cover_path = (context.root / cover_path).resolve()
    cover_hash = sha256_file(cover_path) if cover_path.is_file() else None
    cover_required = asset_is_required(project, "cover")
    cover_applicable = cover_required or cover_path.is_file()
    platform_same_file = bool(output_hash) and all(
        path.is_file()
        and read_json(path).get("status") == "pass"
        and read_json(path).get("file_sha256") == output_hash
        for path in platform_paths.values()
    )
    single_output = single_output_config and delivery_output.is_file() and platform_same_file
    criteria["8_single_universal_delivery"] = _row(
        "pass" if single_output else "pending",
        f"Configured universal output: {delivery_output}; rendered: {delivery_output.is_file()}; same bytes validated for both platforms: {platform_same_file}.",
        [state_path, project_file, delivery_output, *platform_paths.values()],
    )
    handoff_path = root / "refactor-change-report.md"
    handoff_text = handoff_path.read_text(encoding="utf-8") if handoff_path.is_file() else ""
    handoff_valid = (
        len(handoff_text.strip()) >= 80
        and all(marker in handoff_text.lower() for marker in (
            "automated verification", "manual gates", "limitations",
        ))
    )
    criteria["9_handoff_and_honest_limits"] = _row(
        "pass" if handoff_valid else "pending",
        "The handoff records code, test, sample, render, and remaining delivery evidence without claiming incomplete gates.",
        [handoff_path, Path(__file__).resolve(), sample_storyboard_path],
    )
    final_delivery_errors: list[str] = []
    final_delivery_errors.extend(_required_asset_readiness_errors(project, stages))
    full_storyboard_path = full_project / "storyboard.json"
    audio_plan_path = full_project / "audio-plan.json"
    media_report_path = (
        root / "manual-finish" / "manual-final-media-report.json"
        if manual_active else root / "final-media-report.json"
    )
    if not delivery_output.is_file():
        final_delivery_errors.append("universal delivery output is missing")
    if not full_storyboard_path.is_file():
        final_delivery_errors.append("full storyboard is missing")
    if not final_aesthetic_path.is_file():
        final_delivery_errors.append("final aesthetic review is missing")
    if not audio_plan_path.is_file():
        final_delivery_errors.append("final audio plan is missing")
    if cover_required and not cover_path.is_file():
        final_delivery_errors.append("delivery cover is missing")
    if cover_applicable and not cover_review_path.is_file():
        final_delivery_errors.append("cover review is missing")
    if delivery_output.is_file() and full_storyboard_path.is_file() and final_aesthetic_path.is_file():
        final_review = read_json(final_aesthetic_path)
        final_delivery_errors.extend(validate_aesthetic_review(
            final_review, read_json(full_storyboard_path),
            decision_complete=project.get("motion_quality", {}).get("enabled") is True,
        ))
        if final_review.get("reviewed_output_sha256") != output_hash:
            final_delivery_errors.append("final aesthetic review output hash is stale")
    if audio_plan_path.is_file() and full_storyboard_path.is_file():
        final_delivery_errors.extend(validate_audio_plan(
            read_json(audio_plan_path), read_json(full_storyboard_path), project,
            base_dir=full_project,
        ))
    if cover_applicable and cover_review_path.is_file() and cover_path.is_file():
        cover_review = read_json(cover_review_path)
        final_delivery_errors.extend(_cover_review_errors(cover_review, cover_hash))
    final_delivery_errors.extend(_technical_report_errors(media_report_path, delivery_output))
    for name, path in platform_paths.items():
        final_delivery_errors.extend(
            f"{name}: {error}" for error in _platform_report_errors(path, delivery_output, cover_path)
        )
    if not final_correctness_pass:
        final_delivery_errors.append("video-use final edit correctness is missing or stale")
    delivery_contract_path = root / "delivery-contract.json"
    if not delivery_contract_path.is_file():
        final_delivery_errors.append("delivery contract is missing")
    elif delivery_output.is_file() and (not cover_applicable or cover_path.is_file()):
        contract = read_json(delivery_contract_path)
        if (
            contract.get("file_sha256") != output_hash
            or contract.get("cover_sha256") != cover_hash
            or Path(str(contract.get("universal_video", ""))).resolve() != delivery_output.resolve()
            or contract.get("duplicate_platform_mp4s") is not False
        ):
            final_delivery_errors.append("delivery contract is incomplete or stale")
        expected_cover_path = str(cover_path) if cover_applicable else None
        if contract.get("cover") != expected_cover_path:
            final_delivery_errors.append("delivery contract cover applicability is stale")
        if not cover_applicable and contract.get("cover_applicability") != "optional_unavailable":
            final_delivery_errors.append("delivery contract does not record optional unavailable cover")
    final_review_evidence = (
        _review_evidence_files(read_json(final_aesthetic_path))
        if final_aesthetic_path.is_file() else []
    )
    delivery_stage_artifacts = [
        delivery_output, delivery_contract_path, final_aesthetic_path,
        final_correctness_path, media_report_path, *platform_paths.values(),
        *final_review_evidence,
    ]
    if cover_applicable:
        delivery_stage_artifacts.extend([cover_path, cover_review_path])
    delivery_complete = (
        stages.get("delivery_qa", {}).get("status") == "complete"
        and not final_delivery_errors
        and _stage_binds_artifacts(stages, "delivery_qa", delivery_stage_artifacts)
    )
    criteria["10_blocking_final_delivery_qa"] = _row(
        "pass" if delivery_complete else "pending",
        "Blocking final delivery QA independently revalidated all bound evidence."
        if delivery_complete else
        f"Final delivery QA has {len(final_delivery_errors)} missing, failed, or stale item(s).",
        [
            delivery_contract_path, final_aesthetic_path, cover_review_path,
            final_correctness_path, media_report_path, *platform_paths.values(),
        ],
    )
    manual_dir = root / "manual-finish"
    manual_artifacts = [
        manual_dir / (
            "openmontage-handoff-manifest.json"
            if manual_finish.get("backend") == "openmontage" else "handoff-manifest.json"
        ),
        manual_dir / "correction-ledger.json",
        manual_dir / "return-receipt.json",
        manual_dir / "manual-final-media-report.json",
        manual_dir / "manual-final-qa.json",
    ]
    manual_errors: list[str] = []
    if manual_active:
        if stages.get("manual_finish_handoff", {}).get("status") != "complete":
            manual_errors.append("manual_finish_handoff stage is not complete")
        missing_manual = [path for path in manual_artifacts if not path.is_file()]
        if missing_manual:
            manual_errors.append("manual finish evidence files are missing")
        if not delivery_output.is_file():
            manual_errors.append("manual returned final is missing")
        if not manual_errors:
            receipt = read_json(manual_artifacts[2])
            media = read_json(manual_artifacts[3])
            if receipt.get("returned_final_sha256") != output_hash:
                manual_errors.append("manual return receipt hash is stale")
            receipt_output = Path(str(receipt.get("returned_final", "")))
            if not receipt_output.is_absolute() or receipt_output.resolve() != delivery_output.resolve():
                manual_errors.append("manual return receipt path does not match effective delivery output")
            if media.get("decode_status") != "pass" or media.get("sha256") != output_hash:
                manual_errors.append("manual full-decode media report is stale or not passing")
            manual_errors.extend(validate_handoff_manifest(read_json(manual_artifacts[0])))
            try:
                validate_ledger(manual_artifacts[1])
            except ValueError as error:
                manual_errors.append(str(error))
            manual_errors.extend(validate_returned_final_qa(read_json(manual_artifacts[4]), delivery_output))
            if not final_correctness_path.is_file() or not edl_path.is_file():
                manual_errors.append("manual return lacks video-use final edit correctness evidence")
            else:
                manual_errors.extend(validate_video_use_final_correctness(
                    read_json(final_correctness_path),
                    output_path=delivery_output,
                    edl=read_json(edl_path),
                ))
    manual_complete = not manual_errors
    criteria["11_optional_manual_finish_handoff"] = _row(
        "pass" if manual_complete else "pending",
        "Manual finish is disabled and preserves the one-click path."
        if not manual_active else
        (
            "The human-facing NLE return is hash-bound and has passed decode, caption, audio, visual, "
            "and edit-correctness revalidation."
            if manual_complete else
            f"Manual finish evidence requires fresh revalidation ({len(manual_errors)} issue(s))."
        ),
        [*manual_artifacts, final_correctness_path],
    )
    fixture_source_path = Path(__file__).parents[1] / "tests" / "fixtures" / "acceptance-scenarios.json"
    fixture_implementation_path = Path(__file__).with_name("fixture_acceptance.py")
    fixture_source_payload = read_json(fixture_source_path) if fixture_source_path.is_file() else {}
    expected_fixture_report = (
        evaluate_suite(fixture_source_payload, fixture_source=fixture_source_path)
        if fixture_source_path.is_file() else {}
    )
    fixture_scenarios = fixtures.get("scenarios") or []
    fixture_pass = (
        expected_fixture_report.get("status") == "pass"
        and _stable_hash(fixtures) == _stable_hash(expected_fixture_report)
        and all(
            [check.get("name") for check in row.get("checks") or []] == list(CHECK_NAMES)
            for row in fixture_scenarios
        )
    )
    six_media_manifest = (
        Path(__file__).parents[1] / "references" / "validation" / "six-media-acceptance.json"
    )
    six_media_errors = validate_six_media_manifest(six_media_manifest)
    criteria["12_six_fixture_acceptance"] = _row(
        "pass" if fixture_pass and not six_media_errors
        else "failed" if fixture_report.is_file() else "pending",
        "Six cross-video-type contracts and six retained real-media technical fixtures passed."
        if fixture_pass and not six_media_errors
        else "The structured or retained real-media six-fixture evidence is missing or failed.",
        [fixture_report, fixture_source_path, fixture_implementation_path, six_media_manifest],
    )
    golden_report = (
        Path(__file__).parents[1] / "references" / "validation" /
        "current-golden-regression.json"
    )
    golden_policy = Path(__file__).parents[1] / "tests" / "fixtures" / "current-golden-policy.json"
    golden_errors = validate_current_golden_report(
        golden_report, fixture_source_path, golden_policy,
        media_manifest=six_media_manifest,
    )
    criteria["15_current_golden_regression"] = _row(
        "pass" if not golden_errors else "failed",
        "Current Director/schema/implementation golden evidence is reproducible."
        if not golden_errors else
        f"Current golden regression has {len(golden_errors)} issue(s).",
        [golden_report, golden_policy, six_media_manifest],
    )
    representative_manifest = (
        Path(__file__).parents[1] / "references" / "validation" /
        "representative-short-media" / "manifest.json"
    )
    representative_errors = validate_representative_short_media(representative_manifest)
    criteria["16_landscape_portrait_30s_media"] = _row(
        "pass" if not representative_errors else "failed",
        "Current 30-second landscape and portrait media decode, probe, audio, and frames pass."
        if not representative_errors else
        f"Representative short media has {len(representative_errors)} issue(s).",
        [representative_manifest],
    )
    inventory_path = root / "capability-inventory.json"
    inventory = read_json(inventory_path) if inventory_path.is_file() else {}
    capability_rows = {
        row.get("name"): row for row in (inventory.get("capabilities") or [])
        if isinstance(row, dict) and row.get("name")
    }
    expected_inventory = build_capability_inventory(project)
    expected_capability_rows = {
        row["name"]: row for row in expected_inventory.get("capabilities") or []
    }
    capability_names = set(capability_rows)
    required_capabilities = {
        "video_use_timeline", "evidence_acquisition", "semantic_visual_plan",
        "hyperframes_router", "preview_render_parity", "cover_generation", "ip_components",
        "bgm_pipeline", "sfx_pipeline", "audio_normalization", "platform_occlusion",
        "render_cache", "manual_finish_handoff", "asr_router", "otio_timeline",
        "production_contract", "provider_governance", "local_semantic_corpus",
        "brand_motion_playbook", "visual_dynamics_qa", "editorial_regression",
        "review_dashboard", "clip_factory", "podcast_pipeline",
        "localization_pipeline", "openmontage_handoff",
        "project_initializer", "doctor_preflight", "semantic_confidence",
        "interactive_review", "event_render_cache", "cover_reference_pack",
        "preference_learning", "feedback_learning_loop", "portable_audit_bundle",
        "release_delivery_pack",
        "adaptive_layout", "stateful_target_binding", "motion_quality_engine",
        "hyperframes_keyframe_evidence", "paired_creative_review",
    }
    maturity_floor = CAPABILITY_LEVELS.index("director_integrated")
    capability_contract_pass = (
        required_capabilities <= capability_names
        and _stable_hash(inventory) == _stable_hash(expected_inventory)
    )
    if capability_contract_pass:
        for name in required_capabilities:
            row = capability_rows[name]
            try:
                maturity_ok = CAPABILITY_LEVELS.index(row.get("maturity")) >= maturity_floor
            except ValueError:
                maturity_ok = False
            if not maturity_ok or not str(row.get("configuration_route") or "").strip():
                capability_contract_pass = False
                break
            expected_row = expected_capability_rows.get(name) or {}
            if any(row.get(field) != expected_row.get(field) for field in (
                "owner", "optional", "maturity", "configuration_route", "enabled",
            )):
                capability_contract_pass = False
                break
            if row.get("optional") is False and row.get("enabled") is not True:
                capability_contract_pass = False
                break
    toolchain_path = root / "toolchain-compatibility.json"
    toolchain = read_json(toolchain_path) if toolchain_path.is_file() else {}
    expected_toolchain = build_toolchain_report(probe_versions=False)
    required_hyperframes = {
        "hyperframes", "hyperframes-core", "hyperframes-creative",
        "hyperframes-animation", "hyperframes-cli",
    }
    hyperframes_records = toolchain.get("required_hyperframes_skills") or {}
    toolchain_pass = (
        toolchain_path.is_file()
        and _stable_hash(toolchain) == _stable_hash(expected_toolchain)
        and required_hyperframes <= set(hyperframes_records)
        and all(hyperframes_records[name].get("available") is True
                and str(hyperframes_records[name].get("path") or "").strip()
                and (Path(str(hyperframes_records[name]["path"])) / "SKILL.md").is_file()
                and hyperframes_records[name].get("skill_md_sha256")
                == sha256_file(Path(str(hyperframes_records[name]["path"])) / "SKILL.md")
                for name in required_hyperframes)
        and all((toolchain.get("tools", {}).get(name) or {}).get("available") is True
                for name in ("ffmpeg", "ffprobe", "npx", "node"))
        and (toolchain.get("skill_roots", {}).get("video-use") or {}).get("available") is True
    )
    evidence_bundle_path = root / "evidence" / "evidence-bundle.json"
    semantic_brief_path = root / "semantic-brief.json"
    transcript_path = (
        context.edit_dir / "video-use" / "transcripts" / f"{context.source_video.stem}.json"
    )
    semantic_errors: list[str] = []
    if semantic_brief_path.is_file():
        semantic_brief = read_json(semantic_brief_path)
        semantic_errors.extend(validate_semantic_brief(semantic_brief))
        semantic_errors.extend(validate_semantic_evidence_binding(
            semantic_brief, transcript_path=transcript_path,
            evidence_bundle_path=evidence_bundle_path,
        ))
    else:
        semantic_errors.append("semantic brief is missing")
    evidence_contract_pass = (
        inventory_path.is_file()
        and capability_contract_pass
        and toolchain_pass
        and stages.get("evidence_acquisition", {}).get("status") == "complete"
        and stages.get("semantic_brief", {}).get("status") == "complete"
        and not semantic_errors
    )
    criteria["13_capability_and_evidence_contract"] = _row(
        "pass" if evidence_contract_pass else "pending",
        "Capability routes, required HyperFrames skills, and hash-bound semantic evidence all validate."
        if evidence_contract_pass else
        "Capability routes, toolchain skills, or hash-bound semantic evidence are incomplete.",
        [inventory_path, toolchain_path, evidence_bundle_path, semantic_brief_path, transcript_path],
    )
    enhancement_errors: list[str] = []
    production_path = root / "production-contract.json"
    provider_path = root / "provider-decision.json"
    cost_path = root / "cost-ledger.json"
    sample_dynamics = root / "sample-qa" / "visual-dynamics-qa.json"
    full_dynamics = root / "full-qa" / "visual-dynamics-qa.json"
    full_brief_path = root / "full-semantic-brief.json"
    playbook_path = root / "brand-motion" / "brand-motion-playbook.json"
    core_paths = [production_path, provider_path, cost_path, sample_dynamics,
                  full_dynamics, full_brief_path, playbook_path]
    missing_core = [path for path in core_paths if not path.is_file()]
    if missing_core:
        enhancement_errors.append("OpenMontage-method enhancement evidence is missing")
    else:
        enhancement_errors.extend(validate_contract(
            read_json(production_path), project=project, source_path=context.source_video,
            transcript_path=transcript_path, edl_path=edl_path,
            semantic_brief_path=semantic_brief_path, input_mode=context.input_mode,
        ))
        project_hash = sha256_file(context.project_file)
        enhancement_errors.extend(validate_decision_report(
            read_json(provider_path), project.get("provider_governance", {}), project_hash,
        ))
        cost_ledger = read_json(cost_path)
        enhancement_errors.extend(validate_cost_ledger(cost_ledger, project_hash))
        if any(row.get("status") not in {"success", "failed"}
               for row in cost_ledger.get("reservations") or []):
            enhancement_errors.append("provider cost ledger has unreconciled reservations")
        for report_path, storyboard_path, brief_path in (
            (sample_dynamics, sample_storyboard_path, semantic_brief_path),
            (full_dynamics, full_project / "storyboard.json", full_brief_path),
        ):
            report = read_json(report_path)
            enhancement_errors.extend(validate_visual_dynamics_report(
                report, storyboard_path, brief_path,
                config=project.get("qa", {}).get("visual_dynamics", {}),
                production_contract_path=production_path,
            ))
            if report.get("status") != "pass":
                enhancement_errors.append(f"visual dynamics did not pass: {report_path}")
        enhancement_errors.extend(validate_playbook(read_json(playbook_path), project=project))
    if project.get("editorial_regression", {}).get("enabled") is True:
        regression_path = root / "full-qa" / "editorial-regression.json"
        baseline_path = root / "editorial-regression" / "golden-baseline.json"
        if not regression_path.is_file():
            enhancement_errors.append("enabled editorial regression report is missing")
        elif not baseline_path.is_file():
            enhancement_errors.append("enabled golden editorial baseline is missing")
        else:
            baseline = read_json(baseline_path)
            enhancement_errors.extend(validate_baseline(baseline))
            enhancement_errors.extend(validate_regression(read_json(regression_path), baseline))
    derived = project.get("derived_content", {})
    derived_paths = {
        "clip_factory": root / "derived-content" / "clip-factory-manifest.json",
        "podcast": root / "derived-content" / "podcast-manifest.json",
        "localization": root / "derived-content" / "localization-manifest.json",
    }
    derived_validators = {
        "clip_factory": validate_clip_manifest,
        "podcast": validate_podcast_manifest,
        "localization": validate_localization_manifest,
    }
    for name, path in derived_paths.items():
        if derived.get(name, {}).get("enabled") is not True:
            continue
        if not path.is_file():
            enhancement_errors.append(f"enabled derived content report is missing: {name}")
        else:
            enhancement_errors.extend(derived_validators[name](read_json(path)))
    required_new_stages = {
        "provider_governance", "production_contract", "brand_motion_playbook", "derived_content",
    }
    if any((stages.get(name) or {}).get("status") != "complete" for name in required_new_stages):
        enhancement_errors.append("new Director stages are not all complete")
    stage_bindings = {
        "provider_governance": [provider_path, cost_path],
        "production_contract": [production_path],
        "brand_motion_playbook": [playbook_path],
        "sample_qa": [sample_dynamics],
        "full_hyperframes_qa": [production_path, full_dynamics],
        "derived_content": [root / "derived-content" / "decision.json"],
    }
    for stage, paths in stage_bindings.items():
        if not _stage_binds_artifacts(stages, stage, paths):
            enhancement_errors.append(f"{stage} does not hash-bind its enhancement evidence")
    if full_qa_evidence.is_file() and not missing_core:
        evidence = read_json(full_qa_evidence)
        for field, path in {
            "production_contract_sha256": production_path,
            "visual_dynamics_sha256": full_dynamics,
        }.items():
            if evidence.get(field) != sha256_file(path):
                enhancement_errors.append(f"full QA enhancement binding is stale: {field}")
    delivery_contract_path = root / "delivery-contract.json"
    if delivery_contract_path.is_file() and not missing_core:
        delivery_contract = read_json(delivery_contract_path)
        for field, path in {
            "production_contract_sha256": production_path,
            "provider_decision_sha256": provider_path,
            "cost_ledger_sha256": cost_path,
            "sample_visual_dynamics_sha256": sample_dynamics,
            "full_visual_dynamics_sha256": full_dynamics,
        }.items():
            if delivery_contract.get(field) != sha256_file(path):
                enhancement_errors.append(f"delivery enhancement binding is stale: {field}")
    criteria["14_openmontage_method_enhancements"] = _row(
        "pass" if not enhancement_errors else "pending",
        "Production, provider/cost, visual dynamics, brand, optional derived-content, and handoff contracts validate."
        if not enhancement_errors else
        f"OpenMontage-method enhancement evidence has {len(enhancement_errors)} issue(s).",
        [production_path, provider_path, cost_path, sample_dynamics, full_dynamics,
         playbook_path, root / "derived-content" / "decision.json"],
    )
    overall = "pass" if all(row["status"] == "pass" for row in criteria.values()) else (
        "failed" if any(row["status"] == "failed" for row in criteria.values()) else "pending"
    )
    limitations = []
    if not rendered:
        limitations.append("The full-video HyperFrames render has not completed.")
    if rendered and not final_correctness_pass:
        limitations.append("The rendered universal output still needs video-use final correctness evidence.")
    if not final_aesthetic_path.is_file():
        limitations.append("The full-video evidence-backed aesthetic review is incomplete.")
    cover_review = read_json(cover_review_path) if cover_review_path.is_file() else {}
    if (
        cover_review.get("identity_applicable", True) is not False
        and cover_review.get("identity_approved_by_user") is not True
    ):
        limitations.append("The final cover still requires explicit user approval of identity likeness.")
    if not platform_same_file:
        limitations.append("The same universal output bytes have not passed both platform validations.")
    if manual_active and not manual_complete:
        limitations.append(
            "The optional human manual-finish return has not completed its fresh revalidation."
        )
    return {
        "schema_version": 1,
        "overall": overall,
        "criteria": criteria,
        "limitations": limitations,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project", required=True)
    parser.add_argument("--test-report")
    parser.add_argument("--fixture-report")
    parser.add_argument("--output")
    args = parser.parse_args()
    project_file = Path(args.project).resolve()
    _, context = load_project_context(project_file)
    output = Path(args.output).resolve() if args.output else context.work_dir / "director" / "completion-audit.json"
    report = build(
        project_file,
        Path(args.test_report).resolve() if args.test_report else None,
        Path(args.fixture_report).resolve() if args.fixture_report else None,
    )
    write_json(output, report)
    print(output)
    return 0 if report["overall"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
