from __future__ import annotations

import inspect
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch


ROOT = Path(__file__).parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from director_contracts import sha256_file  # noqa: E402
from editable_delivery import build_editable_delivery  # noqa: E402
from jianying_native_real import (  # noqa: E402
    JianyingNativeDraftError,
    _adapter_request,
    bind_project_local_candidate,
    materialize_project_local_candidate,
    validate_project_local_candidate,
)
from jianying_native_plan import validate_draft_plan  # noqa: E402
from jianying_native_adapter_runner import (  # noqa: E402
    _add_segment_with_exact_touching_boundary,
    _locked_authorized_bytes, _locked_authorized_hash,
    execute as execute_adapter_request,
)
from jianying_native_adapter_lock import ADAPTER_RUNTIME_LOCK  # noqa: E402


class JianyingProjectLocalCandidateTests(unittest.TestCase):
    TEST_RUNTIME_LOCK = {
        "python_executable_sha256": hashlib.sha256(b"python").hexdigest(),
        "pyvenv_cfg_sha256": hashlib.sha256(b"home = test\r\n").hexdigest(),
        "python_version": "test", "machine": "test", "pointer_bits": 64,
    }

    @classmethod
    def setUpClass(cls) -> None:
        cls._runtime_lock_patch = patch(
            "jianying_native_real.ADAPTER_RUNTIME_LOCK", cls.TEST_RUNTIME_LOCK
        )
        cls._runtime_lock_patch.start()
        cls._dependency_lock_patch = patch(
            "jianying_native_real.ADAPTER_DEPENDENCY_LOCK", {}
        )
        cls._dependency_lock_patch.start()

    @classmethod
    def tearDownClass(cls) -> None:
        cls._dependency_lock_patch.stop()
        cls._runtime_lock_patch.stop()

    def test_pinned_adapter_touching_boundary_workaround_preserves_exact_times(self) -> None:
        class FakeRange:
            def __init__(self, start: int, duration: int) -> None:
                self.start = start
                self.duration = duration

            @property
            def end(self) -> int:
                return self.start + self.duration

        class FakeScript:
            def __init__(self) -> None:
                self.track = SimpleNamespace(segments=[])

            def _resolve_track_ref(self, _track_ref):
                return self.track

            def add_segment(self, segment, _track_ref) -> None:
                for existing in self.track.segments:
                    if not (
                        existing.target_timerange.end < segment.target_timerange.start
                        or segment.target_timerange.end < existing.target_timerange.start
                    ):
                        raise ValueError("inclusive overlap")
                self.track.segments.append(segment)

        script = FakeScript()
        first = SimpleNamespace(
            target_timerange=FakeRange(0, 100),
        )
        script.track.segments.append(first)
        second_range = FakeRange(100, 50)
        second = SimpleNamespace(target_timerange=second_range)

        _add_segment_with_exact_touching_boundary(script, second, object())

        self.assertEqual(first.target_timerange.duration, 100)
        self.assertEqual(script.track.segments, [first, second])

        overlapping = SimpleNamespace(
            target_timerange=FakeRange(99, 10),
        )
        with self.assertRaisesRegex(ValueError, "inclusive overlap"):
            _add_segment_with_exact_touching_boundary(script, overlapping, object())

    def test_adapter_request_uses_frame_endpoints_at_fractional_microseconds(self) -> None:
        root = Path("C:/authorized")
        context = {
            "plan": {
                "plan_sha256": "0" * 64,
                "draft_id": "fractional-boundary",
                "timebase": {"numerator": 30, "denominator": 1},
                "tracks": [{
                    "track_id": "text.captions", "order": 200, "kind": "text",
                    "clips": [
                        {"clip_id": "caption.1", "role": "caption",
                         "start_frame": 1097, "source_start_frame": 0,
                         "duration_frames": 53, "source": {"path": "a", "sha256": "a"},
                         "payload": {"text": "前句"}},
                        {"clip_id": "caption.2", "role": "caption",
                         "start_frame": 1150, "source_start_frame": 0,
                         "duration_frames": 48, "source": {"path": "b", "sha256": "b"},
                         "payload": {"text": "后句"}},
                    ],
                }],
            },
            "fps": 30, "canvas": {"width": 960, "height": 624},
            "adapter_wheel": root / "adapter.whl", "adapter_dependencies": [],
            "adapter_runtime_lock": {}, "adapter_lock_sha256": "1" * 64,
            "adapter_locked_io_sha256": "2" * 64,
            "adapter_python": root / "python.exe", "adapter_runner_sha256": "3" * 64,
            "authorized_root": root,
        }
        with patch("jianying_native_real.sha256_file", return_value="4" * 64):
            clips = _adapter_request(
                context, staging=root / "staging"
            )["tracks"][0]["clips"]
        self.assertEqual(
            clips[0]["target_start_us"] + clips[0]["target_duration_us"],
            clips[1]["target_start_us"],
        )

    @staticmethod
    def _refresh_candidate_manifest(manifest_path: Path) -> None:
        package_root = manifest_path.parent
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["inventory"] = [{
            "path": str(path.relative_to(package_root)).replace("\\", "/"),
            "sha256": sha256_file(path),
            "size_bytes": path.stat().st_size,
        } for path in sorted(package_root.rglob("*"))
          if path.is_file() and path != manifest_path]
        import hashlib
        manifest["integrity_sha256"] = hashlib.sha256(json.dumps(
            {key: value for key, value in manifest.items() if key != "integrity_sha256"},
            ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        ).encode("utf-8")).hexdigest()
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    def _authorities(self, root: Path) -> tuple[Path, Path, Path]:
        media = root / "media.mp4"
        audio = root / "cue.wav"
        master = root / "automatic.mp4"
        for path, value in ((media, b"video"), (audio, b"audio"), (master, b"master")):
            path.write_bytes(value)
        nle = root / "nle-receipt.json"
        nle.write_text("{}", encoding="utf-8")
        edl = root / "edl.json"
        edl.write_text(json.dumps({
            "ranges": [{"id": "c1", "start": 10.0, "end": 12.0,
                        "timeline_start": 0.0}],
        }), encoding="utf-8")
        srt = root / "master.srt"
        srt.write_text(
            "1\n00:00:00,000 --> 00:00:01,000\n可编辑字幕\n",
            encoding="utf-8",
        )
        timeline = root / "layer-timeline.json"
        timeline.write_text(json.dumps({
            "schema_version": 2, "authority": "video-use-output-timeline",
            "origin_seconds": 0, "duration_seconds": 2.0, "frame_rate": 25.0,
            "canvas": {"width": 1080, "height": 1920}, "tracks": [], "markers": [],
        }), encoding="utf-8")
        candidate = root / "caption-free-candidate.mp4"
        candidate.write_bytes(b"candidate")
        ass = root / "master.ass"
        ass.write_text("[Script Info]\n", encoding="utf-8")
        style = root / "caption-style.json"
        style.write_text("{}", encoding="utf-8")
        hyperframes = root / "hyperframes"
        hyperframes.mkdir()
        (hyperframes / "index.html").write_text("<main></main>", encoding="utf-8")
        (hyperframes / "storyboard.json").write_text('{"events": []}', encoding="utf-8")
        editable = build_editable_delivery(
            output_root=root / "editable-delivery", authorized_root=root,
            automatic_master=master, caption_free_candidate=candidate,
            caption_srt=srt, caption_ass=ass, caption_style_plan=style,
            hyperframes_project=hyperframes,
        )
        plan = {
            "schema_version": 1,
            "kind": "jianying_native_draft_plan",
            "draft_id": "project-local-test",
            "profile": "layered_reconstruction",
            "asset_mode": "linked",
            "authorities": {
                "edl": {"path": str(edl), "sha256": sha256_file(edl)},
                "layer_timeline": {"path": str(timeline), "sha256": sha256_file(timeline)},
                "master_srt": {"path": str(srt), "sha256": sha256_file(srt)},
                "automatic_master": {"path": str(master), "sha256": sha256_file(master)},
                "nle_package": {"path": str(nle), "sha256": sha256_file(nle)},
            },
            "timebase": {"numerator": 25, "denominator": 1, "duration_frames": 50},
            "tracks": [
                {"track_id": "video.base", "order": 0, "kind": "video", "clips": [{
                    "clip_id": "base.c1", "role": "base", "semantic_event_id": None,
                    "render_event_id": None, "start_frame": 0,
                    "source_start_frame": 0, "duration_frames": 50,
                    "source": {"path": str(media), "sha256": sha256_file(media)},
                    "editable": True, "fidelity": "full", "payload": {
                        "type": "video", "alpha_mode": "none",
                        "transform": {"x": 0.0, "y": 0.0, "scale_x": 1.0,
                                      "scale_y": 1.0, "rotation_degrees": 0.0,
                                      "opacity": 1.0},
                        "motion_editability": "native_clip",
                    },
                }]},
                {"track_id": "text.captions", "order": 200, "kind": "text", "clips": [{
                    "clip_id": "caption.00001", "role": "caption",
                    "semantic_event_id": None, "render_event_id": None,
                    "start_frame": 0, "source_start_frame": 0,
                    "duration_frames": 25,
                    "source": {"path": str(srt), "sha256": sha256_file(srt)},
                    "editable": True, "fidelity": "degraded", "payload": {
                        "type": "caption", "cue_id": "1", "text": "可编辑字幕",
                        "base_style": {}, "emphasis": [], "fidelity": "degraded",
                        "ass_reference": None,
                    },
                }]},
                {"track_id": "audio.sfx.demo", "order": 320, "kind": "audio", "clips": [{
                    "clip_id": "sfx.demo", "role": "sfx", "semantic_event_id": "s1",
                    "render_event_id": "demo", "start_frame": 25,
                    "source_start_frame": 0, "duration_frames": 12,
                    "source": {"path": str(audio), "sha256": sha256_file(audio)},
                    "editable": True, "fidelity": "full", "payload": {
                        "type": "audio", "sample_rate_hz": 48000, "channels": 2,
                        "gain_db": -6.0,
                    },
                }]},
                {"track_id": "reference.master", "order": 900, "kind": "reference", "clips": [{
                    "clip_id": "reference.automatic-master", "role": "reference",
                    "semantic_event_id": None, "render_event_id": None,
                    "start_frame": 0, "source_start_frame": 0,
                    "duration_frames": 50,
                    "source": {"path": str(master), "sha256": sha256_file(master)},
                    "editable": False, "fidelity": "full",
                    "payload": {"type": "reference", "enabled": False, "locked": True},
                }]},
            ],
        }
        import hashlib
        plan["plan_sha256"] = hashlib.sha256(json.dumps(
            plan, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode("utf-8")).hexdigest()
        plan_path = root / "jianying-draft-plan.json"
        plan_path.write_text(json.dumps(plan, ensure_ascii=False), encoding="utf-8")
        return plan_path, editable, nle

    @staticmethod
    def _fake_adapter(completed_request: list[dict[str, object]]):
        def run(argv, **kwargs):
            request_path = Path(argv[argv.index("--request") + 1])
            request = json.loads(request_path.read_text(encoding="utf-8"))
            completed_request.append(request)
            native = Path(request["native_draft_root"])
            native.mkdir()
            tracks = []
            rows = []
            material_videos = []
            material_audios = []
            material_texts = []
            for track in request["tracks"]:
                native_segments = []
                for clip in track["clips"]:
                    segment_id = "native-" + clip["clip_id"]
                    segment = {
                        "id": segment_id,
                        "material_id": "material-" + clip["clip_id"],
                        "target_timerange": {
                            "start": clip["target_start_us"],
                            "duration": clip["target_duration_us"],
                        },
                    }
                    if track["kind"] in {"video", "audio"}:
                        segment["source_timerange"] = {
                            "start": clip["source_start_us"],
                            "duration": clip["source_duration_us"],
                        }
                        material = {
                            "id": segment["material_id"], "path": clip["source_path"]
                        }
                        if track["kind"] == "video":
                            transform = clip["payload"].get("transform") or {}
                            segment["clip"] = {
                                "alpha": float(transform.get("opacity", 1.0)),
                                "rotation": float(transform.get("rotation_degrees", 0.0)),
                                "scale": {
                                    "x": float(transform.get("scale_x", 1.0)),
                                    "y": float(transform.get("scale_y", 1.0)),
                                },
                                "transform": {
                                    "x": float(transform.get("x", 0.0)),
                                    "y": float(transform.get("y", 0.0)),
                                },
                            }
                            material_videos.append(material)
                        else:
                            segment["volume"] = 10 ** (
                                float(clip["payload"].get("gain_db", 0.0)) / 20
                            )
                            material_audios.append(material)
                    else:
                        base = clip["payload"].get("base_style") or {}
                        color = base.get("base_color") or base.get("color") or "#FFFFFF"
                        rgb = [int(color[index:index + 2], 16) / 255 for index in (1, 3, 5)]
                        material_texts.append({
                            "id": segment["material_id"],
                            "content": json.dumps({
                                "text": clip["text"],
                                "styles": [{
                                    "size": float(base.get("font_size") or base.get("font_size_px") or base.get("size") or 8.0),
                                    "bold": bool(base.get("bold", False)),
                                    "fill": {"content": {"solid": {"color": rgb}}},
                                }],
                            }, ensure_ascii=False),
                        })
                    native_segments.append(segment)
                    rows.append({
                        "clip_id": clip["clip_id"], "track_id": track["track_id"],
                        "segment_id": segment_id, "status": "projected",
                    })
                tracks.append({"name": track["track_id"], "type": track["kind"],
                               "segments": native_segments})
            (native / "draft_content.json").write_text(json.dumps({
                "canvas_config": request["canvas"], "fps": request["fps"],
                "tracks": tracks,
                "materials": {"videos": material_videos, "audios": material_audios,
                              "texts": material_texts},
            }, ensure_ascii=False), encoding="utf-8")
            (native / "draft_meta_info.json").write_text("{}", encoding="utf-8")
            Path(request["projection_report_path"]).write_text(json.dumps({
                "schema_version": 1, "kind": "jianying_native_projection_report",
                "status": "generated_unopened", "adapter_id": "pyjianyingdraft_0_3",
                "adapter_version": "0.3.0", "source_plan_sha256": request["plan_sha256"],
                "adapter_artifact_sha256": request["adapter_wheel_sha256"],
                "adapter_python_sha256": request["adapter_python_sha256"],
                "adapter_runtime_lock": request["adapter_runtime_lock"],
                "adapter_lock_sha256": request["adapter_lock_sha256"],
                "adapter_locked_io_sha256": request["adapter_locked_io_sha256"],
                "adapter_dependencies": {
                    Path(row["path"]).name: row["sha256"]
                    for row in request["adapter_dependencies"]
                },
                "parent_input_locks": request["parent_input_locks"],
                "runner_sha256": request["runner_sha256"],
                "third_party_code_executed": True,
                "editor_store_path_supplied": False,
                "editor_store_operation_requested": False,
                "editor_store_access_control": "not_enforced",
                "editor_store_access_evidence": "unknown",
                "editor_launched_by_orchestrator": False,
                "network_access_control": "not_enforced",
                "network_use_evidence": "unknown",
                "projected": rows,
                "omitted": [{"clip_id": "reference.automatic-master",
                             "reason": "disabled_reference_is_external_fallback"}],
            }), encoding="utf-8")
            return subprocess.CompletedProcess(argv, 0, "ok", "")
        return run

    def test_materializer_has_no_editor_store_parameter_and_publishes_only_under_project(self) -> None:
        self.assertNotIn("draft_store", inspect.signature(
            materialize_project_local_candidate
        ).parameters)
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan, editable, _ = self._authorities(root)
            wheel = root / "pyjianyingdraft-0.3.0-py3-none-any.whl"
            wheel.write_bytes(b"pinned-wheel")
            python = root / ".venv" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"python")
            (python.parent.parent / "pyvenv.cfg").write_text("home = test\n", encoding="utf-8")
            calls: list[dict[str, object]] = []
            with patch("jianying_native_real.ADAPTER_WHEEL_SHA256", sha256_file(wheel)), patch(
                "jianying_native_real.ADAPTER_DEPENDENCY_LOCK", {}
            ), patch(
                "jianying_native_real.subprocess.run", side_effect=self._fake_adapter(calls)
            ):
                manifest = materialize_project_local_candidate(
                    plan_path=plan, output_root=root / "native-output",
                    authorized_root=root, build_id="real-short-v1",
                    adapter_python=python, adapter_wheel=wheel,
                    standard_editable_delivery=editable,
                )

            published = root / "native-output" / "published" / "real-short-v1"
            self.assertEqual(manifest["status"], "generated_awaiting_manual_canary")
            self.assertTrue((published / "native-draft" / "draft_content.json").is_file())
            self.assertIn("手动复制", (published / "README-中文.md").read_text(encoding="utf-8"))
            self.assertNotIn("草稿位置绝对路径", (published / "README-中文.md").read_text(encoding="utf-8"))
            with patch("jianying_native_real.ADAPTER_WHEEL_SHA256", sha256_file(wheel)):
                self.assertEqual(validate_project_local_candidate(
                    published / "candidate-manifest.json", authorized_root=root
                ), [])
            self.assertEqual(len(calls), 1)
            request = calls[0]
            self.assertTrue(Path(str(request["native_parent"])).is_relative_to(
                root / "native-output"
            ))
            base = next(row for row in request["tracks"] if row["track_id"] == "video.base")
            self.assertEqual(base["clips"][0]["source_start_us"], 0)
            self.assertFalse(manifest["safety"]["editor_store_path_supplied"])
            self.assertEqual(manifest["safety"]["editor_store_access_evidence"], "unknown")
            self.assertEqual(manifest["safety"]["network_use_evidence"], "unknown")

            status_path = root / "draft-status.json"
            handoff_path = root / "manual-copy-handoffs" / "manual-copy-handoff.json"
            handoff_path.parent.mkdir()
            status_path.write_text(json.dumps({
                "kind": "jianying_native_draft_status",
                "draft_id": "project-local-test",
                "plan": {"path": str(plan.resolve()), "sha256": sha256_file(plan)},
                "native_package_generated": False,
            }), encoding="utf-8")
            handoff_path.write_text(json.dumps({
                "kind": "jianying_manual_copy_handoff",
                "draft_id": "project-local-test",
                "source_plan": {"path": str(plan.resolve()), "sha256": sha256_file(plan)},
                "candidate_root": None,
            }), encoding="utf-8")
            import jianying_native_real
            original_writer = jianying_native_real._write_json
            def fail_status_once(path, payload):
                if Path(path) == status_path:
                    raise OSError("simulated second-view failure")
                return original_writer(path, payload)
            with patch("jianying_native_real.ADAPTER_WHEEL_SHA256", sha256_file(wheel)), patch(
                "jianying_native_real._write_json", side_effect=fail_status_once
            ):
                with self.assertRaisesRegex(JianyingNativeDraftError, "rerun to recover"):
                    bind_project_local_candidate(
                        manifest_path=published / "candidate-manifest.json",
                        director_status_path=status_path,
                        director_handoff_path=handoff_path,
                        authorized_root=root,
                    )
            self.assertTrue((root / "candidate-binding.json").is_file())
            with patch("jianying_native_real.ADAPTER_WHEEL_SHA256", sha256_file(wheel)):
                binding = bind_project_local_candidate(
                    manifest_path=published / "candidate-manifest.json",
                    director_status_path=status_path,
                    director_handoff_path=handoff_path,
                    authorized_root=root,
                )
            self.assertTrue(binding["status"]["native_package_generated"])
            self.assertEqual(
                binding["handoff"]["candidate_root"],
                str((published / "native-draft").resolve()),
            )
            self.assertIsNone(binding["handoff"]["jianying_draft_store_parameter"])

    def test_validator_detects_native_timeline_drift(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan, editable, _ = self._authorities(root)
            wheel = root / "pyjianyingdraft-0.3.0-py3-none-any.whl"
            wheel.write_bytes(b"wheel")
            python = root / ".venv" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"python")
            (python.parent.parent / "pyvenv.cfg").write_text("home = test\n", encoding="utf-8")
            with patch("jianying_native_real.ADAPTER_WHEEL_SHA256", sha256_file(wheel)), patch(
                "jianying_native_real.ADAPTER_DEPENDENCY_LOCK", {}
            ), patch(
                "jianying_native_real.subprocess.run", side_effect=self._fake_adapter([])
            ):
                materialize_project_local_candidate(
                    plan_path=plan, output_root=root / "out", authorized_root=root,
                    build_id="drift", adapter_python=python, adapter_wheel=wheel,
                    standard_editable_delivery=editable,
                )
            published = root / "out" / "published" / "drift"
            manifest_path = published / "candidate-manifest.json"
            content_path = published / "native-draft" / "draft_content.json"
            original_content = content_path.read_text(encoding="utf-8")
            original_manifest = manifest_path.read_text(encoding="utf-8")
            def target_drift(value):
                value["tracks"][0]["segments"][0]["target_timerange"]["duration"] += 1
            def canvas_drift(value):
                value["canvas_config"]["width"] += 1
            def extra_track(value):
                value["tracks"].append({"name": "video.extra", "type": "video", "segments": []})
            def gain_drift(value):
                audio = next(track for track in value["tracks"] if track["type"] == "audio")
                audio["segments"][0]["volume"] = 1.0
            def transform_drift(value):
                video = next(track for track in value["tracks"] if track["type"] == "video")
                video["segments"][0]["clip"]["alpha"] = 0.5
            def style_drift(value):
                text_material = value["materials"]["texts"][0]
                payload = json.loads(text_material["content"])
                payload["styles"][0]["size"] += 1
                text_material["content"] = json.dumps(payload)
            def boolean_transform(value):
                video = next(track for track in value["tracks"] if track["type"] == "video")
                video["segments"][0]["clip"] = {
                    "alpha": True, "rotation": False,
                    "scale": {"x": True, "y": True},
                    "transform": {"x": False, "y": False},
                }
            def boolean_text_rgb(value):
                text_material = value["materials"]["texts"][0]
                payload = json.loads(text_material["content"])
                payload["styles"][0]["fill"]["content"]["solid"]["color"] = [
                    True, True, True
                ]
                text_material["content"] = json.dumps(payload)
            def nonfinite_transform(value):
                video = next(track for track in value["tracks"] if track["type"] == "video")
                video["segments"][0]["clip"]["alpha"] = float("nan")
            def nonfinite_text_size(value):
                text_material = value["materials"]["texts"][0]
                payload = json.loads(text_material["content"])
                payload["styles"][0]["size"] = float("inf")
                text_material["content"] = json.dumps(payload)
            for mutation, expected in (
                (target_drift, "timeline"), (canvas_drift, "canvas"),
                (extra_track, "track inventory"), (gain_drift, "audio gain"),
                (transform_drift, "visual transform"), (style_drift, "text style"),
                (boolean_transform, "visual transform"),
                (boolean_text_rgb, "text style"),
                (nonfinite_transform, "visual transform"),
                (nonfinite_text_size, "text style"),
            ):
                with self.subTest(expected=expected):
                    content_path.write_text(original_content, encoding="utf-8")
                    manifest_path.write_text(original_manifest, encoding="utf-8")
                    content = json.loads(original_content)
                    mutation(content)
                    content_path.write_text(json.dumps(content), encoding="utf-8")
                    self._refresh_candidate_manifest(manifest_path)
                    with patch("jianying_native_real.ADAPTER_WHEEL_SHA256", sha256_file(wheel)):
                        errors = validate_project_local_candidate(
                            manifest_path, authorized_root=root
                        )
                    self.assertTrue(any(expected in row for row in errors), errors)

    def test_plan_rejects_raw_edl_inpoint_on_conformed_base(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan_path, _, _ = self._authorities(root)
            plan = json.loads(plan_path.read_text(encoding="utf-8"))
            plan["tracks"][0]["clips"][0]["source_start_frame"] = 250
            import hashlib
            plan["plan_sha256"] = hashlib.sha256(json.dumps(
                {key: value for key, value in plan.items() if key != "plan_sha256"},
                ensure_ascii=False, sort_keys=True, separators=(",", ":"),
            ).encode("utf-8")).hexdigest()
            errors = validate_draft_plan(plan, authorized_root=root)
            self.assertTrue(any("EDL" in row for row in errors), errors)

    def test_validator_never_reads_an_outside_manifest_reference(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan, editable, _ = self._authorities(root)
            wheel = root / "pyjianyingdraft-0.3.0-py3-none-any.whl"
            wheel.write_bytes(b"wheel")
            python = root / ".venv" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"python")
            (python.parent.parent / "pyvenv.cfg").write_text("home = test\n", encoding="utf-8")
            with patch("jianying_native_real.ADAPTER_WHEEL_SHA256", sha256_file(wheel)), patch(
                "jianying_native_real.ADAPTER_DEPENDENCY_LOCK", {}
            ), patch(
                "jianying_native_real.subprocess.run", side_effect=self._fake_adapter([])
            ):
                materialize_project_local_candidate(
                    plan_path=plan, output_root=root / "out", authorized_root=root,
                    build_id="outside", adapter_python=python, adapter_wheel=wheel,
                    standard_editable_delivery=editable,
                )
            manifest_path = root / "out" / "published" / "outside" / "candidate-manifest.json"
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            sentinel = root.parent / f"outside-{root.name}.json"
            sentinel.write_text('{"must_not":"be_read"}', encoding="utf-8")
            try:
                manifest["plan"] = {"path": str(sentinel), "sha256": sha256_file(sentinel)}
                import hashlib
                manifest["integrity_sha256"] = hashlib.sha256(json.dumps(
                    {key: value for key, value in manifest.items() if key != "integrity_sha256"},
                    ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                ).encode("utf-8")).hexdigest()
                manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
                import jianying_native_real
                with patch(
                    "jianying_native_real.read_json",
                    wraps=jianying_native_real.read_json,
                ) as reader:
                    errors = validate_project_local_candidate(
                        manifest_path, authorized_root=root
                    )
                read_paths = [Path(call.args[0]).resolve() for call in reader.call_args_list]
                self.assertNotIn(sentinel.resolve(), read_paths)
                self.assertTrue(any("outside" in row or "authorized" in row for row in errors), errors)
            finally:
                sentinel.unlink(missing_ok=True)

    def test_failed_adapter_leaves_no_candidate_or_partial_staging(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan, editable, _ = self._authorities(root)
            wheel = root / "pyjianyingdraft-0.3.0-py3-none-any.whl"
            wheel.write_bytes(b"wheel")
            python = root / ".venv" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"python")
            (python.parent.parent / "pyvenv.cfg").write_text("home = test\n", encoding="utf-8")
            with patch("jianying_native_real.ADAPTER_WHEEL_SHA256", sha256_file(wheel)), patch(
                "jianying_native_real.ADAPTER_DEPENDENCY_LOCK", {}
            ), patch(
                "jianying_native_real.subprocess.run",
                return_value=subprocess.CompletedProcess([], 17, "sensitive stdout", "sensitive stderr"),
            ):
                with self.assertRaisesRegex(JianyingNativeDraftError, "exit 17") as raised:
                    materialize_project_local_candidate(
                        plan_path=plan, output_root=root / "out", authorized_root=root,
                        build_id="fails", adapter_python=python, adapter_wheel=wheel,
                        standard_editable_delivery=editable,
                    )
            self.assertNotIn("sensitive", str(raised.exception))
            self.assertFalse((root / "out" / "published" / "fails").exists())
            self.assertEqual(list((root / "out" / "staging").iterdir()), [])

    def test_generation_pins_output_and_staging_against_rename(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan, editable, _ = self._authorities(root)
            wheel = root / "pyjianyingdraft-0.3.0-py3-none-any.whl"
            wheel.write_bytes(b"wheel")
            python = root / ".venv" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"python")
            (python.parent.parent / "pyvenv.cfg").write_text(
                "home = test\n", encoding="utf-8"
            )
            delegate = self._fake_adapter([])

            def attempt_swaps(argv, **kwargs):
                request_path = Path(argv[argv.index("--request") + 1])
                request = json.loads(request_path.read_text(encoding="utf-8"))
                staging = Path(request["native_parent"])
                for source, target in (
                    (staging, staging.with_name(staging.name + "-swapped")),
                    (staging.parent, staging.parent.with_name("published-swapped")),
                ):
                    with self.assertRaises(PermissionError):
                        source.rename(target)
                media_source = Path(request["tracks"][0]["clips"][0]["source_path"])
                with self.assertRaises(PermissionError):
                    media_source.rename(media_source.with_name("media-swapped.mp4"))
                authorized = Path(request["authorized_root"])
                with self.assertRaises(PermissionError):
                    authorized.rename(authorized.with_name("authorized-swapped"))
                return delegate(argv, **kwargs)

            with patch("jianying_native_real.ADAPTER_WHEEL_SHA256", sha256_file(wheel)), patch(
                "jianying_native_real.subprocess.run", side_effect=attempt_swaps
            ):
                materialize_project_local_candidate(
                    plan_path=plan, output_root=root / "out", authorized_root=root,
                    build_id="race-safe", adapter_python=python, adapter_wheel=wheel,
                    standard_editable_delivery=editable,
                )
            self.assertTrue(
                (root / "out" / "published" / "race-safe" / "native-draft").is_dir()
            )

    def test_validator_fails_closed_for_invalid_budget_and_native_shapes(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            plan, editable, _ = self._authorities(root)
            wheel = root / "pyjianyingdraft-0.3.0-py3-none-any.whl"
            wheel.write_bytes(b"wheel")
            python = root / ".venv" / "Scripts" / "python.exe"
            python.parent.mkdir(parents=True)
            python.write_bytes(b"python")
            (python.parent.parent / "pyvenv.cfg").write_text(
                "home = test\n", encoding="utf-8"
            )
            with patch("jianying_native_real.ADAPTER_WHEEL_SHA256", sha256_file(wheel)), patch(
                "jianying_native_real.subprocess.run", side_effect=self._fake_adapter([])
            ):
                materialize_project_local_candidate(
                    plan_path=plan, output_root=root / "out", authorized_root=root,
                    build_id="malformed", adapter_python=python, adapter_wheel=wheel,
                    standard_editable_delivery=editable,
                )
            package = root / "out" / "published" / "malformed"
            manifest_path = package / "candidate-manifest.json"
            content_path = package / "native-draft" / "draft_content.json"
            original_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            original_content = json.loads(content_path.read_text(encoding="utf-8"))

            for budget in (float("nan"), float("inf"), True, 0, 65):
                with self.subTest(budget=budget):
                    manifest = dict(original_manifest)
                    manifest["max_package_gib"] = budget
                    manifest["integrity_sha256"] = hashlib.sha256(json.dumps(
                        {key: value for key, value in manifest.items()
                         if key != "integrity_sha256"},
                        ensure_ascii=False, sort_keys=True, separators=(",", ":"),
                    ).encode("utf-8")).hexdigest()
                    manifest_path.write_text(
                        json.dumps(manifest, allow_nan=True), encoding="utf-8"
                    )
                    with patch("jianying_native_real.ADAPTER_WHEEL_SHA256", sha256_file(wheel)):
                        errors = validate_project_local_candidate(
                            manifest_path, authorized_root=root
                        )
                    self.assertTrue(any("budget" in row for row in errors), errors)

            for mutation, expected in (
                (lambda value: value["materials"].__setitem__("videos", 1), "material bucket"),
                (lambda value: value["tracks"][0].__setitem__("segments", 1), "segment inventory"),
                (lambda value: value["materials"]["texts"][0].__setitem__("content", "[]"), "native text"),
            ):
                with self.subTest(expected=expected):
                    content = json.loads(json.dumps(original_content))
                    mutation(content)
                    content_path.write_text(json.dumps(content), encoding="utf-8")
                    manifest_path.write_text(
                        json.dumps(original_manifest), encoding="utf-8"
                    )
                    self._refresh_candidate_manifest(manifest_path)
                    with patch("jianying_native_real.ADAPTER_WHEEL_SHA256", sha256_file(wheel)):
                        errors = validate_project_local_candidate(
                            manifest_path, authorized_root=root
                        )
                    self.assertTrue(any(expected in row for row in errors), errors)

    def test_runner_rejects_wrong_wheel_even_when_request_hash_matches(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            wheel = root / "pyjianyingdraft-0.3.0-py3-none-any.whl"
            wheel.write_bytes(b"not-the-pinned-wheel")
            import hashlib
            request = {
                "schema_version": 1,
                "kind": "jianying_adapter_execution_request",
                "plan_sha256": "0" * 64,
                "draft_id": "reject-wrong-wheel",
                "fps": 25,
                "canvas": {"width": 1080, "height": 1920},
                "native_draft_root": str(root / "native-draft"),
                "native_parent": str(root),
                "projection_report_path": str(root / "projection-report.json"),
                "adapter_wheel": str(wheel),
                "adapter_wheel_sha256": hashlib.sha256(wheel.read_bytes()).hexdigest(),
                "adapter_dependencies": [],
                "authorized_root": str(root),
                "adapter_python_sha256": hashlib.sha256(Path(sys.executable).read_bytes()).hexdigest(),
                "adapter_runtime_lock": ADAPTER_RUNTIME_LOCK,
                "adapter_lock_sha256": sha256_file(
                    ROOT / "scripts" / "jianying_native_adapter_lock.py"
                ),
                "adapter_locked_io_sha256": sha256_file(
                    ROOT / "scripts" / "jianying_native_locked_io.py"
                ),
                "runner_sha256": sha256_file(ROOT / "scripts" / "jianying_native_adapter_runner.py"),
                "network_access_control": "not_enforced",
                "parent_input_locks": True,
                "adapter_runtime_root": str(root / ".adapter-runtime"),
                "tracks": [],
                "omitted": [],
            }
            with self.assertRaisesRegex(ValueError, "compiled lock"):
                execute_adapter_request(
                    request, expected_parent=root, authorized_root=root
                )

    @unittest.skipUnless(os.name == "nt", "Windows locked-source regression")
    def test_runner_rejects_ancestor_junction_and_holds_source_until_save(self) -> None:
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder) / "authorized"
            outside = Path(folder) / "outside"
            root.mkdir()
            outside.mkdir()
            (outside / "probe.bin").write_bytes(b"outside")
            junction = root / "alias"
            result = subprocess.run(
                ["cmd", "/c", "mklink", "/J", str(junction), str(outside)],
                capture_output=True, text=True, check=False,
            )
            if result.returncode:
                self.skipTest("unable to create NTFS junction")
            try:
                with self.assertRaisesRegex(ValueError, "redirected"):
                    _locked_authorized_bytes(
                        junction / "probe.bin", authorized_root=root,
                        max_bytes=1024,
                    )
            finally:
                os.rmdir(junction)

            source = root / "source.mp4"
            source.write_bytes(b"approved")
            digest = _locked_authorized_hash(source, authorized_root=root)
            self.assertEqual(digest, hashlib.sha256(b"approved").hexdigest())


if __name__ == "__main__":
    unittest.main()
