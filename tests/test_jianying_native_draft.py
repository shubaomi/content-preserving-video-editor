from __future__ import annotations

import json
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director_contracts import sha256_file  # noqa: E402
from editable_delivery import build_editable_delivery  # noqa: E402
from jianying_native_draft import (  # noqa: E402
    JianyingNativeDraftError,
    build_fixture_compatibility_profile,
    compile_draft_plan,
    discover_jianying_executable,
    materialize_synthetic_fixture,
    validate_adapter_lock,
    validate_compatibility_profile,
    validate_draft_package,
    validate_draft_plan,
)
from nle_handoff_v2 import build_nle_handoff_package  # noqa: E402
import jianying_native_package as native_package_module  # noqa: E402


class JianyingNativeDraftV1Tests(unittest.TestCase):
    def _standard_editable(self, root: Path) -> Path:
        automatic = root / "standard-automatic.mp4"
        candidate = root / "standard-candidate.mp4"
        srt = root / "standard.srt"
        ass = root / "standard.ass"
        style = root / "standard-style.json"
        hyperframes = root / "standard-hyperframes"
        automatic.write_bytes(b"automatic-reference")
        candidate.write_bytes(b"caption-free-candidate")
        srt.write_text("1\n00:00:00,000 --> 00:00:01,000\n字幕\n", encoding="utf-8")
        ass.write_text("[Script Info]\n", encoding="utf-8")
        style.write_text("{}", encoding="utf-8")
        hyperframes.mkdir()
        (hyperframes / "index.html").write_text("<main></main>", encoding="utf-8")
        (hyperframes / "storyboard.json").write_text(
            json.dumps({"events": []}), encoding="utf-8"
        )
        return build_editable_delivery(
            output_root=root / "standard-editable-delivery",
            authorized_root=root,
            automatic_master=automatic,
            caption_free_candidate=candidate,
            caption_srt=srt,
            caption_ass=ass,
            caption_style_plan=style,
            hyperframes_project=hyperframes,
        )

    def test_adapter_and_compatibility_nested_shapes_reject_secret_or_lock_drift(self) -> None:
        compatibility = build_fixture_compatibility_profile()
        compatibility["editor"]["token"] = "must-not-enter-package"
        errors = validate_compatibility_profile(compatibility, allow_fixture=True)
        self.assertTrue(any("shape" in row or "forbidden" in row for row in errors), errors)

        lock = json.loads(
            (ROOT / "references" / "jianying-native-draft-v1" / "adapter-lock.json")
            .read_text(encoding="utf-8")
        )
        lock["distribution"]["index"] = "https://unapproved.invalid/simple"
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "adapter-lock.json"
            path.write_text(json.dumps(lock), encoding="utf-8")
            self.assertTrue(validate_adapter_lock(path))

        compatibility = build_fixture_compatibility_profile()
        compatibility["canary_receipt"] = {"path": "", "sha256": "x"}
        errors = validate_compatibility_profile(compatibility, allow_fixture=True)
        self.assertTrue(any("canary" in row for row in errors), errors)

    def test_editor_discovery_is_read_only_exact_and_root_bounded(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            install_root = root / "program-files"
            executable = install_root / "JianyingPro.exe"
            executable.parent.mkdir(parents=True)
            executable.write_bytes(b"editor-binary")

            with patch(
                "jianying_native_compatibility._windows_file_version",
                return_value="8.2.1.12345",
            ) as version_reader:
                receipt = discover_jianying_executable(
                    executable=executable,
                    authorized_install_roots=[install_root],
                )

            version_reader.assert_called_once_with(executable.resolve())
            self.assertEqual(receipt["status"], "detected_unapproved")
            self.assertEqual(receipt["editor"]["version"], "8.2.1.12345")
            self.assertEqual(
                receipt["editor"]["executable_sha256"], sha256_file(executable)
            )
            self.assertFalse(receipt["editor_launched"])
            self.assertFalse(receipt["draft_store_read"])
            self.assertFalse(receipt["compatibility_claimed"])

            outside = root / "outside" / "JianyingPro.exe"
            outside.parent.mkdir()
            outside.write_bytes(b"outside")
            with self.assertRaisesRegex(JianyingNativeDraftError, "approved install root"):
                discover_jianying_executable(
                    executable=outside,
                    authorized_install_roots=[install_root],
                )

    def _package(self, root: Path, *, optional_visuals: bool = False) -> Path:
        project = root / "project.yaml"
        source = root / "source.mp4"
        automatic = root / "automatic.mp4"
        clean = root / "clean.mp4"
        captions = root / "master.srt"
        caption_ass = root / "master.ass"
        caption_style = root / "caption-style.json"
        sfx = root / "cue.wav"
        project.write_text("schema_version: 13\n", encoding="utf-8")
        source.write_bytes(b"source")
        automatic.write_bytes(b"automatic")
        clean.write_bytes(b"clean")
        captions.write_text(
            "1\n00:00:00,000 --> 00:00:00,800\n第一句\n\n"
            "2\n00:00:01,000 --> 00:00:02,000\n第二句\n",
            encoding="utf-8",
        )
        caption_ass.write_text("[Script Info]\n", encoding="utf-8")
        caption_style.write_text(json.dumps({
            "schema_version": 1,
            "mode": "semantic_emphasis",
            "treatment": {
                "font_family": "Microsoft YaHei UI", "base_color": "#F7F8FA",
                "accent_colors": ["#51E3C2"],
                "max_emphasis_terms_per_caption": 2, "max_scale_percent": 116,
            },
            "captions": [
                {"start": 0.0, "end": 0.8, "text": "第一句", "emphasis": [{
                    "text": "第一", "start_char": 0, "end_char": 2,
                    "color": "#51E3C2", "scale_percent": 116,
                }]},
                {"start": 1.0, "end": 2.0, "text": "第二句", "emphasis": []},
            ],
        }, ensure_ascii=False), encoding="utf-8")
        sfx.write_bytes(b"cue")
        edl = root / "edl.json"
        edl.write_text(json.dumps({
            "owner": "video-use",
            "sources": {"input": str(source)},
            "ranges": [
                {"id": "c1", "source": "input", "start": 0.0, "end": 1.0,
                 "timeline_start": 0.0},
                {"id": "c2", "source": "input", "start": 1.2, "end": 2.2,
                 "timeline_start": 1.0},
            ],
            "gaps": [],
            "transitions": [],
            "metadata": {"video_id": "fixture"},
        }), encoding="utf-8")
        package = root / "work" / "director" / "manual-finish" / "nle-package-v2"
        assets: dict[str, object] = {
            "clean_a_roll": clean,
            "caption_srt": captions,
            "caption_ass_reference": caption_ass,
            "caption_style_plan": caption_style,
            "sfx_event": [{
                "path": sfx,
                "semantic_event_id": "semantic-1",
                "render_event_id": "render-1",
                "timeline": {"start_seconds": 0.5, "end_seconds": 1.0,
                             "frame_rate": 25.0},
                "audio": {"sample_rate": 48000, "duration_seconds": 0.5,
                          "gain_db": -6.0, "channels": 2},
            }],
        }
        if optional_visuals:
            ip = root / "ip.png"
            ip.write_bytes(b"png-fixture")
            outro_copy = root / "copy.json"
            outro_copy.write_text(json.dumps({
                "schema_version": 1,
                "kind": "manual_nle_outro_copy_and_timing",
                "copy": {"headline": "关注 HongRun", "actions": ["点赞", "转发"],
                         "supporting": "一起把想法做出来"},
                "timing": {"duration_seconds": 1.0},
            }, ensure_ascii=False), encoding="utf-8")

            def rights(path: Path, role: str, identity: str) -> Path:
                evidence = root / f"{role}-rights.json"
                evidence.write_text(json.dumps({
                    "schema_version": 1, "kind": "nle_asset_rights",
                    "status": "authorized",
                    "asset": {"path": str(path.resolve()), "sha256": sha256_file(path)},
                    "allowed_roles": [role], "identity_mode": identity,
                    "rights_basis": "authorized synthetic fixture",
                    "redistribution_authorized": True,
                }), encoding="utf-8")
                return evidence

            ip_rights = rights(ip, "ip_rendered", "self")
            copy_rights = rights(outro_copy, "outro_copy", "generic")
            assets["ip_rendered"] = {
                "path": ip, "rights_status": "redistribution_authorized",
                "provenance": "authorized fixture", "rights_evidence": {
                    "path": ip_rights, "sha256": sha256_file(ip_rights),
                },
                "timeline": {"start_seconds": 0.5, "end_seconds": 1.5,
                             "frame_rate": 25.0},
                "semantic_event_id": "semantic-product",
            }
            assets["outro_copy"] = {
                "path": outro_copy, "rights_status": "redistribution_authorized",
                "provenance": "authorized fixture", "rights_evidence": {
                    "path": copy_rights, "sha256": sha256_file(copy_rights),
                },
            }
        build_nle_handoff_package(
            package_root=package,
            authorized_root=root,
            project_path=project,
            source_path=source,
            automatic_master=automatic,
            edl_path=edl,
            implementation_sha256=sha256_file(ROOT / "scripts" / "nle_handoff_v2.py"),
            package_level="balanced",
            frame_rate=25.0,
            width=1080,
            height=1920,
            assets=assets,
        )
        return package / "10-evidence" / "nle-handoff-package.json"

    def test_compiles_frame_exact_layered_plan_from_current_authorities(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            receipt = self._package(root)
            output = root / "work" / "director" / "manual-finish" / \
                "jianying-native-draft-v1" / "plan" / "jianying-draft-plan.json"
            plan = compile_draft_plan(
                nle_package_receipt=receipt,
                output_path=output,
                authorized_root=root,
                draft_id="fixture-draft",
                profile="layered_reconstruction",
                asset_mode="linked",
            )

            self.assertEqual(validate_draft_plan(plan, authorized_root=root), [])
            self.assertEqual(plan["timebase"], {
                "numerator": 25, "denominator": 1, "duration_frames": 50,
            })
            base = next(row for row in plan["tracks"] if row["track_id"] == "video.base")
            self.assertEqual(
                [(clip["start_frame"], clip["duration_frames"]) for clip in base["clips"]],
                [(0, 25), (25, 25)],
            )
            self.assertEqual(
                [clip["clip_id"] for clip in base["clips"]], ["base.c1", "base.c2"]
            )
            captions = next(
                row for row in plan["tracks"] if row["track_id"] == "text.captions"
            )
            self.assertEqual([clip["payload"]["text"] for clip in captions["clips"]],
                             ["第一句", "第二句"])
            self.assertIsNotNone(captions["clips"][0]["payload"]["ass_reference"])
            self.assertEqual(captions["clips"][0]["payload"]["emphasis"], [{
                "start_utf16": 0, "end_utf16": 2, "bold": True,
                "scale": 1.16, "color": "#51E3C2",
            }])
            sfx = next(row for row in plan["tracks"] if row["track_id"] == "audio.sfx.render-1")
            self.assertEqual(sfx["clips"][0]["start_frame"], 13)
            self.assertEqual(sfx["clips"][0]["payload"]["gain_db"], -6.0)
            self.assertEqual(plan["plan_sha256"], json.loads(
                output.read_text(encoding="utf-8")
            )["plan_sha256"])

    def test_compiles_rights_bound_ip_and_native_outro_copy_tracks(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            receipt = self._package(root, optional_visuals=True)
            plan = compile_draft_plan(
                nle_package_receipt=receipt,
                output_path=root / "plan.json",
                authorized_root=root,
                draft_id="optional-layers",
                profile="layered_reconstruction",
                asset_mode="linked",
            )

            ip = next(row for row in plan["tracks"] if row["track_id"].startswith("video.ip."))
            self.assertEqual(ip["clips"][0]["payload"]["type"], "ip")
            self.assertEqual(ip["clips"][0]["start_frame"], 13)
            copy = next(row for row in plan["tracks"] if row["track_id"] == "text.outro.0")
            self.assertIn("关注 HongRun", copy["clips"][0]["payload"]["native_text"])
            self.assertEqual(copy["clips"][0]["start_frame"], 25)
            self.assertEqual(validate_draft_plan(plan, authorized_root=root), [])

    def test_repair_profile_is_caption_only_and_portable_plan_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            receipt = self._package(root, optional_visuals=True)
            candidate = root / "repair-candidate.mp4"
            candidate.write_bytes(b"caption-free-baked-candidate")
            repair = compile_draft_plan(
                nle_package_receipt=receipt,
                output_path=root / "repair-plan.json",
                authorized_root=root,
                draft_id="repair",
                profile="repair_draft",
                asset_mode="linked",
                repair_candidate=candidate,
            )
            self.assertEqual(
                [track["track_id"] for track in repair["tracks"]],
                ["video.base", "text.captions", "reference.master"],
            )
            self.assertEqual(repair["tracks"][0]["clips"][0]["fidelity"], "baked")
            self.assertEqual(validate_draft_plan(repair, authorized_root=root), [])

            portable = compile_draft_plan(
                nle_package_receipt=receipt,
                output_path=root / "portable-plan.json",
                authorized_root=root,
                draft_id="portable",
                profile="layered_reconstruction",
                asset_mode="portable",
            )
            self.assertEqual(portable["asset_mode"], "portable")
            self.assertEqual(validate_draft_plan(portable, authorized_root=root), [])

    def test_paired_motion_and_sfx_may_share_one_event_binding(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan = compile_draft_plan(
                nle_package_receipt=self._package(root),
                output_path=root / "plan.json",
                authorized_root=root,
                draft_id="paired-event",
                profile="layered_reconstruction",
                asset_mode="linked",
            )
            sfx = next(
                track for track in plan["tracks"]
                if track["track_id"].startswith("audio.sfx.")
            )["clips"][0]
            motion = {
                **sfx,
                "clip_id": "motion.render-1",
                "role": "motion",
                "payload": {
                    "type": "video", "alpha_mode": "none",
                    "transform": {
                        "x": 0.0, "y": 0.0, "scale_x": 1.0, "scale_y": 1.0,
                        "rotation_degrees": 0.0, "opacity": 1.0,
                    },
                    "motion_editability": "native_clip",
                },
            }
            plan["tracks"].insert(1, {
                "track_id": "video.motion.render-1", "order": 10,
                "kind": "video", "clips": [motion],
            })
            plan["plan_sha256"] = hashlib.sha256(json.dumps(
                {key: value for key, value in plan.items() if key != "plan_sha256"},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            self.assertEqual(validate_draft_plan(plan, authorized_root=root), [])

    def test_plan_validation_rejects_hash_drift_role_mismatch_and_invalid_numbers(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            receipt = self._package(root)
            plan = compile_draft_plan(
                nle_package_receipt=receipt,
                output_path=root / "plan.json",
                authorized_root=root,
                draft_id="fixture",
                profile="layered_reconstruction",
                asset_mode="linked",
            )
            caption = next(row for row in plan["tracks"] if row["track_id"] == "text.captions")
            caption["clips"][0]["duration_frames"] = 0
            caption["clips"][0]["payload"]["type"] = "audio"
            source = Path(next(
                row for row in plan["authorities"].values()
                if Path(row["path"]).name == "master.srt"
            )["path"])
            source.write_text("drift", encoding="utf-8")
            errors = validate_draft_plan(plan, authorized_root=root)
            self.assertTrue(any("duration_frames" in row for row in errors))
            self.assertTrue(any("payload type" in row for row in errors))
            self.assertTrue(any("stale" in row for row in errors))

    def test_plan_validation_enforces_frozen_nested_machine_contract(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan = compile_draft_plan(
                nle_package_receipt=self._package(root),
                output_path=root / "plan.json",
                authorized_root=root,
                draft_id="contract",
                profile="layered_reconstruction",
                asset_mode="linked",
            )
            plan["draft_id"] = "../../bad"
            plan["authorities"]["edl"]["extra"] = "E:/private/path"
            base = next(row for row in plan["tracks"] if row["track_id"] == "video.base")
            base["clips"][0]["editable"] = "yes"
            base["clips"][0]["fidelity"] = "invented"
            base["clips"][0]["payload"]["alpha_mode"] = "guessed"
            caption = next(
                row for row in plan["tracks"] if row["track_id"] == "text.captions"
            )["clips"][0]
            caption["payload"]["emphasis"][0]["end_utf16"] = 999
            sfx = next(
                row for row in plan["tracks"] if row["track_id"].startswith("audio.sfx.")
            )["clips"][0]
            sfx["payload"]["gain_db"] = 25.0
            plan["plan_sha256"] = __import__("hashlib").sha256(json.dumps(
                {key: value for key, value in plan.items() if key != "plan_sha256"},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()

            errors = validate_draft_plan(plan, authorized_root=root)
            for expected in (
                "plan ID", "file reference shape", "editable", "fidelity", "payload enum",
                "emphasis span", "audio clip",
            ):
                self.assertTrue(any(expected in row for row in errors), (expected, errors))

    def test_compile_rejects_transitive_external_authority_before_upstream_validation(self) -> None:
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside:
            root = Path(folder)
            receipt_path = self._package(root)
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            external_source = Path(outside) / "source.mp4"
            authority = Path(receipt["authorities"]["source"]["path"])
            external_source.write_bytes(authority.read_bytes())
            receipt["authorities"]["source"] = {
                "path": str(external_source.resolve()),
                "sha256": sha256_file(external_source),
            }
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            with patch(
                "jianying_native_plan_compile.validate_nle_handoff_package"
            ) as validator:
                with self.assertRaisesRegex(JianyingNativeDraftError, "authorized root"):
                    compile_draft_plan(
                        nle_package_receipt=receipt_path,
                        output_path=root / "plan.json",
                        authorized_root=root,
                        draft_id="external",
                        profile="layered_reconstruction",
                        asset_mode="linked",
                    )
            validator.assert_not_called()

    def test_package_validator_rejects_transitive_external_nle_authority_first(self) -> None:
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside:
            root = Path(folder)
            receipt_path = self._package(root)
            plan_path = root / "native" / "plan" / "plan.json"
            compile_draft_plan(
                nle_package_receipt=receipt_path,
                output_path=plan_path,
                authorized_root=root,
                draft_id="transitive-outside",
                profile="layered_reconstruction",
                asset_mode="linked",
            )
            compatibility_path = root / "compatibility.json"
            compatibility_path.write_text(
                json.dumps(build_fixture_compatibility_profile()), encoding="utf-8"
            )
            output_root = root / "native"
            materialize_synthetic_fixture(
                plan_path=plan_path,
                compatibility_profile_path=compatibility_path,
                output_root=output_root,
                authorized_root=root,
                build_id="transitive-outside",
                standard_editable_delivery=self._standard_editable(root),
            )

            external_source = Path(outside) / "source.mp4"
            receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
            external_source.write_bytes(
                Path(receipt["authorities"]["source"]["path"]).read_bytes()
            )
            receipt["authorities"]["source"] = {
                "path": str(external_source.resolve()),
                "sha256": sha256_file(external_source),
            }
            receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
            receipt_hash = sha256_file(receipt_path)

            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["authorities"]["nle_package"]["sha256"] = receipt_hash
            plan["plan_sha256"] = hashlib.sha256(json.dumps(
                {key: value for key, value in plan.items() if key != "plan_sha256"},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            plan_path.write_text(json.dumps(plan), encoding="utf-8")

            manifest_path = output_root / "published" / "transitive-outside" / \
                "draft-package-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["plan"]["sha256"] = sha256_file(plan_path)
            manifest["fallbacks"]["nle_package"]["sha256"] = receipt_hash
            manifest["integrity_sha256"] = hashlib.sha256(json.dumps(
                {key: value for key, value in manifest.items()
                 if key != "integrity_sha256"},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            with patch("jianying_native_package.validate_nle_handoff_package") as validator:
                errors = validate_draft_package(manifest_path, authorized_root=root)
            self.assertTrue(any("authorized root" in row for row in errors), errors)
            validator.assert_not_called()

    def test_synthetic_fixture_is_isolated_deterministic_and_self_identifies(self) -> None:
        canonical_hashes: list[str] = []
        for index in range(2):
            with tempfile.TemporaryDirectory() as folder:
                root = Path(folder)
                receipt = self._package(root)
                plan_path = root / "work" / "director" / "manual-finish" / \
                    "jianying-native-draft-v1" / "plan" / "jianying-draft-plan.json"
                compile_draft_plan(
                    nle_package_receipt=receipt,
                    output_path=plan_path,
                    authorized_root=root,
                    draft_id="fixture-draft",
                    profile="layered_reconstruction",
                    asset_mode="linked",
                )
                compatibility_path = root / "compatibility.json"
                compatibility = build_fixture_compatibility_profile()
                compatibility_path.write_text(
                    json.dumps(compatibility, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8",
                )
                standard_editable = self._standard_editable(root)
                output_root = root / "work" / "director" / "manual-finish" / \
                    "jianying-native-draft-v1"
                manifest = materialize_synthetic_fixture(
                    plan_path=plan_path,
                    compatibility_profile_path=compatibility_path,
                    output_root=output_root,
                    authorized_root=root,
                    build_id="fixture-build",
                    standard_editable_delivery=standard_editable,
                )
                published = output_root / "published" / "fixture-build"
                manifest_path = published / "draft-package-manifest.json"
                self.assertEqual(validate_draft_package(manifest_path, authorized_root=root), [])
                native = json.loads(
                    (published / "native-draft" / "draft_content.json").read_text(
                        encoding="utf-8"
                    )
                )
                self.assertTrue(native["synthetic_fixture_only"])
                self.assertFalse(native["real_jianying_compatibility_claimed"])
                self.assertNotIn(str(root), json.dumps(native, ensure_ascii=False))
                native_base = next(
                    track for track in native["tracks"] if track["track_id"] == "video.base"
                )
                self.assertEqual(
                    [clip["source_start_frame"] for clip in native_base["clips"]],
                    [0, 25],
                )
                self.assertFalse(manifest["safety"]["existing_draft_read"])
                self.assertFalse(manifest["safety"]["existing_draft_modified"])
                adapter_report = json.loads(
                    (published / manifest["adapter_report"]["path"]).read_text(
                        encoding="utf-8"
                    )
                )
                self.assertTrue(adapter_report["synthetic_fixture_only"])
                canonical_hashes.append(adapter_report["canonical_output_sha256"])

                (published / "extra.txt").write_text("unexpected", encoding="utf-8")
                self.assertTrue(any(
                    "inventory" in row
                    for row in validate_draft_package(manifest_path, authorized_root=root)
                ))
                tampered = json.loads(manifest_path.read_text(encoding="utf-8"))
                tampered["output_root"] = str(root / "wrong-output")
                tampered["integrity_sha256"] = __import__("hashlib").sha256(json.dumps(
                    {key: value for key, value in tampered.items()
                     if key != "integrity_sha256"},
                    ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")).hexdigest()
                manifest_path.write_text(json.dumps(tampered), encoding="utf-8")
                self.assertTrue(any(
                    "output root" in row
                    for row in validate_draft_package(manifest_path, authorized_root=root)
                ))
        self.assertEqual(canonical_hashes[0], canonical_hashes[1])

    def test_materializer_refuses_existing_build_and_outside_root(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            receipt = self._package(root)
            plan_path = root / "plan.json"
            compile_draft_plan(
                nle_package_receipt=receipt,
                output_path=plan_path,
                authorized_root=root,
                draft_id="fixture",
                profile="layered_reconstruction",
                asset_mode="linked",
            )
            compatibility_path = root / "compatibility.json"
            compatibility_path.write_text(
                json.dumps(build_fixture_compatibility_profile()), encoding="utf-8"
            )
            standard_editable = self._standard_editable(root)
            output_root = root / "native"
            materialize_synthetic_fixture(
                plan_path=plan_path,
                compatibility_profile_path=compatibility_path,
                output_root=output_root,
                authorized_root=root,
                build_id="same",
                standard_editable_delivery=standard_editable,
            )
            with self.assertRaisesRegex(JianyingNativeDraftError, "already exists"):
                materialize_synthetic_fixture(
                    plan_path=plan_path,
                    compatibility_profile_path=compatibility_path,
                    output_root=output_root,
                    authorized_root=root,
                    build_id="same",
                    standard_editable_delivery=standard_editable,
                )

    def test_package_reparse_rejects_all_json_secrets_urls_and_invalid_source_plan(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            receipt = self._package(root)
            plan_path = root / "native" / "plan" / "plan.json"
            compile_draft_plan(
                nle_package_receipt=receipt,
                output_path=plan_path,
                authorized_root=root,
                draft_id="privacy",
                profile="layered_reconstruction",
                asset_mode="linked",
            )
            compatibility_path = root / "compatibility.json"
            compatibility_path.write_text(
                json.dumps(build_fixture_compatibility_profile()), encoding="utf-8"
            )
            output_root = root / "native"
            materialize_synthetic_fixture(
                plan_path=plan_path,
                compatibility_profile_path=compatibility_path,
                output_root=output_root,
                authorized_root=root,
                build_id="privacy",
                standard_editable_delivery=self._standard_editable(root),
            )
            published = output_root / "published" / "privacy"
            manifest_path = published / "draft-package-manifest.json"

            def refresh(path: Path) -> None:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                relative = str(path.relative_to(published)).replace("\\", "/")
                for ref in manifest["inventory"]:
                    if ref["path"] == relative:
                        ref["sha256"] = sha256_file(path)
                if relative == manifest["adapter_report"]["path"]:
                    manifest["adapter_report"]["sha256"] = sha256_file(path)
                manifest["integrity_sha256"] = hashlib.sha256(json.dumps(
                    {key: value for key, value in manifest.items()
                     if key != "integrity_sha256"},
                    ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")).hexdigest()
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            adapter = published / "adapter-report.json"
            adapter_payload = json.loads(adapter.read_text(encoding="utf-8"))
            adapter_payload["token"] = "must-not-ship"
            adapter.write_text(json.dumps(adapter_payload), encoding="utf-8")
            refresh(adapter)
            errors = validate_draft_package(manifest_path, authorized_root=root)
            self.assertTrue(any("forbidden metadata" in row for row in errors), errors)
            self.assertTrue(any("boundary" in row for row in errors), errors)

            adapter_payload.pop("token")
            adapter.write_text(json.dumps(adapter_payload), encoding="utf-8")
            refresh(adapter)
            adapter_plan = published / "adapter-plan.json"
            adapter_plan_payload = json.loads(adapter_plan.read_text(encoding="utf-8"))
            adapter_plan_payload["documentation"] = "https://unapproved.invalid/path"
            adapter_plan.write_text(json.dumps(adapter_plan_payload), encoding="utf-8")
            refresh(adapter_plan)
            errors = validate_draft_package(manifest_path, authorized_root=root)
            self.assertTrue(any("forbidden URL" in row for row in errors), errors)

            adapter_plan_payload.pop("documentation")
            adapter_plan.write_text(json.dumps(adapter_plan_payload), encoding="utf-8")
            refresh(adapter_plan)
            native_content = published / "native-draft" / "draft_content.json"
            native_payload = json.loads(native_content.read_text(encoding="utf-8"))
            native_payload["tracks"][0]["clips"][0]["source_start_frame"] = 99999
            native_content.write_text(json.dumps(native_payload), encoding="utf-8")
            refresh(native_content)
            native_inventory = [{
                "path": str(path.relative_to(published / "native-draft")).replace("\\", "/"),
                "sha256": sha256_file(path),
            } for path in sorted((published / "native-draft").rglob("*")) if path.is_file()]
            adapter_payload["canonical_output_sha256"] = hashlib.sha256(json.dumps(
                native_inventory, ensure_ascii=False, sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            adapter.write_text(json.dumps(adapter_payload), encoding="utf-8")
            refresh(adapter)
            errors = validate_draft_package(manifest_path, authorized_root=root)
            self.assertTrue(any("projected plan differs" in row for row in errors), errors)

            fake = root / "fake-editable.txt"
            fake.write_text("not an editable delivery", encoding="utf-8")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["fallbacks"]["standard_editable_delivery"] = {
                "path": "../../../fake-editable.txt", "sha256": sha256_file(fake),
            }
            manifest["integrity_sha256"] = hashlib.sha256(json.dumps(
                {key: value for key, value in manifest.items()
                 if key != "integrity_sha256"},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            errors = validate_draft_package(manifest_path, authorized_root=root)
            self.assertTrue(any("editable" in row.lower() for row in errors), errors)

            plan_path.write_text('{"not":"a draft plan"}', encoding="utf-8")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["plan"]["sha256"] = sha256_file(plan_path)
            manifest["integrity_sha256"] = hashlib.sha256(json.dumps(
                {key: value for key, value in manifest.items()
                 if key != "integrity_sha256"},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            errors = validate_draft_package(manifest_path, authorized_root=root)
            self.assertTrue(any("source plan" in row or "draft plan" in row for row in errors), errors)

    def test_materializer_enforces_package_size_budget(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan_path = root / "plan.json"
            compile_draft_plan(
                nle_package_receipt=self._package(root),
                output_path=plan_path,
                authorized_root=root,
                draft_id="budget",
                profile="layered_reconstruction",
                asset_mode="portable",
            )
            compatibility_path = root / "compatibility.json"
            compatibility_path.write_text(
                json.dumps(build_fixture_compatibility_profile()), encoding="utf-8"
            )
            output_root = root / "native"
            with self.assertRaisesRegex(JianyingNativeDraftError, "size budget"):
                materialize_synthetic_fixture(
                    plan_path=plan_path,
                    compatibility_profile_path=compatibility_path,
                    output_root=output_root,
                    authorized_root=root,
                    build_id="too-small",
                    standard_editable_delivery=self._standard_editable(root),
                    max_package_gib=0.000000001,
                )
            self.assertFalse((output_root / "published" / "too-small").exists())
            staging_root = output_root / "staging"
            self.assertEqual(
                list(staging_root.iterdir()) if staging_root.is_dir() else [], []
            )

    def test_package_validator_never_reads_an_outside_reference(self) -> None:
        with tempfile.TemporaryDirectory() as folder, tempfile.TemporaryDirectory() as outside:
            root = Path(folder)
            plan_path = root / "native" / "plan" / "plan.json"
            compile_draft_plan(
                nle_package_receipt=self._package(root),
                output_path=plan_path,
                authorized_root=root,
                draft_id="outside-ref",
                profile="layered_reconstruction",
                asset_mode="linked",
            )
            compatibility_path = root / "compatibility.json"
            compatibility_path.write_text(
                json.dumps(build_fixture_compatibility_profile()), encoding="utf-8"
            )
            output_root = root / "native"
            materialize_synthetic_fixture(
                plan_path=plan_path,
                compatibility_profile_path=compatibility_path,
                output_root=output_root,
                authorized_root=root,
                build_id="outside-ref",
                standard_editable_delivery=self._standard_editable(root),
            )
            manifest_path = output_root / "published" / "outside-ref" / \
                "draft-package-manifest.json"
            external = Path(outside) / "outside-plan.json"
            external.write_text('{"schema_version":1,"tracks":[1]}', encoding="utf-8")
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            manifest["plan"] = {"path": str(external), "sha256": sha256_file(external)}
            manifest["integrity_sha256"] = hashlib.sha256(json.dumps(
                {key: value for key, value in manifest.items()
                 if key != "integrity_sha256"},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

            original_read_json = native_package_module.read_json

            def guarded_read_json(path: Path):
                if Path(path).resolve() == external.resolve():
                    raise AssertionError("outside authority was read")
                return original_read_json(path)

            with patch("jianying_native_package.read_json", side_effect=guarded_read_json):
                errors = validate_draft_package(manifest_path, authorized_root=root)
            self.assertTrue(any("authorized root" in row for row in errors), errors)

    def test_materializer_refuses_tree_redirection_before_atomic_publish(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            receipt = self._package(root)
            plan_path = root / "plan.json"
            compile_draft_plan(
                nle_package_receipt=receipt,
                output_path=plan_path,
                authorized_root=root,
                draft_id="redirected",
                profile="layered_reconstruction",
                asset_mode="linked",
            )
            compatibility_path = root / "compatibility.json"
            compatibility_path.write_text(
                json.dumps(build_fixture_compatibility_profile()), encoding="utf-8"
            )
            standard_editable = self._standard_editable(root)
            output_root = root / "native"
            with patch(
                "jianying_native_package._assert_generated_tree_safe",
                side_effect=[None, JianyingNativeDraftError("redirected generated tree")],
            ):
                with self.assertRaisesRegex(JianyingNativeDraftError, "redirected"):
                    materialize_synthetic_fixture(
                        plan_path=plan_path,
                        compatibility_profile_path=compatibility_path,
                        output_root=output_root,
                        authorized_root=root,
                        build_id="redirected",
                        standard_editable_delivery=standard_editable,
                    )
            self.assertFalse((output_root / "published" / "redirected").exists())
            with self.assertRaisesRegex(JianyingNativeDraftError, "authorized root"):
                materialize_synthetic_fixture(
                    plan_path=plan_path,
                    compatibility_profile_path=compatibility_path,
                    output_root=root.parent / "outside-native",
                    authorized_root=root,
                    build_id="outside",
                    standard_editable_delivery=standard_editable,
                )


if __name__ == "__main__":
    unittest.main()
