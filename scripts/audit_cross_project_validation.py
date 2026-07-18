#!/usr/bin/env python3
"""Create durable cross-project evidence for the roadmap validation gate."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def probe(path: Path):
    result = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration:stream=codec_type,width,height", "-of", "json", str(path)],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    data = json.loads(result.stdout)
    video = next(stream for stream in data["streams"] if stream["codec_type"] == "video")
    return {
        "duration": round(float(data["format"]["duration"]), 3),
        "dimensions": [video["width"], video["height"]],
        "orientation": "portrait" if video["height"] > video["width"] else "landscape",
        "audio_present": any(stream["codec_type"] == "audio" for stream in data["streams"]),
    }


def hyperframes_check(project: Path):
    result = subprocess.run(
        ["npx.cmd", "--yes", "hyperframes", "check", "--json"],
        cwd=project,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=180,
    )
    data = json.loads(result.stdout)
    data["process_exit_code"] = result.returncode
    return data


def platform_summary(root: Path, report_dir: Path):
    rows = []
    for platform in ("douyin", "wechat-channels"):
        report = load(report_dir / f"platform-{platform}.json")
        rows.append({
            "platform": report["platform"],
            "passed": report["passed"],
            "recommendation_warnings": report["recommendation_warnings"],
            "preset_version": report["preset_version"],
            "preset_verified_on": report["preset_verified_on"],
            "media": report["media"],
        })
    return rows


def publishing_gate(path: Path):
    data = load(path)
    expected = "Publishing/upload requires explicit user action."
    return all(data[name]["external_action_gate"] == expected for name in ("douyin", "wechat_channels"))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tabout-root", required=True)
    parser.add_argument("--talk-root", required=True)
    parser.add_argument("--out", required=True)
    args = parser.parse_args()
    tabout = Path(args.tabout_root)
    talk = Path(args.talk_root)
    tabout_reports = tabout / "edit" / "reports"
    talk_reports = talk / "edit" / "reports"

    tabout_video = tabout / "exports" / "tabout-preserve-v2-social-normalized.mp4"
    talk_video = talk / "exports" / "talk-with-gpt-live-social-normalized.mp4"
    tabout_cover = load(tabout / "covers" / "generative-v2" / "cover-manifest.json")
    talk_cover = load(talk / "covers" / "generative-v2" / "cover-manifest.json")
    tabout_cover_ab = load(tabout / "covers" / "generative-v2" / "cover-ab-report-v2.json")
    talk_cover_ab = load(talk / "covers" / "generative-v2" / "cover-ab-report.json")
    tabout_platform = platform_summary(tabout, tabout_reports)
    talk_platform = platform_summary(talk, talk_reports)
    tabout_hf = hyperframes_check(tabout / "hyperframes")
    talk_hf = hyperframes_check(talk / "hyperframes")
    tabout_occlusion = load(tabout_reports / "occlusion-wechat-channels.json")
    talk_occlusion = load(talk_reports / "occlusion-douyin.json")
    cache = load(talk_reports / "render-cache-status.json")

    checks = {
        "opposite_orientations": {probe(tabout_video)["orientation"], probe(talk_video)["orientation"]} == {"landscape", "portrait"},
        "both_videos_over_six_minutes_with_audio": all(item["duration"] >= 360 and item["audio_present"] for item in (probe(tabout_video), probe(talk_video))),
        "both_hyperframes_projects_pass": tabout_hf["ok"] and talk_hf["ok"],
        "both_platform_packages_pass_without_recommendation_warnings": all(row["passed"] and not row["recommendation_warnings"] for row in tabout_platform + talk_platform),
        "both_covers_use_reference_guided_generation": all(cover["passed"] and cover["generation_mode"] == "reference_guided_regeneration" and len(cover["identity_references"]) >= 2 and cover["identity_qa"]["agent_visual_review_passed"] for cover in (tabout_cover, talk_cover)),
        "both_generative_cover_ab_reports_pass": tabout_cover_ab["passed"] and talk_cover_ab["passed"],
        "design_tokens_exist_for_both": (tabout / "edit" / "design-tokens.json").is_file() and (talk / "edit" / "design-tokens.json").is_file(),
        "tabout_components_and_motion_qa_pass": load(tabout / "edit" / "asset-components.json")["overall_passed"] and load(tabout_reports / "motion-snapshot-qa.json")["passed"],
        "talk_subject_tracking_and_reference_guided_cover_exist": (talk_reports / "subject-track.json").is_file() and talk_cover["generation_mode"] == "reference_guided_regeneration",
        "cache_interruption_resumed_without_extraction": cache["state"] == "completed" and cache["stages"]["extraction"]["state"] == "reused",
        "approved_preferences_applied_to_both": load(tabout / "edit" / "applied-motion-preferences.json")["enabled"] and load(talk / "edit" / "applied-motion-preferences.json")["enabled"],
        "preserve_pacing_audits_do_not_change_edl": load(tabout_reports / "hook-pacing-audit.json")["preserve_mode_edl_unchanged"] and load(talk_reports / "hook-pacing-audit.json")["preserve_mode_edl_unchanged"],
        "publishing_remains_explicit": publishing_gate(tabout / "publish-metadata-v2.json") and publishing_gate(talk / "publish-metadata.json"),
    }
    review_warnings = [
        {
            "project": "TabOut",
            "kind": "optional_platform_ui_template",
            "finding_count": len(tabout_occlusion["findings"]),
            "evidence": str(tabout_reports / "occlusion-wechat-channels.json"),
            "action": "review caption and facecam against the current WeChat Channels UI before publishing",
        },
        {
            "project": "talk-with-gpt-live",
            "kind": "optional_platform_ui_template",
            "finding_count": len(talk_occlusion["findings"]),
            "evidence": str(talk_reports / "occlusion-douyin.json"),
            "action": "review burned captions against the current Douyin description and action zones before publishing",
        },
    ]
    report = {
        "schema_version": 1,
        "roadmap": "Phase 0.5 through Phase 4",
        "projects": {
            "TabOut": {"video": str(tabout_video), "probe": probe(tabout_video), "platforms": tabout_platform, "hyperframes": tabout_hf},
            "talk-with-gpt-live": {"video": str(talk_video), "probe": probe(talk_video), "platforms": talk_platform, "hyperframes": talk_hf},
        },
        "checks": checks,
        "review_warnings": review_warnings,
        "passed": all(checks.values()),
        "external_actions_performed": [],
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(out)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
