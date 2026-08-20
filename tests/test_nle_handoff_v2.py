from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from PIL import Image


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director_contracts import sha256_file  # noqa: E402
from nle_handoff_v2 import (  # noqa: E402
    NleHandoffError,
    build_nle_handoff_package,
    validate_compatibility_report,
    validate_layer_asset,
    validate_layer_timeline,
    validate_nle_handoff_package,
)
from nle_outro import (  # noqa: E402
    NleOutroError,
    archive_modular_outro_project,
    build_modular_outro_project,
    record_modular_outro_render_approval,
    validate_modular_outro_render_approval,
    validate_modular_outro_contract,
)
import nle_layer_materializer as layer_materializer  # noqa: E402
import nle_handoff_v2 as handoff_v2  # noqa: E402


class NleHandoffV2Tests(unittest.TestCase):
    def _authorities(self, root: Path) -> dict[str, Path]:
        values: dict[str, Path] = {}
        for name, content in {
            "project.yaml": "schema_version: 12\n",
            "source.mp4": "source",
            "automatic.mp4": "automatic",
            "edl.json": json.dumps({
                "owner": "video-use",
                "sources": {"input": str(root / "source.mp4")},
                "ranges": [{
                    "id": "c1", "source": "input", "start": 0.0, "end": 2.0,
                    "timeline_start": 0.0,
                }],
                "gaps": [], "transitions": [], "metadata": {"video_id": "fixture"},
            }),
        }.items():
            path = root / name
            path.write_text(content, encoding="utf-8")
            values[name] = path
        return values

    def test_layer_asset_rejects_unavailable_hash_nan_and_fake_alpha_mp4(self) -> None:
        unavailable = {
            "schema_version": 2, "asset_id": "motion", "role": "motion_event",
            "status": "unavailable", "editability_class": "unavailable",
            "path": None, "sha256": "0" * 64, "size_bytes": None, "media_type": None,
            "purpose": "motion", "provenance": "none", "rights_status": "unavailable",
            "reason": "not rendered",
        }
        self.assertTrue(validate_layer_asset(unavailable, package_root=Path.cwd()))

        available = dict(unavailable)
        available.update({
            "status": "available", "editability_class": "media_layer_editable",
            "path": "overlay.mp4", "sha256": "0" * 64, "size_bytes": 1,
            "media_type": "video/mp4", "rights_status": "project_authorized",
            "timeline": {"start_seconds": 0.0, "end_seconds": math.nan, "frame_rate": 25.0},
            "video": {"width": 100, "height": 100, "pixel_format": "yuv420p",
                      "alpha_status": "verified"},
        })
        errors = validate_layer_asset(available, package_root=Path.cwd())
        self.assertTrue(any("finite" in row for row in errors))
        self.assertTrue(any("MP4" in row for row in errors))

    def test_timeline_rejects_bool_numbers_duplicate_ids_and_wrong_ranges(self) -> None:
        timeline = {
            "schema_version": 2, "authority": "video-use-output-timeline",
            "origin_seconds": 0, "duration_seconds": 2.0, "frame_rate": 25.0,
            "canvas": {"width": True, "height": 1920},
            "tracks": [{
                "track_id": "v1", "role": "base_video", "order": 0,
                "clips": [
                    {"clip_id": "c", "asset_id": "base", "timeline_start": 1.0,
                     "timeline_end": 0.5, "source_start": 0.0, "source_end": 1.0},
                    {"clip_id": "c", "asset_id": "base", "timeline_start": 0.0,
                     "timeline_end": 1.0, "source_start": 0.0, "source_end": 1.0},
                ],
            }],
            "markers": [],
        }
        errors = validate_layer_timeline(timeline)
        self.assertTrue(any("canvas" in row for row in errors))
        self.assertTrue(any("duplicate" in row for row in errors))
        self.assertTrue(any("range" in row for row in errors))

    def test_timeline_extends_for_appended_outro_without_extending_base_media(self) -> None:
        edl = {
            "owner": "video-use", "sources": {"input": "source.mp4"},
            "ranges": [{"id": "c1", "source": "input", "start": 0.0, "end": 2.0,
                        "timeline_start": 0.0}],
            "gaps": [], "transitions": [], "metadata": {"video_id": "fixture"},
        }
        assets = [
            {"asset_id": "base", "role": "clean_a_roll", "status": "available"},
            {"asset_id": "outro", "role": "outro_overlay", "status": "available",
             "timeline": {"start_seconds": 2.0, "end_seconds": 6.0, "frame_rate": 30.0}},
        ]
        timeline = handoff_v2._timeline(edl, assets, rate=30.0, width=1080, height=1920)
        self.assertEqual(timeline["duration_seconds"], 6.0)
        base = next(row for row in timeline["tracks"] if row["role"] == "base_video")
        self.assertEqual(base["clips"][0]["timeline_end"], 2.0)
        outro = next(row for row in timeline["tracks"] if row["role"] == "outro")
        self.assertEqual(outro["clips"][0]["timeline_start"], 2.0)

    def test_compatibility_never_claims_native_editor_automation(self) -> None:
        report = {
            "schema_version": 2, "status": "pending",
            "package_profile": "jianying_desktop_compatible_v1",
            "editor": {"name": "Jianying Desktop", "version": "unverified",
                       "platform": "Windows", "observed_at": "2026-08-13T00:00:00Z"},
            "capabilities": {"native_draft": True, "api": False, "cli": False,
                             "headless_render": False, "srt_import": False},
            "format_results": [{
                "format_id": "srt", "asset_sha256": "0" * 64, "imported": False,
                "decoded": True, "editable_class": "reference_only",
                "finding": "human canary pending",
            }],
            "human_canary": {"actor": "HongRun", "status": "pending",
                             "tasks": [{"task_id": str(i), "status": "pending"}
                                       for i in range(5)],
                             "reason": "not run"},
        }
        self.assertTrue(any("native" in row for row in validate_compatibility_report(report)))

    def test_builds_deterministic_balanced_package_and_detects_nested_drift(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            auth = self._authorities(root)
            clean = root / "clean.mp4"; clean.write_bytes(b"clean")
            captions = root / "master.srt"; captions.write_text(
                "1\n00:00:00,000 --> 00:00:02,000\nhello\n", encoding="utf-8",
            )
            sfx = root / "cue.wav"; sfx.write_bytes(b"cue")
            package = root / "manual-finish" / "nle-package-v2"
            receipt = build_nle_handoff_package(
                package_root=package,
                authorized_root=root,
                project_path=auth["project.yaml"], source_path=auth["source.mp4"],
                automatic_master=auth["automatic.mp4"], edl_path=auth["edl.json"],
                implementation_sha256=sha256_file(ROOT / "scripts" / "nle_handoff_v2.py"),
                package_level="balanced", frame_rate=25.0, width=1080, height=1920,
                assets={"clean_a_roll": clean, "caption_srt": captions, "sfx_event": [{
                    "path": sfx, "semantic_event_id": "semantic-1", "render_event_id": "event-1",
                    "timeline": {"start_seconds": 0.5, "end_seconds": 1.0,
                                 "frame_rate": 25.0},
                }]},
            )
            receipt_path = package / "10-evidence" / "nle-handoff-package.json"
            self.assertEqual(receipt["status"], "action_required")
            self.assertEqual(validate_nle_handoff_package(receipt_path), [])
            guide_path = package / "08-timeline" / "import-order.md"
            self.assertTrue(guide_path.is_file())
            guide = guide_path.read_text(encoding="utf-8")
            self.assertIn("剪映专业版手动导入与调整指南", guide)
            self.assertIn("素材 → 导入", guide)
            self.assertIn("文本 → 新建文本 → 导入本地字幕", guide)
            self.assertIn("事件音效不能全部放在 0 秒", guide)
            self.assertIn("不包含剪映原生草稿", guide)
            inventory_paths = {
                row["path"] for row in receipt["complete_file_inventory"]
            }
            for name in (
                "01-empty-project.png", "02-import-subtitles.png",
                "03-audio-panel.png", "04-project-settings.png",
            ):
                screenshot = package / "08-timeline" / "screenshots" / name
                self.assertTrue(screenshot.is_file(), name)
                self.assertIn(f"screenshots/{name}", guide)
                self.assertIn(
                    f"08-timeline/screenshots/{name}", inventory_paths,
                )
            self.assertFalse(receipt["capability_claims"]["native_draft"])
            timeline = json.loads((package / "08-timeline" / "layer-timeline.json").read_text(encoding="utf-8"))
            sfx_track = next(row for row in timeline["tracks"] if row["role"] == "sfx")
            self.assertEqual(sfx_track["clips"][0]["timeline_start"], 0.5)

            screenshot = package / "08-timeline" / "screenshots" / "01-empty-project.png"
            screenshot_bytes = screenshot.read_bytes()
            screenshot.write_bytes(b"stale screenshot")
            self.assertTrue(any(
                "guide screenshot" in row
                for row in validate_nle_handoff_package(receipt_path)
            ))
            screenshot.write_bytes(screenshot_bytes)
            self.assertEqual(validate_nle_handoff_package(receipt_path), [])

            copied = package / "02-captions" / "master.srt"
            copied.write_text("changed", encoding="utf-8")
            self.assertTrue(any("stale" in row for row in validate_nle_handoff_package(receipt_path)))

    def test_disabled_builder_does_not_create_package(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            auth = self._authorities(root)
            package = root / "manual-finish" / "nle-package-v2"
            with self.assertRaisesRegex(NleHandoffError, "disabled"):
                build_nle_handoff_package(
                    package_root=package, authorized_root=root,
                    project_path=auth["project.yaml"], source_path=auth["source.mp4"],
                    automatic_master=auth["automatic.mp4"], edl_path=auth["edl.json"],
                    implementation_sha256=sha256_file(ROOT / "scripts" / "nle_handoff_v2.py"), package_level="balanced",
                    frame_rate=25.0, width=1080, height=1920, assets={}, enabled=False,
                )
            self.assertFalse(package.exists())

    def test_personal_ip_and_outro_assets_require_current_rights_evidence(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            auth = self._authorities(root)
            clean = root / "clean.mp4"; clean.write_bytes(b"clean")
            captions = root / "master.srt"; captions.write_text("caption", encoding="utf-8")
            ip_source = root / "ip.png"
            Image.new("RGBA", (32, 32), (10, 120, 80, 255)).save(ip_source)
            package = root / "manual-finish" / "nle-package-v2"
            with self.assertRaisesRegex(NleHandoffError, "rights evidence"):
                build_nle_handoff_package(
                    package_root=package, authorized_root=root,
                    project_path=auth["project.yaml"], source_path=auth["source.mp4"],
                    automatic_master=auth["automatic.mp4"], edl_path=auth["edl.json"],
                    implementation_sha256=sha256_file(ROOT / "scripts" / "nle_handoff_v2.py"),
                    package_level="balanced", frame_rate=25.0, width=1080, height=1920,
                    assets={"clean_a_roll": clean, "caption_srt": captions,
                            "ip_source": ip_source},
                )

            rights = root / "ip-rights.json"
            rights_payload = {
                "schema_version": 1,
                "kind": "nle_asset_rights",
                "status": "authorized",
                "asset": {"path": str(ip_source.resolve()),
                          "sha256": sha256_file(ip_source)},
                "allowed_roles": ["ip_source"],
                "identity_mode": "self",
                "rights_basis": "user-owned project-generated personal IP asset",
                "redistribution_authorized": True,
            }
            rights.write_text(json.dumps(rights_payload), encoding="utf-8")
            receipt = build_nle_handoff_package(
                package_root=package, authorized_root=root,
                project_path=auth["project.yaml"], source_path=auth["source.mp4"],
                automatic_master=auth["automatic.mp4"], edl_path=auth["edl.json"],
                implementation_sha256=sha256_file(ROOT / "scripts" / "nle_handoff_v2.py"),
                package_level="balanced", frame_rate=25.0, width=1080, height=1920,
                assets={"clean_a_roll": clean, "caption_srt": captions, "ip_source": {
                    "path": ip_source,
                    "rights_status": "redistribution_authorized",
                    "provenance": "HongRun current personal-IP library",
                    "rights_evidence": {"path": rights, "sha256": sha256_file(rights)},
                }},
            )
            ip_row = next(row for row in receipt["assets"] if row["role"] == "ip_source")
            self.assertEqual(ip_row["rights_status"], "redistribution_authorized")
            self.assertEqual(ip_row["provenance"], "HongRun current personal-IP library")
            self.assertEqual(
                validate_nle_handoff_package(
                    package / "10-evidence" / "nle-handoff-package.json"
                ),
                [],
            )
            copied_rights = package / ip_row["rights_evidence"]["path"]
            copied_rights.write_text("{}", encoding="utf-8")
            self.assertTrue(any(
                "rights evidence" in error
                for error in validate_nle_handoff_package(
                    package / "10-evidence" / "nle-handoff-package.json"
                )
            ))

    def test_builds_deterministic_luminous_modular_outro_source_project(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = root / "profile.json"
            profile.write_text(json.dumps({
                "schema_version": 1,
                "profile_id": "hongrun",
                "profile_version": "2.0.0",
                "identity_mode": "self",
                "status": "proposed",
                "direction": "luminous_intelligence",
                "palettes": {
                    "dark": {"canvas": "#071A1A", "ink": "#F8FAFC",
                             "mint": "#34D399", "cyan": "#22D3EE",
                             "warm": "#F6C177", "violet": "#A78BFA"},
                },
                "typography": {"font_family": "Noto Sans SC"},
            }, ensure_ascii=False), encoding="utf-8")
            output = root / "work" / "outro-project"
            runtime = root / "gsap-3.14.2.min.js"
            runtime.write_text("window.gsap={};", encoding="utf-8")
            contract = build_modular_outro_project(
                output_root=output,
                authorized_root=root,
                profile_path=profile,
                gsap_runtime_path=runtime,
                width=1080,
                height=1920,
                frame_rate=30.0,
                duration_seconds=4.0,
                copy={
                    "headline": "关注 HongRun",
                    "actions": ["点赞", "转发", "收藏"],
                    "supporting": "一起把想法做出来",
                },
            )
            contract_path = output / "outro-contract.json"
            self.assertEqual(validate_modular_outro_contract(contract_path), [])
            html = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn('document.querySelectorAll(".action span")', html)
            self.assertIn("actionLabels.forEach((node) => node.remove())", html)
            self.assertIn("if (vars.showCopy) tl.fromTo(\"#meta\"", html)
            self.assertEqual(contract["direction"], "luminous_intelligence")
            self.assertTrue((output / "index.html").is_file())
            self.assertTrue((output / "copy.json").is_file())
            self.assertTrue((output / "timing.json").is_file())
            self.assertEqual(len(list((output / "icons").glob("*.svg"))), 3)
            html_text = (output / "index.html").read_text(encoding="utf-8")
            self.assertIn('icons/like.svg" alt=""/><span>点赞</span>', html_text)
            self.assertIn('icons/share.svg" alt=""/><span>转发</span>', html_text)
            self.assertIn('icons/favorite.svg" alt=""/><span>收藏</span>', html_text)
            archive = archive_modular_outro_project(
                source_root=output,
                archive_path=root / "work" / "outro-source-project.zip",
                authorized_root=root,
            )
            self.assertTrue(Path(archive["path"]).is_file())
            self.assertTrue(Path(archive["rights_evidence"]["path"]).is_file())
            archive_hash = sha256_file(Path(archive["path"]))
            archive_modular_outro_project(
                source_root=output,
                archive_path=root / "work" / "outro-source-project.zip",
                authorized_root=root,
            )
            self.assertEqual(archive_hash, sha256_file(Path(archive["path"])))
            first_hash = sha256_file(contract_path)
            build_modular_outro_project(
                output_root=output,
                authorized_root=root,
                profile_path=profile,
                gsap_runtime_path=runtime,
                width=1080,
                height=1920,
                frame_rate=30.0,
                duration_seconds=4.0,
                copy={
                    "headline": "关注 HongRun",
                    "actions": ["点赞", "转发", "收藏"],
                    "supporting": "一起把想法做出来",
                },
            )
            self.assertEqual(first_hash, sha256_file(contract_path))

            malformed = json.loads(contract_path.read_text(encoding="utf-8"))
            malformed["canvas"]["width"] = True
            malformed["integrity_sha256"] = "0" * 64
            contract_path.write_text(json.dumps(malformed), encoding="utf-8")
            self.assertTrue(validate_modular_outro_contract(contract_path))

    def test_modular_outro_rejects_unapproved_direction_and_redirected_output(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = root / "profile.json"
            profile.write_text(json.dumps({
                "schema_version": 1, "profile_id": "hongrun",
                "profile_version": "2.0.0", "identity_mode": "self",
                "status": "proposed", "direction": "humanist_cinema",
                "palettes": {"dark": {}}, "typography": {"font_family": "Noto Sans SC"},
            }), encoding="utf-8")
            runtime = root / "gsap-3.14.2.min.js"
            runtime.write_text("window.gsap={};", encoding="utf-8")
            with self.assertRaisesRegex(NleOutroError, "luminous_intelligence"):
                build_modular_outro_project(
                    output_root=root / "out", authorized_root=root,
                    profile_path=profile, gsap_runtime_path=runtime,
                    width=1080, height=1920,
                    frame_rate=30.0, duration_seconds=4.0,
                    copy={"headline": "关注", "actions": ["点赞"], "supporting": "继续"},
                )

    def test_records_current_modular_outro_render_approval_without_secret(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            profile = root / "profile.json"
            profile.write_text(json.dumps({
                "schema_version": 1, "profile_id": "hongrun", "profile_version": "2.0.0",
                "identity_mode": "self", "status": "proposed", "direction": "luminous_intelligence",
                "palettes": {"dark": {"canvas": "#071A1A", "ink": "#F8FAFC", "mint": "#34D399",
                                      "cyan": "#22D3EE", "warm": "#F6C177", "violet": "#A78BFA"}},
                "typography": {"font_family": "Noto Sans SC"},
            }), encoding="utf-8")
            runtime = root / "gsap.js"; runtime.write_text("runtime", encoding="utf-8")
            source = root / "source"
            build_modular_outro_project(
                output_root=source, authorized_root=root, profile_path=profile,
                gsap_runtime_path=runtime, width=1080, height=1920, frame_rate=30.0,
                duration_seconds=4.0,
                copy={"headline": "关注 HongRun", "actions": ["点赞"], "supporting": "继续"},
            )
            snapshot = root / "preview.png"; Image.new("RGB", (8, 8), "black").save(snapshot)
            approval_path = root / "approval.json"
            receipt = record_modular_outro_render_approval(
                contract_path=source / "outro-contract.json", snapshot_path=snapshot,
                output_path=approval_path, authorized_root=root, actor="HongRun",
                decision="approve_render", reason="批准片尾预览，允许渲染 4 秒透明片尾层和参考合成",
                approved_at="2026-08-19T00:00:00Z",
            )
            self.assertEqual(validate_modular_outro_render_approval(approval_path), [])
            self.assertIn("not identity authentication", receipt["integrity_notice"])
            snapshot.write_bytes(b"stale")
            self.assertTrue(validate_modular_outro_render_approval(approval_path))

    def test_materializes_fresh_alpha_evidence_for_existing_outro_render(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            overlay = root / "outro.mov"; overlay.write_bytes(b"rendered-prores")
            evidence_dir = root / "evidence"
            probe = {
                "codec_name": "prores", "profile": "4444", "width": 1080,
                "height": 1920, "pixel_format": "yuva444p12le", "alpha_mode": None,
                "duration_seconds": 4.0, "frame_rate": 30.0,
            }

            def frame(_source: Path, _seconds: float, output: Path) -> None:
                image = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
                if output.name == "midpoint.png":
                    for x in range(460, 620):
                        for y in range(820, 1100):
                            image.putpixel((x, y), (20, 220, 190, 255))
                image.save(output)

            with patch.object(layer_materializer, "_run"), \
                 patch.object(layer_materializer, "_probe_video", return_value=probe), \
                 patch.object(layer_materializer, "_extract_rgba_frame", side_effect=frame):
                video = layer_materializer.materialize_existing_alpha_evidence(
                    overlay=overlay, evidence_dir=evidence_dir, authorized_root=root,
                    expected_width=1080, expected_height=1920,
                    expected_duration=4.0, expected_frame_rate=30.0,
                )
            self.assertEqual(video["alpha_status"], "verified")
            evidence = evidence_dir / "alpha-evidence.json"
            self.assertTrue(evidence.is_file())
            self.assertTrue((evidence_dir / "composite-busy.png").is_file())

    def test_package_publish_retries_transient_windows_directory_lock(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            auth = self._authorities(root)
            clean = root / "clean.mp4"; clean.write_bytes(b"clean")
            captions = root / "master.srt"; captions.write_text("caption", encoding="utf-8")
            package = root / "manual-finish" / "nle-package-v2"
            kwargs = dict(
                package_root=package, authorized_root=root,
                project_path=auth["project.yaml"], source_path=auth["source.mp4"],
                automatic_master=auth["automatic.mp4"], edl_path=auth["edl.json"],
                implementation_sha256=sha256_file(ROOT / "scripts" / "nle_handoff_v2.py"),
                package_level="balanced", frame_rate=25.0, width=1080, height=1920,
                assets={"clean_a_roll": clean, "caption_srt": captions},
            )
            build_nle_handoff_package(**kwargs)
            actual_replace = os.replace
            raised = False

            def transient(source: object, target: object) -> None:
                nonlocal raised
                if Path(source) == package and not raised:
                    raised = True
                    raise PermissionError("transient indexer lock")
                actual_replace(source, target)

            with patch("nle_handoff_v2.os.replace", side_effect=transient):
                build_nle_handoff_package(**kwargs)
            self.assertTrue(raised)
            self.assertEqual(validate_nle_handoff_package(
                package / "10-evidence" / "nle-handoff-package.json"
            ), [])

    def test_packages_verified_event_motion_metadata_and_source_project_archive(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            auth = self._authorities(root)
            clean = root / "clean.mp4"; clean.write_bytes(b"clean")
            captions = root / "master.srt"; captions.write_text("caption", encoding="utf-8")
            overlay = root / "overlay.mov"; overlay.write_bytes(b"alpha-mov")
            archive = root / "hyperframes.zip"; archive.write_bytes(b"source-project")
            alpha_root = root / "alpha-proof"; alpha_root.mkdir()
            midpoint = alpha_root / "midpoint.png"
            post_exit = alpha_root / "post-exit.png"
            middle = Image.new("RGBA", (1080, 1920), (0, 0, 0, 0))
            for x in range(420, 660):
                for y in range(760, 1160):
                    middle.putpixel((x, y), (60, 220, 190, 255))
            middle.save(midpoint)
            Image.new("RGBA", (1080, 1920), (0, 0, 0, 0)).save(post_exit)
            composites = []
            for name, background in layer_materializer._composite_backgrounds(1080, 1920).items():
                image = alpha_root / f"composite-{name}.png"
                background.alpha_composite(middle)
                background.convert("RGB").save(image)
                composites.append({"kind": name, "path": image.name,
                                   "sha256": sha256_file(image)})
            probe = {"codec_name": "prores", "profile": "4444",
                     "width": 1080, "height": 1920,
                     "pixel_format": "yuva444p10le", "frame_rate": 25.0,
                     "duration_seconds": 1.0, "alpha_mode": None}
            evidence_payload = {
                "schema_version": 1, "kind": "nle_motion_alpha_evidence",
                "status": "pass", "video_sha256": sha256_file(overlay),
                "probe": probe,
                "midpoint": {"path": midpoint.name, "sha256": sha256_file(midpoint),
                             "width": 1080, "height": 1920, "minimum_alpha": 0,
                             "maximum_alpha": 255,
                             "visible_ratio": (240 * 400) / (1080 * 1920)},
                "post_exit": {"path": post_exit.name, "sha256": sha256_file(post_exit),
                              "width": 1080, "height": 1920, "minimum_alpha": 0,
                              "maximum_alpha": 0, "visible_ratio": 0.0},
                "composites": composites,
            }
            evidence_payload["integrity_sha256"] = __import__("hashlib").sha256(json.dumps(
                evidence_payload, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            evidence = alpha_root / "alpha-evidence.json"
            evidence.write_text(json.dumps(evidence_payload), encoding="utf-8")
            package = root / "manual-finish" / "nle-package-v2"

            with patch("nle_layer_materializer._probe_video", return_value=probe):
                receipt = build_nle_handoff_package(
                    package_root=package, authorized_root=root,
                    project_path=auth["project.yaml"], source_path=auth["source.mp4"],
                    automatic_master=auth["automatic.mp4"], edl_path=auth["edl.json"],
                    implementation_sha256=sha256_file(ROOT / "scripts" / "nle_handoff_v2.py"),
                    package_level="balanced", frame_rate=25.0, width=1080, height=1920,
                    assets={
                        "clean_a_roll": clean, "caption_srt": captions,
                        "motion_event": [{
                            "path": overlay, "semantic_event_id": "semantic-1",
                            "render_event_id": "event-1",
                            "timeline": {"start_seconds": 0.5, "end_seconds": 1.5,
                                         "frame_rate": 25.0},
                            "video": {"codec_name": "prores", "profile": "4444",
                                      "width": 1080, "height": 1920,
                                      "pixel_format": "yuva444p10le",
                                      "alpha_status": "verified",
                                      "decode_receipt": {"path": str(evidence),
                                                         "sha256": sha256_file(evidence)}},
                        }],
                        "hyperframes_project": archive,
                        "evidence": [evidence],
                    },
                )

            motion = next(row for row in receipt["assets"] if row["role"] == "motion_event")
            source = next(row for row in receipt["assets"] if row["role"] == "hyperframes_project")
            self.assertEqual(motion["video"]["alpha_status"], "verified")
            self.assertEqual(motion["editability_class"], "reference_only")
            self.assertEqual(source["path"], "09-source-project/hyperframes-project.zip")
            with patch("nle_layer_materializer._probe_video", return_value=probe):
                self.assertEqual(validate_nle_handoff_package(
                    package / "10-evidence" / "nle-handoff-package.json"
                ), [])
            packaged_evidence = package / motion["video"]["decode_receipt"]["path"]
            self.assertTrue((packaged_evidence.parent / "midpoint.png").is_file())
            Image.new("RGBA", (1080, 1920), (0, 0, 0, 0)).save(
                packaged_evidence.parent / "midpoint.png"
            )
            with patch("nle_layer_materializer._probe_video", return_value=probe):
                self.assertTrue(any("midpoint" in error or "inventory" in error
                                    for error in validate_nle_handoff_package(
                                        package / "10-evidence" / "nle-handoff-package.json"
                                    )))

    @unittest.skipUnless(os.name == "nt", "NTFS junction regression is Windows-specific")
    def test_package_root_junction_is_rejected_without_external_writes(self) -> None:
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as external:
            root = Path(folder)
            outside = Path(external)
            auth = self._authorities(root)
            clean = root / "clean.mp4"; clean.write_bytes(b"clean")
            captions = root / "master.srt"; captions.write_text("caption", encoding="utf-8")
            package = root / "manual-finish" / "nle-package-v2"
            package.parent.mkdir(parents=True)
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(package), str(outside)],
                capture_output=True, text=True,
            )
            if result.returncode:
                self.skipTest(f"cannot create NTFS junction: {result.stderr or result.stdout}")
            with self.assertRaisesRegex(NleHandoffError, "redirected"):
                build_nle_handoff_package(
                    package_root=package, authorized_root=root,
                    project_path=auth["project.yaml"], source_path=auth["source.mp4"],
                    automatic_master=auth["automatic.mp4"], edl_path=auth["edl.json"],
                    implementation_sha256=sha256_file(ROOT / "scripts" / "nle_handoff_v2.py"), package_level="balanced",
                    frame_rate=25.0, width=1080, height=1920,
                    assets={"clean_a_roll": clean, "caption_srt": captions},
                )
            self.assertEqual(list(outside.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
