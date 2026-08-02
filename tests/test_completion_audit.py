from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml
from PIL import Image


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from completion_audit import build  # noqa: E402
from capability_registry import build_capability_inventory, build_toolchain_report  # noqa: E402
from brand_motion_playbook import compile_playbook  # noqa: E402
from aesthetic_qa import REQUIRED_CRITERIA  # noqa: E402
from director_contracts import STAGES, VISUAL_VOCABULARY, sha256_file  # noqa: E402
from production_contract import build_contract  # noqa: E402
from project_config import migrate_project_config  # noqa: E402
from provider_governance import build_decision_report, create_cost_ledger  # noqa: E402
from test_acceptance_report import REQUIRED_TEST_IDS, write_report_from_output  # noqa: E402
from technical_qa import run_technical_qa  # noqa: E402
from visual_dynamics_qa import build_report as build_visual_dynamics_report  # noqa: E402
from validate_platform_export import (  # noqa: E402
    bind_cover, bind_universal_output, cover_preview, decode, loudness, snapshot, validate,
)


class CompletionAuditTests(unittest.TestCase):
    def test_complete_hash_bound_fixture_passes_all_completion_criteria(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source" / "input.mp4"
            source.parent.mkdir(parents=True)
            subprocess.run([
                "ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                "testsrc2=size=1280x720:rate=24:duration=2", "-f", "lavfi", "-i",
                "sine=frequency=440:sample_rate=48000:duration=2", "-c:v", "libx264",
                "-pix_fmt", "yuv420p", "-c:a", "aac", "-shortest", str(source),
            ], check=True)
            project = root / "project.yaml"
            project.write_text(yaml.safe_dump({
                "version": 1, "video_id": "audit",
                "paths": {"root": str(root), "work": "work", "edit": "edit", "exports": "exports"},
                "source": {"primary_video": "source/input.mp4", "input_mode": "source_first"},
                "delivery": {"mode": "single_universal_export",
                             "output": "exports/audit-universal.mp4"},
            }), encoding="utf-8")
            director_root = root / "work" / "director"
            director_root.mkdir(parents=True)
            (director_root / "toolchain-compatibility.json").write_text(
                json.dumps(build_toolchain_report(probe_versions=False)), encoding="utf-8")
            output = root / "exports" / "audit-universal.mp4"
            output.parent.mkdir(parents=True)
            output.write_bytes(source.read_bytes())
            output_hash = sha256_file(output)
            render = director_root / "render" / "full-hyperframes.mp4"
            render.parent.mkdir(parents=True)
            render.write_bytes(b"render")
            sample = root / "hyperframes-director"
            full = root / "hyperframes-director-full"
            sample.mkdir()
            full.mkdir()
            events = [{"id": f"e{i}", "treatment": "structure",
                "anchor": f"concept-{i}", "viewer_takeaway": f"takeaway-{i}",
                "visual_mechanism": f"mechanism-{i}",
                "relevance_rationale": "fixture explanatory value",
                "motion": {"entrance": "fade", "reveal": "step", "hold": "steady", "exit": "fade"},
                "visual_structure": {
                "dom_structure": f"dom{i}", "information_hierarchy": f"h{i}",
                "layout_archetype": f"l{i}", "animation_choreography": f"a{i}",
                "use_case": f"u{i}"}} for i in range(4)]
            storyboard = {"composition": {"duration": 0}, "events": events}
            (sample / "storyboard.json").write_text(json.dumps(storyboard), encoding="utf-8")
            (full / "storyboard.json").write_text(json.dumps(storyboard), encoding="utf-8")
            categories = {}
            for index, name in enumerate(VISUAL_VOCABULARY):
                categories[name] = (
                    {"status": "selected", "event_ids": [f"e{index}"], "evidence": ["fixture"]}
                    if index < 4 else
                    {"status": "not_applicable", "rationale": "not required",
                     "evidence": ["fixture"]}
                )
            vocabulary = {
                "categories": categories,
                "chapter_decisions": [{"chapter_id": "chapter-1", "evidence": ["fixture"],
                                       "selected_categories": [VISUAL_VOCABULARY[0]]}],
            }
            (sample / "visual-vocabulary-audit.json").write_text(
                json.dumps(vocabulary), encoding="utf-8")
            (full / "visual-vocabulary-audit.json").write_text(
                json.dumps(vocabulary), encoding="utf-8")
            (director_root / "sample-qa").mkdir()
            (director_root / "sample-qa" / "gate-report.json").write_text(
                json.dumps({"passed": True}), encoding="utf-8")
            (director_root / "full-qa").mkdir()
            commands_path = director_root / "full-hyperframes-commands.json"
            commands_path.write_text(json.dumps({
                "final_motion_render": {"expected_artifact": str(render),
                                        "argv": ["npx", "hyperframes", "render", "."],
                                        "cwd": str(full)}
            }), encoding="utf-8")
            full_qa = director_root / "full-qa"
            check_path = full_qa / "hyperframes-check.json"
            check_path.write_text(json.dumps({
                "ok": True,
                **{name: {"ok": True, "errorCount": 0}
                   for name in ("lint", "runtime", "layout", "contrast")},
                "motion": {"ok": True, "errorCount": 0, "enabled": True},
            }), encoding="utf-8")
            check_stdout = full_qa / "hyperframes-check-stdout.log"
            check_stderr = full_qa / "hyperframes-check-stderr.log"
            check_stdout.write_text(check_path.read_text(encoding="utf-8"), encoding="utf-8")
            check_stderr.write_text("", encoding="utf-8")
            check_command = json.loads(commands_path.read_text(encoding="utf-8")).get("check") or {
                "argv": ["npx", "hyperframes", "check"], "cwd": str(full),
            }
            # The compact audit fixture supplies the same command contract the Director emits.
            commands_payload = json.loads(commands_path.read_text(encoding="utf-8"))
            commands_payload["check"] = check_command
            commands_path.write_text(json.dumps(commands_payload), encoding="utf-8")
            check_receipt_path = full_qa / "hyperframes-check-receipt.json"
            check_receipt_path.write_text(json.dumps({
                "schema_version": 1, "owner": "director", "capability": "hyperframes_check",
                "status": "pass", "exit_code": 0,
                "command_sha256": __import__("hashlib").sha256(json.dumps(
                    check_command["argv"], ensure_ascii=False, sort_keys=True,
                    separators=(",", ":")
                ).encode("utf-8")).hexdigest(),
                "cwd": str(Path(check_command["cwd"]).resolve()),
                "storyboard_sha256": sha256_file(full / "storyboard.json"),
                "visual_vocabulary_sha256": sha256_file(full / "visual-vocabulary-audit.json"),
                "commands_sha256": sha256_file(commands_path),
                "toolchain_sha256": sha256_file(director_root / "toolchain-compatibility.json"),
                "check_report_sha256": sha256_file(check_path),
                "stdout_log": str(check_stdout), "stdout_sha256": sha256_file(check_stdout),
                "stderr_log": str(check_stderr), "stderr_sha256": sha256_file(check_stderr),
            }), encoding="utf-8")
            snapshots = []
            for index in range(4):
                path = full_qa / f"snapshot-{index}.png"
                path.write_bytes(b"snapshot")
                snapshots.append(str(path))
            review_path = full_qa / "snapshot-review.json"
            review_path.write_text(json.dumps({
                "status": "pass", "reviewed_snapshots": snapshots,
                "checks": {name: "pass" for name in (
                    "content_relevance", "visual_variety", "overlap", "overflow",
                    "caption_face_cursor_ui_safety", "motion_rhythm",
                )},
            }), encoding="utf-8")
            studio = full_qa / "studio.png"
            rendered_snapshot = full_qa / "render.png"
            studio.write_bytes(b"studio")
            rendered_snapshot.write_bytes(b"rendered")
            parity_path = full_qa / "preview-render-parity.json"
            parity_path.write_text(json.dumps({
                "schema_version": 1, "status": "pass",
                "tolerances": {"position_px": 4, "size_px": 4, "time_seconds": 0.05},
                "samples": [{
                    "event_id": "e0", "time_seconds": 1,
                    "studio_snapshot": str(studio), "render_snapshot": str(rendered_snapshot),
                    "studio_snapshot_sha256": sha256_file(studio),
                    "render_snapshot_sha256": sha256_file(rendered_snapshot),
                    "animation_phase": {"studio": "midpoint", "render": "midpoint"},
                    "elements": [{"selector": "#e0",
                                  "studio": {"x": 1, "y": 1, "width": 10, "height": 10,
                                             "visible": True},
                                  "render": {"x": 1, "y": 1, "width": 10, "height": 10,
                                             "visible": True}}],
                    "connectors": {"expected_count": 0, "studio_count": 0,
                                   "render_count": 0, "all_endpoints_attached": True,
                                   "clipped": False},
                    "cropping": {"studio_clipped": False, "render_clipped": False},
                    "caption_occlusion": {"studio": False, "render": False},
                }],
            }), encoding="utf-8")
            sample_audio = {
                "speech_track": {"dominant": True}, "provenance": ["source-audio"],
                "motion_sfx": {"event_decisions": [
                    {"event_id": event["id"], "decision": "intentionally_silent",
                     "reason": "fixture"} for event in events
                ]},
                "background_music": {"mode": "disabled", "reason": "fixture"},
            }
            (sample / "audio-plan.json").write_text(json.dumps(sample_audio), encoding="utf-8")
            sample_review_path = director_root / "sample-qa" / "aesthetic-review.json"
            sample_review_path.write_text(json.dumps({
                "verdict": "pass",
                "criteria": {name: {"status": "pass", "evidence": [str(studio)]}
                             for name in REQUIRED_CRITERIA},
                "technical_qa": {name: {"status": "pass"} for name in (
                    "hyperframes_check", "caption_sync", "overlap", "overflow", "decode",
                )},
                "reviewed_event_ids": [event["id"] for event in events],
                "snapshots": {event["id"]: {
                    phase: str(studio) for phase in (
                        "entrance", "midpoint", "pre_exit", "post_exit",
                    )} for event in events},
            }), encoding="utf-8")
            sample_gate_path = director_root / "sample-qa" / "gate-report.json"
            sample_gate_path.write_text(json.dumps({
                "schema_version": 2, "passed": True, "errors": [],
                "storyboard_sha256": sha256_file(sample / "storyboard.json"),
                "review_sha256": sha256_file(sample_review_path),
                "audio_plan_sha256": sha256_file(sample / "audio-plan.json"),
            }), encoding="utf-8")
            (director_root / "preview-approval.json").write_text(json.dumps({
                "approved": True, "approved_by": "test-user",
                "storyboard_sha256": sha256_file(sample / "storyboard.json"),
                "aesthetic_review_sha256": sha256_file(sample_review_path),
                "gate_report_sha256": sha256_file(sample_gate_path),
            }), encoding="utf-8")
            evidence_path = full_qa / "verified-evidence.json"
            evidence_path.write_text(json.dumps({
                "storyboard_sha256": sha256_file(full / "storyboard.json"),
                "visual_vocabulary_sha256": sha256_file(full / "visual-vocabulary-audit.json"),
                "commands_sha256": sha256_file(commands_path),
                "hyperframes_check_sha256": sha256_file(check_path),
                "hyperframes_check_receipt_sha256": sha256_file(check_receipt_path),
                "snapshot_review_sha256": sha256_file(review_path),
                "preview_render_parity_sha256": sha256_file(parity_path),
                "strict_check_passed": True, "snapshot_review_passed": True,
                "preview_render_parity_passed": True,
            }), encoding="utf-8")
            (director_root / "final-render-authorization.json").write_text(json.dumps({
                "authorized": True, "authorized_by": "test-user",
                "storyboard_sha256": sha256_file(full / "storyboard.json"),
                "visual_vocabulary_sha256": sha256_file(full / "visual-vocabulary-audit.json"),
                "commands_sha256": sha256_file(commands_path),
                "full_qa_evidence_sha256": sha256_file(evidence_path),
            }), encoding="utf-8")
            authorization_path = director_root / "final-render-authorization.json"
            render_stdout = director_root / "final-render-stdout.log"
            render_stderr = director_root / "final-render-stderr.log"
            render_stdout.write_text("rendered", encoding="utf-8")
            render_stderr.write_text("", encoding="utf-8")
            render_command = json.loads(commands_path.read_text(encoding="utf-8"))[
                "final_motion_render"
            ]
            (director_root / "final-render-receipt.json").write_text(json.dumps({
                "schema_version": 1, "owner": "director", "capability": "hyperframes_render",
                "status": "pass", "exit_code": 0,
                "command_sha256": __import__("hashlib").sha256(json.dumps(
                    render_command.get("argv") or [], ensure_ascii=False, sort_keys=True,
                    separators=(",", ":")
                ).encode("utf-8")).hexdigest(),
                "cwd": str(Path(render_command.get("cwd", "")).resolve()),
                "authorization_sha256": sha256_file(authorization_path),
                "full_qa_evidence_sha256": sha256_file(evidence_path),
                "storyboard_sha256": sha256_file(full / "storyboard.json"),
                "commands_sha256": sha256_file(commands_path),
                "toolchain_sha256": sha256_file(director_root / "toolchain-compatibility.json"),
                "output": str(render.resolve()), "output_sha256": sha256_file(render),
                "stdout_log": str(render_stdout), "stdout_sha256": sha256_file(render_stdout),
                "stderr_log": str(render_stderr), "stderr_sha256": sha256_file(render_stderr),
            }), encoding="utf-8")
            (director_root / "legacy-script-audit.json").write_text(
                json.dumps({"execution_allowed": False, "status": "pass"}), encoding="utf-8")
            (director_root / "refactor-change-report.md").write_text(
                "# Handoff\n\n## Automated verification\nAll bound tests and fixtures passed.\n\n"
                "## Manual gates\nAesthetic and identity review remain human-owned.\n\n"
                "## Limitations\nNo live platform publication was claimed.\n",
                encoding="utf-8",
            )
            evidence = director_root / "evidence" / "evidence-bundle.json"
            evidence.parent.mkdir()
            transcript = video_use = root / "edit" / "video-use"
            transcript.mkdir(parents=True)
            transcript = transcript / "transcripts" / "input.json"
            transcript.parent.mkdir()
            transcript.write_text(json.dumps({"words": [{
                "id": "w0", "type": "word", "text": "proof", "start": 0.0, "end": 1.0
            }]}), encoding="utf-8")
            frame = director_root / "evidence" / "frames" / "frame-00.png"
            frame.parent.mkdir()
            frame.write_bytes(b"frame")
            evidence.write_text(json.dumps({
                "transcript": {"sha256": sha256_file(transcript), "term_evidence": [{
                    "word_id": "w0", "text": "proof", "start": 0.0, "end": 1.0
                }]},
                "representative_frames": [{"path": str(frame), "sha256": sha256_file(frame)}],
            }), encoding="utf-8")
            semantic = director_root / "semantic-brief.json"
            semantic.write_text(json.dumps({
                "schema_version": 2, "generated_by": "test-llm",
                "content_reading": "raw_word_transcript_and_evidence_frames",
                "transcript_sha256": sha256_file(transcript),
                "evidence_bundle_sha256": sha256_file(evidence),
                "evidence_frames": [str(frame)],
                "opening_hook": {"status": "not_selected", "evidence": ["direct start"]},
                "events": [{
                    "id": "semantic-1", "anchor": "proof", "transcript_quote": "proof",
                    "transcript_word_ids": ["w0"], "source_start": 0.0, "source_end": 1.0,
                    "output_start": 0.0, "output_end": 1.0,
                    "viewer_job": "understand", "viewer_takeaway": "proof",
                    "visual_mechanism": "evidence focus", "target_frame_evidence": [str(frame)],
                    "protected_zones": {"face": [], "ui": [], "caption": [], "cursor": []},
                    "form": "focus", "placement": "center", "size": "medium",
                    "background": "transparent", "read_time": 1.0,
                    "motion": {"entrance": "fade", "reveal": "focus",
                               "hold": "steady", "exit": "fade"},
                    "audio_decision": {"type": "intentionally_silent", "reason": "fixture"},
                    "deduplication": {"semantic": "unique", "visual": "unique"},
                    "relevance_rationale": "direct transcript and frame evidence",
                    "visual_structure": {"dom_structure": "focus", "information_hierarchy": "one",
                        "layout_archetype": "center", "animation_choreography": "fade",
                        "use_case": "proof"},
                }],
            }), encoding="utf-8")
            project_data = migrate_project_config(
                yaml.safe_load(project.read_text(encoding="utf-8"))
            )
            inventory = build_capability_inventory(project_data)
            (director_root / "capability-inventory.json").write_text(
                json.dumps(inventory), encoding="utf-8")
            (director_root / "toolchain-compatibility.json").write_text(
                json.dumps(build_toolchain_report(probe_versions=False)), encoding="utf-8")
            edl = {"ranges": [{"start": 0, "end": 10}]}
            (video_use / "edl.json").write_text(json.dumps(edl), encoding="utf-8")
            production_path = director_root / "production-contract.json"
            production = build_contract(
                project=project_data, source_path=source, transcript_path=transcript,
                edl_path=video_use / "edl.json", semantic_brief_path=semantic,
                input_mode="preserve",
            )
            production_path.write_text(json.dumps(production), encoding="utf-8")
            project_hash = sha256_file(project)
            provider_path = director_root / "provider-decision.json"
            provider_path.write_text(json.dumps(build_decision_report(
                config=project_data["provider_governance"], project_hash=project_hash,
            )), encoding="utf-8")
            cost_path = director_root / "cost-ledger.json"
            cost_path.write_text(json.dumps(create_cost_ledger(
                config=project_data["provider_governance"], project_hash=project_hash,
            )), encoding="utf-8")
            full_semantic = director_root / "full-semantic-brief.json"
            full_semantic.write_bytes(semantic.read_bytes())
            sample_dynamics = director_root / "sample-qa" / "visual-dynamics-qa.json"
            sample_dynamics.write_text(json.dumps(build_visual_dynamics_report(
                storyboard_path=sample / "storyboard.json", semantic_brief_path=semantic,
                config=project_data["qa"]["visual_dynamics"],
                production_contract_path=production_path,
            )), encoding="utf-8")
            full_dynamics = full_qa / "visual-dynamics-qa.json"
            full_dynamics.write_text(json.dumps(build_visual_dynamics_report(
                storyboard_path=full / "storyboard.json", semantic_brief_path=full_semantic,
                config=project_data["qa"]["visual_dynamics"],
                production_contract_path=production_path,
            )), encoding="utf-8")
            design_tokens = root / "edit" / "design-tokens.json"
            design_tokens.write_text(json.dumps({
                "sampling": {"dimensions": {"width": 1280, "height": 720}},
                "surface": {"color": "#ffffff", "text_color": "#111111"},
                "accent": {"color": "#22aa88"}, "shape": {}, "shadow": {},
                "typography": {}, "safe_zones": {},
            }), encoding="utf-8")
            playbook_outputs = compile_playbook(
                project=project_data, design_tokens_path=design_tokens,
                semantic_brief_path=semantic, profile_path=None,
                output_dir=director_root / "brand-motion",
            )
            derived_decision = director_root / "derived-content" / "decision.json"
            derived_decision.parent.mkdir(parents=True)
            derived_decision.write_text(json.dumps({"schema_version": 1, "status": "disabled"}),
                                        encoding="utf-8")
            verified = json.loads(evidence_path.read_text(encoding="utf-8"))
            verified.update({
                "production_contract_sha256": sha256_file(production_path),
                "visual_dynamics_sha256": sha256_file(full_dynamics),
                "visual_dynamics_passed": True,
            })
            evidence_path.write_text(json.dumps(verified), encoding="utf-8")
            authorization = json.loads(authorization_path.read_text(encoding="utf-8"))
            authorization["full_qa_evidence_sha256"] = sha256_file(evidence_path)
            authorization_path.write_text(json.dumps(authorization), encoding="utf-8")
            receipt_path = director_root / "final-render-receipt.json"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            receipt["full_qa_evidence_sha256"] = sha256_file(evidence_path)
            receipt["authorization_sha256"] = sha256_file(authorization_path)
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            for name, payload in {
                "captions.json": {}, "media-analysis.json": {},
                "edit-correctness-preflight.json": {}, "caption-sync-report.json": {"passed": True},
            }.items():
                (video_use / name).write_text(json.dumps(payload), encoding="utf-8")
            views = []
            for name in ("first", "middle", "final"):
                view = video_use / f"{name}.png"
                view.write_bytes(b"png")
                views.append(str(view))
            (video_use / "final-edit-correctness.json").write_text(json.dumps({
                "owner": "video-use", "status": "pass", "output_sha256": output_hash,
                "expected_output_duration": 10, "actual_output_duration": 10,
                "boundary_reviews": [], "overview_timeline_views": views,
            }), encoding="utf-8")
            (full / "audio-plan.json").write_text(json.dumps({
                "speech_track": {"dominant": True},
                "provenance": ["source-audio"],
                "motion_sfx": {"event_decisions": [
                    {"event_id": event["id"], "decision": "intentionally_silent",
                     "reason": "fixture has no audible motion cue"}
                    for event in events
                ]},
                "background_music": {"mode": "disabled", "reason": "fixture"},
            }), encoding="utf-8")
            final_qa = director_root / "final-qa"
            final_qa.mkdir()
            final_snapshots = {
                event["id"]: {phase: str(studio)
                               for phase in ("entrance", "midpoint", "pre_exit", "post_exit")}
                for event in events
            }
            (final_qa / "aesthetic-review.json").write_text(json.dumps({
                "verdict": "pass", "reviewed_output_sha256": output_hash,
                "criteria": {name: {"status": "pass", "evidence": [str(studio)]}
                             for name in REQUIRED_CRITERIA},
                "technical_qa": {name: {"status": "pass"} for name in (
                    "hyperframes_check", "caption_sync", "overlap", "overflow", "decode",
                )},
                "reviewed_event_ids": [event["id"] for event in events],
                "snapshots": final_snapshots,
            }), encoding="utf-8")
            cover = root / "exports" / "cover-portrait.png"
            Image.new("RGB", (1080, 1920), "#173d31").save(cover)
            (final_qa / "cover-review.json").write_text(
                json.dumps({"status": "pass", "identity_approved_by_user": True,
                            "identity_reference_count": 2, "topic_relevant": True,
                            "natural_expression_and_energy": True,
                            "cover_sha256": sha256_file(cover)}), encoding="utf-8")
            run_technical_qa(
                output, output=director_root / "final-media-report.json",
                evidence_dir=final_qa / "technical-evidence", true_peak_ceiling=1.0,
            )
            presets = json.loads((ROOT / "references" / "platform-presets.json")
                                 .read_text(encoding="utf-8"))
            for platform in ("douyin", "wechat_channels"):
                safe = final_qa / f"{platform}-safe.jpg"
                crop = final_qa / f"{platform}-cover.jpg"
                preset = presets["platforms"][platform]
                platform_report = bind_cover(bind_universal_output(
                    validate(output, preset, platform, loudness(output), decode(output)), output,
                ), cover)
                platform_report.update({
                    "preset_version": presets["preset_version"],
                    "preset_verified_on": presets["verified_on"],
                    "sources": preset["sources"],
                    "recommendation_fields": preset["recommendation_fields"],
                })
                snapshot(output, preset["caption_safe_zone"], safe)
                cover_preview(cover, preset["cover"]["center_safe"], crop)
                platform_report.update({
                    "safe_zone_snapshot": str(safe),
                    "safe_zone_snapshot_sha256": sha256_file(safe),
                    "cover_crop_preview": str(crop),
                    "cover_crop_preview_sha256": sha256_file(crop),
                })
                (final_qa / f"platform-{platform}.json").write_text(
                    json.dumps(platform_report), encoding="utf-8")
            (director_root / "delivery-contract.json").write_text(json.dumps({
                "universal_video": str(output), "file_sha256": output_hash,
                "cover_sha256": sha256_file(cover), "duplicate_platform_mp4s": False,
                "production_contract_sha256": sha256_file(production_path),
                "provider_decision_sha256": sha256_file(provider_path),
                "cost_ledger_sha256": sha256_file(cost_path),
                "sample_visual_dynamics_sha256": sha256_file(sample_dynamics),
                "full_visual_dynamics_sha256": sha256_file(full_dynamics),
            }), encoding="utf-8")
            state_proof = director_root / "state-proof.json"
            state_proof.write_text("bound", encoding="utf-8")
            def stage_row(paths: list[Path]) -> dict:
                unique = list(dict.fromkeys(path.resolve() for path in paths))
                records = []
                for path in unique:
                    file_stat = path.stat()
                    records.append({"path": str(path), "available": True,
                                    "size": file_stat.st_size, "mtime_ns": file_stat.st_mtime_ns,
                                    "sha256": sha256_file(path)})
                return {"status": "complete", "artifacts": [str(path) for path in unique],
                        "artifact_records": records}
            stages = {name: stage_row([state_proof]) for name in STAGES}
            stages["sample_qa"] = stage_row([
                sample / "storyboard.json", sample_review_path, sample / "audio-plan.json",
                sample_gate_path, sample_dynamics, studio,
            ])
            stages["preview_approval"] = stage_row([director_root / "preview-approval.json"])
            stages["full_hyperframes_qa"] = stage_row([
                check_path, check_receipt_path, review_path, parity_path, evidence_path,
                production_path, full_dynamics,
                *[Path(path) for path in snapshots], studio, rendered_snapshot,
            ])
            stages["provider_governance"] = stage_row([provider_path, cost_path])
            stages["production_contract"] = stage_row([production_path])
            stages["brand_motion_playbook"] = stage_row(list(playbook_outputs))
            stages["derived_content"] = stage_row([derived_decision])
            stages["final_render"] = stage_row([
                render, authorization_path, director_root / "final-render-receipt.json",
                render_stdout, render_stderr,
            ])
            stages["delivery_qa"] = stage_row([
                output, cover, director_root / "delivery-contract.json",
                final_qa / "aesthetic-review.json", final_qa / "cover-review.json",
                video_use / "final-edit-correctness.json", director_root / "final-media-report.json",
                *[final_qa / f"platform-{name}.json"
                  for name in ("douyin", "wechat_channels")], studio,
                *[final_qa / f"{name}-{kind}.jpg"
                  for name in ("douyin", "wechat_channels") for kind in ("safe", "cover")],
            ])
            def input_record(path: Path) -> dict:
                file_stat = path.stat()
                return {"path": str(path.resolve()), "available": True,
                        "size": file_stat.st_size, "mtime_ns": file_stat.st_mtime_ns,
                        "sha256": sha256_file(path)}
            (director_root / "director-state.json").write_text(json.dumps({
                "schema_version": 6, "single_universal_output": True, "stages": stages,
                "input_fingerprints": {"project_file": input_record(project),
                                       "source_video": input_record(source)},
            }), encoding="utf-8")
            test_report = root / "tests.json"
            test_log = "\n".join([
                *(f"{test_id} (tests.synthetic.ReceiptTests.{test_id}) ... ok"
                  for test_id in REQUIRED_TEST_IDS),
                "Ran 5 tests in 1.0s", "", "OK",
            ])
            write_report_from_output(
                ROOT, test_log, test_report, root / "tests.log", returncode=0,
            )

            report = build(project, test_report=test_report)
            self.assertEqual(report["overall"], "pass", report)
            self.assertTrue(all(row["status"] == "pass" for row in report["criteria"].values()))

    def test_failed_six_fixture_report_is_a_negative_completion_gate(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source" / "input.mp4"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"video")
            project = root / "project.yaml"
            project.write_text(yaml.safe_dump({
                "version": 1, "video_id": "audit",
                "paths": {"root": str(root), "work": "work", "edit": "edit", "exports": "exports"},
                "source": {"primary_video": "source/input.mp4", "input_mode": "source_first"},
                "delivery": {"output": "exports/audit-universal.mp4"},
            }), encoding="utf-8")
            fixture_report = root / "six-fixture-acceptance.json"
            fixture_report.write_text(json.dumps({"status": "failed", "scenario_count": 6,
                                                  "missing_types": []}), encoding="utf-8")
            report = build(project, fixture_report=fixture_report)
            self.assertEqual(report["criteria"]["12_six_fixture_acceptance"]["status"], "failed")
            self.assertEqual(report["overall"], "failed")

    def test_forged_fixture_report_with_arbitrary_passing_check_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source" / "input.mp4"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"video")
            project = root / "project.yaml"
            project.write_text(yaml.safe_dump({
                "video_id": "audit",
                "paths": {"root": str(root), "work": "work", "edit": "edit",
                          "exports": "exports"},
                "source": {"primary_video": "source/input.mp4"},
            }), encoding="utf-8")
            fixture_report = root / "forged-fixtures.json"
            fixture_report.write_text(json.dumps({
                "status": "pass", "scenario_count": 6, "missing_types": [],
                "duplicate_types": [], "duplicate_ids": [],
                "scenarios": [{"id": f"fake-{index}", "fixture_type": fixture_type,
                               "status": "pass", "checks": [
                                   {"name": "anything", "status": "pass"}
                               ]}
                              for index, fixture_type in enumerate(sorted({
                                  "landscape_screen_tutorial", "portrait_talking_head",
                                  "published_edit_polish", "two_person_interview",
                                  "noisy_audio_hotwords", "screen_camera_mixed",
                              }))],
            }), encoding="utf-8")
            report = build(project, fixture_report=fixture_report)
            self.assertEqual(report["criteria"]["12_six_fixture_acceptance"]["status"],
                             "failed")

    def test_autonomous_pre_publish_still_uses_single_universal_delivery(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source" / "input.mp4"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"source")
            output = root / "exports" / "audit-universal.mp4"
            output.parent.mkdir(parents=True)
            output.write_bytes(b"universal")
            output_hash = sha256_file(output)
            project = root / "project.yaml"
            project.write_text(yaml.safe_dump({
                "video_id": "audit",
                "paths": {"root": str(root), "work": "work", "edit": "edit", "exports": "exports"},
                "source": {"primary_video": "source/input.mp4"},
                "delivery": {"mode": "autonomous_pre_publish",
                             "output": "exports/audit-universal.mp4"},
            }), encoding="utf-8")
            director_root = root / "work" / "director"
            final_qa = director_root / "final-qa"
            final_qa.mkdir(parents=True)
            (director_root / "director-state.json").write_text(json.dumps({
                "single_universal_output": True, "stages": {}
            }), encoding="utf-8")
            for platform in ("douyin", "wechat_channels"):
                (final_qa / f"platform-{platform}.json").write_text(json.dumps({
                    "status": "pass", "file_sha256": output_hash
                }), encoding="utf-8")
            report = build(project)
            self.assertEqual(report["criteria"]["8_single_universal_delivery"]["status"], "pass")

    def test_capability_gate_rejects_bare_names_without_routes_or_maturity(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source" / "input.mp4"
            source.parent.mkdir(parents=True)
            source.write_bytes(b"source")
            project = root / "project.yaml"
            project.write_text(yaml.safe_dump({
                "video_id": "audit",
                "paths": {"root": str(root), "work": "work", "edit": "edit", "exports": "exports"},
                "source": {"primary_video": "source/input.mp4"},
            }), encoding="utf-8")
            director_root = root / "work" / "director"
            (director_root / "evidence").mkdir(parents=True)
            (director_root / "director-state.json").write_text(json.dumps({
                "stages": {"evidence_acquisition": {"status": "complete"},
                           "semantic_brief": {"status": "complete"}}
            }), encoding="utf-8")
            (director_root / "capability-inventory.json").write_text(json.dumps({
                "capabilities": [{"name": "video_use_timeline"}]
            }), encoding="utf-8")
            (director_root / "evidence" / "evidence-bundle.json").write_text("{}", encoding="utf-8")
            (director_root / "semantic-brief.json").write_text("{}", encoding="utf-8")
            report = build(project)
            self.assertEqual(report["criteria"]["13_capability_and_evidence_contract"]["status"],
                             "pending")

    def test_audit_is_honestly_pending_when_full_render_is_paused(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source" / "input.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video")
            project = root / "project.yaml"
            project.write_text(yaml.safe_dump({
                "video_id": "audit",
                "paths": {"root": str(root), "work": "work", "edit": "edit", "exports": "exports"},
                "source": {"primary_video": "source/input.mp4"},
                "delivery": {"mode": "single_universal_export", "output": "exports/audit-universal.mp4"},
            }), encoding="utf-8")
            director_root = root / "work" / "director"
            director_root.mkdir(parents=True)
            state = {
                "single_universal_output": True,
                "stages": {name: {"status": "complete" if name in {
                    "inspect", "video_use_timeline", "semantic_brief", "hyperframes_storyboard", "sample_qa"
                } else "pending"} for name in STAGES},
            }
            (director_root / "director-state.json").write_text(json.dumps(state), encoding="utf-8")
            (director_root / "legacy-script-audit.json").write_text(
                json.dumps({"execution_allowed": False, "status": "legacy_quarantined"}), encoding="utf-8"
            )
            video_use = root / "edit" / "video-use"
            video_use.mkdir(parents=True)
            for name, content in {
                "edl.json": {}, "captions.json": {}, "caption-sync-report.json": {"passed": True}
            }.items():
                (video_use / name).write_text(json.dumps(content), encoding="utf-8")
            sample = root / "hyperframes-director"
            sample.mkdir()
            events = []
            for index in range(4):
                events.append({"id": f"e{index}", "visual_structure": {
                    "dom_structure": f"dom-{index}", "information_hierarchy": f"hierarchy-{index}",
                    "layout_archetype": f"layout-{index}", "animation_choreography": f"motion-{index}",
                    "use_case": f"case-{index}",
                }})
            (sample / "storyboard.json").write_text(json.dumps({"events": events}), encoding="utf-8")
            (sample / "visual-vocabulary-audit.json").write_text("{}", encoding="utf-8")
            sample_qa = director_root / "sample-qa"
            sample_qa.mkdir()
            (sample_qa / "gate-report.json").write_text(json.dumps({"passed": True}), encoding="utf-8")
            tests = root / "test-report.json"
            tests.write_text(json.dumps({"passed": True, "test_count": 5}), encoding="utf-8")

            report = build(project, tests)
            self.assertEqual(report["overall"], "pending")
            self.assertEqual(report["criteria"]["4_actual_hyperframes_final_render"]["status"], "pending")
            self.assertEqual(report["criteria"]["8_single_universal_delivery"]["status"], "pending")
            self.assertTrue(any("has not completed" in item for item in report["limitations"]))

    def test_completed_status_with_empty_qa_and_authorization_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source" / "input.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video")
            project = root / "project.yaml"
            project.write_text(yaml.safe_dump({
                "video_id": "audit",
                "paths": {"root": str(root), "work": "work", "edit": "edit", "exports": "exports"},
                "source": {"primary_video": "source/input.mp4"},
                "delivery": {"mode": "single_universal_export", "output": "exports/audit-universal.mp4"},
            }), encoding="utf-8")
            director_root = root / "work" / "director"
            director_root.mkdir(parents=True)
            state = {
                "single_universal_output": True,
                "stages": {name: {"status": "complete" if name in {
                    "full_hyperframes_qa", "final_render"
                } else "pending"} for name in STAGES},
            }
            (director_root / "director-state.json").write_text(json.dumps(state), encoding="utf-8")
            full = root / "hyperframes-director-full"
            full.mkdir()
            render = director_root / "render" / "full.mp4"
            render.parent.mkdir()
            render.write_bytes(b"render")
            (director_root / "full-hyperframes-commands.json").write_text(json.dumps({
                "final_motion_render": {"expected_artifact": str(render)}
            }), encoding="utf-8")
            qa = director_root / "full-qa"
            qa.mkdir()
            (qa / "verified-evidence.json").write_text("{}", encoding="utf-8")
            (director_root / "final-render-authorization.json").write_text("{}", encoding="utf-8")

            report = build(project)
            self.assertEqual(report["criteria"]["4_actual_hyperframes_final_render"]["status"],
                             "pending")
            self.assertTrue(any("has not completed" in item for item in report["limitations"]))

    def test_manual_finish_audit_rejects_unbound_placeholder_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source" / "input.mp4"
            source.parent.mkdir()
            source.write_bytes(b"video")
            returned = root / "exports" / "audit-manual-finish.mp4"
            returned.parent.mkdir()
            returned.write_bytes(b"manual")
            project = root / "project.yaml"
            project.write_text(yaml.safe_dump({
                "video_id": "audit",
                "paths": {"root": str(root), "work": "work", "edit": "edit", "exports": "exports"},
                "source": {"primary_video": "source/input.mp4"},
                "delivery": {
                    "mode": "single_universal_export",
                    "output": "exports/audit-universal.mp4",
                    "manual_finish": {
                        "enabled": True,
                        "backend": "opencut",
                        "returned_final": "exports/audit-manual-finish.mp4",
                    },
                },
            }), encoding="utf-8")
            director_root = root / "work" / "director"
            manual_dir = director_root / "manual-finish"
            manual_dir.mkdir(parents=True)
            state = {
                "single_universal_output": True,
                "stages": {name: {"status": "complete" if name == "manual_finish_handoff" else "pending"}
                           for name in STAGES},
            }
            (director_root / "director-state.json").write_text(json.dumps(state), encoding="utf-8")
            for name in (
                "handoff-manifest.json", "correction-ledger.json", "return-receipt.json",
                "manual-final-media-report.json", "manual-final-qa.json",
            ):
                (manual_dir / name).write_text("{}", encoding="utf-8")

            report = build(project)

            self.assertEqual(report["criteria"]["11_optional_manual_finish_handoff"]["status"], "pending")
            self.assertTrue(any("fresh revalidation" in item for item in report["limitations"]))


if __name__ == "__main__":
    unittest.main()
