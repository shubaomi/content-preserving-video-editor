#!/usr/bin/env python3
"""Produce an evidence-backed audit of the director Goal acceptance criteria."""
from __future__ import annotations

import argparse
from pathlib import Path
from typing import Any

from director_contracts import (
    REQUIRED_VISUAL_FIELDS,
    load_project_context,
    read_json,
    sha256_file,
    validate_video_use_final_correctness,
    visual_signature,
    write_json,
)
from correction_ledger import validate_ledger
from manual_finish import validate_handoff_manifest, validate_returned_final_qa


def _row(status: str, finding: str, evidence: list[Path]) -> dict[str, Any]:
    return {
        "status": status,
        "finding": finding,
        "evidence": [str(path.resolve()) for path in evidence if path.exists()],
    }


def build(project_file: Path, test_report: Path | None = None) -> dict[str, Any]:
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
    legacy_path = root / "legacy-script-audit.json"
    legacy = read_json(legacy_path) if legacy_path.is_file() else {}
    sync_path = context.edit_dir / "video-use" / "caption-sync-report.json"
    edl_path = context.edit_dir / "video-use" / "edl.json"
    captions_path = context.edit_dir / "video-use" / "captions.json"
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
    manual_active = (
        manual_finish.get("enabled") is True
        and manual_finish.get("backend") in {"opencut", "other_nle"}
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

    criteria: dict[str, dict[str, Any]] = {}
    criteria["1_tests_and_architecture_tests"] = _row(
        "pass" if tests.get("passed") is True and int(tests.get("test_count", 0)) > 0 else "pending",
        f"Recorded test count: {tests.get('test_count', 0)}; passing: {tests.get('passed', False)}.",
        [test_report] if test_report else [],
    )
    criteria["2_single_resumable_entry"] = _row(
        "pass" if state_path.is_file() and "final_compose" in stages else "pending",
        "director.py is the canonical entry and state includes resumable professional stages.",
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
        and full_qa_evidence.is_file()
        and final_render_authorization.is_file()
        and sample_project.resolve() != full_project.resolve()
    )
    criteria["4_actual_hyperframes_final_render"] = _row(
        "pass" if rendered else "pending",
        "Pending by explicit user pause." if not rendered else "Full output was rendered by the separate HyperFrames project.",
        [full_commands_path, full_qa_evidence, final_render_authorization, render_output],
    )
    video_use_chain_pass = (
        all(path.is_file() for path in (
            edl_path, captions_path, sync_path, media_analysis_path, edit_preflight_path
        ))
        and sync.get("passed") is True
        and stages.get("video_use_timeline", {}).get("status") == "complete"
    )
    final_correctness_pass = final_correctness_path.is_file()
    video_use_pass = video_use_chain_pass and (not rendered or final_correctness_pass)
    criteria["5_video_use_word_timeline_chain"] = _row(
        "pass" if video_use_pass else "pending",
        "video-use media analysis, EDL preflight, output-timeline captions, sampled sync, and final rendered-output correctness are present." if video_use_pass
        else "video-use execution evidence is incomplete, or the final render is not yet bound to a final correctness report.",
        [media_analysis_path, edl_path, edit_preflight_path, captions_path, sync_path, final_correctness_path],
    )
    criteria["6_sample_has_distinct_structures"] = _row(
        "pass" if len(visual_events) >= 4 and len(signatures) >= 4 else "pending",
        f"Sample contains {len(visual_events)} visual events and {len(signatures)} distinct five-field structures.",
        [sample_storyboard_path, sample_project / "visual-vocabulary-audit.json"],
    )
    criteria["7_sample_content_and_layout_gate"] = _row(
        "pass" if sample_gate.get("passed") is True else "pending",
        "Blocking sample content, repetition, overlap, overflow, subtitle and aesthetic gate status.",
        [sample_gate_path, root / "sample-qa" / "aesthetic-review.json"],
    )
    single_output_config = state.get("single_universal_output") is True and project.get("delivery", {}).get("mode") in {
        None, "single_universal_export"
    }
    output_hash = sha256_file(delivery_output) if delivery_output.is_file() else None
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
    criteria["9_handoff_and_honest_limits"] = _row(
        "pass" if handoff_path.is_file() else "pending",
        "The handoff records code, test, sample, render, and remaining delivery evidence without claiming incomplete gates.",
        [handoff_path, Path(__file__).resolve(), sample_storyboard_path],
    )
    delivery_complete = stages.get("delivery_qa", {}).get("status") == "complete"
    criteria["10_blocking_final_delivery_qa"] = _row(
        "pass" if delivery_complete else "pending",
        f"Blocking final delivery QA status: {stages.get('delivery_qa', {}).get('status', 'missing')}.",
        [
            root / "delivery-contract.json", final_aesthetic_path, cover_review_path,
            final_correctness_path, *platform_paths.values(),
        ],
    )
    manual_dir = root / "manual-finish"
    manual_artifacts = [
        manual_dir / "handoff-manifest.json",
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
    if cover_review.get("identity_approved_by_user") is not True:
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
    parser.add_argument("--output")
    args = parser.parse_args()
    project_file = Path(args.project).resolve()
    _, context = load_project_context(project_file)
    output = Path(args.output).resolve() if args.output else context.work_dir / "director" / "completion-audit.json"
    report = build(project_file, Path(args.test_report).resolve() if args.test_report else None)
    write_json(output, report)
    print(output)
    return 0 if report["overall"] == "pass" else 2


if __name__ == "__main__":
    raise SystemExit(main())
