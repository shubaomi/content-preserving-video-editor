#!/usr/bin/env python3
"""Capture deterministic browser evidence for the eight portrait components."""
from __future__ import annotations

import argparse
from contextlib import contextmanager
from functools import partial
import hashlib
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
import threading
import tempfile
from pathlib import Path
from typing import Any, Mapping

from director_contracts import sha256_file, write_json
from capture_hyperframes_runtime_evidence import resolve_browser_executable
from portrait_motion_recipes import (
    PORTRAIT_COMPONENT_CSS,
    PORTRAIT_COMPONENT_JS,
    load_portrait_recipe_registry,
    recipe_fingerprint,
)
from safe_generated_output import (
    SafeGeneratedOutputError, atomic_replace_file, atomic_write_text, safe_generated_directory,
    safe_generated_target,
)


PHASES = ("entrance", "explain", "hold", "exit", "post_exit")
SEEK_SEQUENCE = (
    "hold", "entrance", "hold", "post_exit", "explain",
    "exit", "post_exit", "entrance", "hold",
)
PHASE_TIMES = {
    "entrance": 0.11, "explain": 0.46, "hold": 0.96,
    "exit": 1.46, "post_exit": 1.91,
}

NEGATIVE_CASES = {
    "PBM-02": ("missing", "wrong_kind", "stale_hash", "out_of_window"),
    "PBM-03": ("missing", "wrong_kind", "stale_hash", "out_of_window"),
    "PBM-05": ("missing", "wrong_kind", "stale_hash", "out_of_window"),
    "PBM-06": ("missing", "stale_hash"),
    "PBM-07": ("missing", "wrong_kind", "stale_hash", "out_of_window"),
}
NEGATIVE_ERROR_MARKERS = {
    "missing": "is required",
    "wrong_kind": "kind is invalid",
    "stale_hash": "differs from compiler projection",
    "out_of_window": "outside the event window",
}
CAPTURE_TOOL = Path(__file__).resolve()


class _QuietStaticHandler(SimpleHTTPRequestHandler):
    """Serve local capture assets without corrupting unittest result lines."""

    def log_message(self, format: str, *args: object) -> None:
        return


class _QuietThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request: object, client_address: object) -> None:
        return


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")).hexdigest()


@contextmanager
def _serve_directory(root: Path):
    handler = partial(_QuietStaticHandler, directory=str(root))
    server = _QuietThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _renderer_payload_errors(payload: Any) -> list[str]:
    if not isinstance(payload, Mapping):
        return ["portrait renderer payload must be a mapping"]
    errors: list[str] = []
    if payload.get("schema_version") != 1:
        errors.append("portrait renderer payload schema_version must equal 1")
    if payload.get("component_api") != "hongrun-portrait-components-v2":
        errors.append("portrait renderer payload component_api is invalid")
    declared_hash = payload.get("payload_sha256")
    try:
        actual_hash = _stable_hash({
            key: value for key, value in payload.items() if key != "payload_sha256"
        })
    except (TypeError, ValueError):
        actual_hash = None
        errors.append("portrait renderer payload contains non-canonical values")
    if declared_hash != actual_hash:
        errors.append("portrait renderer payload hash is stale")
    events = payload.get("events")
    if not isinstance(events, list) or not events:
        return [*errors, "portrait renderer payload events must be a non-empty list"]
    event_ids: list[str] = []
    semantic_ids: list[str] = []
    for index, row in enumerate(events):
        if not isinstance(row, Mapping):
            errors.append(f"portrait renderer payload events[{index}] must be a mapping")
            continue
        event_id = str(row.get("eventId") or "")
        semantic_id = str(row.get("semanticEventId") or "")
        if not event_id or not semantic_id:
            errors.append(f"portrait renderer payload events[{index}] is missing IDs")
        event_ids.append(event_id)
        semantic_ids.append(semantic_id)
        if row.get("recipeId") not in {f"PBM-{number:02d}" for number in range(1, 9)}:
            errors.append(f"portrait renderer payload {event_id} recipe is invalid")
        for window_name in ("sourceWindow", "outputWindow"):
            window = row.get(window_name)
            if not isinstance(window, Mapping):
                errors.append(f"portrait renderer payload {event_id} {window_name} is invalid")
                continue
            start = window.get("start_seconds")
            end = window.get("end_seconds")
            if (
                isinstance(start, bool) or isinstance(end, bool)
                or not isinstance(start, (int, float)) or not isinstance(end, (int, float))
                or not math.isfinite(float(start)) or not math.isfinite(float(end))
                or float(end) <= float(start)
            ):
                errors.append(f"portrait renderer payload {event_id} {window_name} is invalid")
        if not isinstance(row.get("bindings"), Mapping) or not isinstance(
            row.get("expectedBindings"), Mapping
        ):
            errors.append(f"portrait renderer payload {event_id} bindings are missing")
        elif row["bindings"] != row["expectedBindings"]:
            errors.append(f"portrait renderer payload {event_id} expected bindings differ")
        digests = row.get("authorityDigests")
        if not isinstance(digests, Mapping):
            errors.append(f"portrait renderer payload {event_id} authority digests are missing")
        else:
            for binding_key, digest_key in (
                ("subjectBinding", "authority_sha256"),
                ("gestureBinding", "authority_sha256"),
                ("chapterBoundaryBinding", "authority_sha256"),
                ("assetRef", "sha256"),
            ):
                bindings = row.get("bindings")
                binding = bindings.get(binding_key) if isinstance(bindings, Mapping) else None
                if binding is not None and (
                    not isinstance(binding, Mapping)
                    or digests.get(binding_key) != binding.get(digest_key)
                ):
                    errors.append(f"portrait renderer payload {event_id} {binding_key} digest differs")
        if row.get("recipeId") == "PBM-06" and isinstance(row.get("bindings"), Mapping):
            render_asset = row["bindings"].get("renderAssetRef")
            if not isinstance(render_asset, Mapping):
                errors.append(f"portrait renderer payload {event_id} render asset is missing")
            else:
                render_path = Path(str(render_asset.get("path") or "")).resolve()
                if not render_path.is_file() or render_asset.get("sha256") != sha256_file(render_path):
                    errors.append(f"portrait renderer payload {event_id} render asset is stale")
                if row["bindings"].get("assetRuntimeUrl") != render_path.as_uri():
                    errors.append(f"portrait renderer payload {event_id} runtime asset URL is stale")
                asset_ref = row["bindings"].get("assetRef")
                if not isinstance(asset_ref, Mapping) or (
                    asset_ref.get("path") != str(render_path)
                    or asset_ref.get("sha256") != render_asset.get("sha256")
                ):
                    errors.append(f"portrait renderer payload {event_id} runtime asset ref differs")
                expected_url = f"./assets/portrait-brand-v2/media/{render_path.name}"
                expected_parent = ("assets", "portrait-brand-v2", "media")
                actual_parent = tuple(render_path.parts[-4:-1]) if len(render_path.parts) >= 4 else ()
                if actual_parent != expected_parent or row["bindings"].get("assetUrl") != expected_url:
                    errors.append(f"portrait renderer payload {event_id} project asset URL is invalid")
    if len(event_ids) != len(set(event_ids)) or len(semantic_ids) != len(set(semantic_ids)):
        errors.append("portrait renderer payload event IDs must be unique")
    return errors


def validate_portrait_runtime_evidence(
    evidence: Any, renderer_payload_path: Path,
) -> list[str]:
    """Validate current compiler payload, browser phases, and binding negatives."""
    if not isinstance(evidence, Mapping):
        return ["portrait runtime evidence must be a mapping"]
    errors: list[str] = []
    renderer_payload_path = renderer_payload_path.resolve()
    if not renderer_payload_path.is_file():
        return [f"portrait renderer payload is missing: {renderer_payload_path}"]
    try:
        payload = json.loads(renderer_payload_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        return [f"portrait renderer payload is unreadable: {error}"]
    errors.extend(_renderer_payload_errors(payload))
    if errors:
        return errors
    payload_ref = evidence.get("renderer_payload")
    if not isinstance(payload_ref, Mapping):
        errors.append("portrait runtime evidence renderer_payload is missing")
    else:
        try:
            declared_path = Path(str(payload_ref.get("path") or "")).resolve()
        except (OSError, ValueError):
            declared_path = Path()
        if declared_path != renderer_payload_path:
            errors.append("portrait runtime evidence renderer payload path differs")
        if payload_ref.get("sha256") != sha256_file(renderer_payload_path):
            errors.append("portrait runtime evidence renderer payload hash is stale")
    if evidence.get("schema_version") != 2 or evidence.get("status") != "pass":
        errors.append("portrait runtime evidence is not a passing schema-v2 receipt")
    if evidence.get("errors") not in ([], None):
        errors.append("portrait runtime evidence contains errors")
    capture_tool = evidence.get("capture_tool")
    if not isinstance(capture_tool, Mapping) or (
        Path(str(capture_tool.get("path") or "")).resolve() != CAPTURE_TOOL
        or capture_tool.get("sha256") != sha256_file(CAPTURE_TOOL)
    ):
        errors.append("portrait runtime evidence does not bind the current capture tool")
    fixture = evidence.get("fixture")
    if not isinstance(fixture, Mapping):
        errors.append("portrait runtime evidence fixture is missing")
    else:
        fixture_path = Path(str(fixture.get("path") or "")).resolve()
        expected_fixture = _fixture_html(timeline_enabled=True, renderer_payload=payload)
        try:
            if (
                fixture.get("sha256") != sha256_file(fixture_path)
                or fixture_path.read_text(encoding="utf-8") != expected_fixture
            ):
                errors.append("portrait runtime evidence fixture is stale")
        except OSError:
            errors.append("portrait runtime evidence fixture is missing")
    assets = evidence.get("component_assets")
    asset_hashes: set[str] = set()
    if not isinstance(assets, list):
        errors.append("portrait runtime component assets must be a list")
    else:
        for index, row in enumerate(assets):
            if not isinstance(row, Mapping):
                errors.append(f"portrait runtime component_assets[{index}] must be a mapping")
                continue
            path = Path(str(row.get("path") or "")).resolve()
            if not path.is_file() or row.get("sha256") != sha256_file(path):
                errors.append(f"portrait runtime component asset {index} is missing or stale")
            else:
                asset_hashes.add(str(row["sha256"]))
    for source in (PORTRAIT_COMPONENT_JS, PORTRAIT_COMPONENT_CSS):
        if sha256_file(source) not in asset_hashes:
            errors.append(f"portrait runtime evidence does not bind current {source.name}")

    expected_rows = {
        str(row["eventId"]): row
        for row in payload.get("events") or [] if isinstance(row, Mapping)
    }
    registry = {
        str(row["recipe_id"]): row
        for row in load_portrait_recipe_registry().get("recipes") or []
        if isinstance(row, Mapping)
    }
    recipes = evidence.get("recipes")
    observed: dict[str, Mapping[str, Any]] = {}
    if not isinstance(recipes, list):
        errors.append("portrait runtime recipes must be a list")
    else:
        for index, row in enumerate(recipes):
            if not isinstance(row, Mapping):
                errors.append(f"portrait runtime recipes[{index}] must be a mapping")
                continue
            event_id = str(row.get("event_id") or "")
            if event_id in observed:
                errors.append(f"portrait runtime duplicates event {event_id}")
            observed[event_id] = row
    if list(observed) != list(expected_rows):
        errors.append("portrait runtime event set/order differs from renderer payload")
    for event_id, expected_event in expected_rows.items():
        recipe_id = str(expected_event.get("recipeId") or "")
        row = observed.get(event_id)
        if not isinstance(row, Mapping):
            continue
        if row.get("recipe_id") != recipe_id:
            errors.append(f"portrait runtime {event_id} recipe differs")
        recipe = registry.get(recipe_id)
        if not isinstance(recipe, Mapping) or row.get("fingerprints") != recipe_fingerprint(recipe):
            errors.append(f"portrait runtime {event_id} recipe fingerprint is stale")
        phases = row.get("phases")
        if not isinstance(phases, list) or [
            phase.get("phase") if isinstance(phase, Mapping) else None for phase in phases
        ] != list(PHASES):
            errors.append(f"portrait runtime {event_id} phase inventory is incomplete")
            phases = []
        phase_by_name: dict[str, Mapping[str, Any]] = {}
        for phase_index, phase in enumerate(phases):
            if not isinstance(phase, Mapping):
                errors.append(f"portrait runtime {event_id} phase {phase_index} must be a mapping")
                continue
            phase_name = str(phase.get("phase") or "")
            phase_by_name[phase_name] = phase
            if phase.get("event_phase") != phase_name or phase.get("recipe") != recipe_id:
                errors.append(f"portrait runtime {event_id} {phase_name} DOM phase differs")
            if phase.get("visible_copy") != list(expected_event.get("visibleCopy") or []):
                errors.append(f"portrait runtime {event_id} {phase_name} visible copy differs")
            if phase.get("inside_canvas") is not True:
                errors.append(f"portrait runtime {event_id} {phase_name} leaves canvas")
            if phase_name != "post_exit" and phase.get("caption_clear") is not True:
                errors.append(f"portrait runtime {event_id} {phase_name} enters caption lane")
            opacity = phase.get("opacity")
            if isinstance(opacity, bool) or not isinstance(opacity, (int, float)) or not math.isfinite(float(opacity)):
                errors.append(f"portrait runtime {event_id} {phase_name} opacity is invalid")
            elif phase_name == "post_exit" and abs(float(opacity)) > 1e-6:
                errors.append(f"portrait runtime {event_id} post-exit is not clean")
            elif phase_name != "post_exit" and float(opacity) <= 0:
                errors.append(f"portrait runtime {event_id} {phase_name} is not visible")
            for bbox_name in ("primary_bbox", "painted_bbox"):
                bbox = phase.get(bbox_name)
                values = [bbox.get(key) for key in ("x", "y", "width", "height")] if isinstance(bbox, Mapping) else []
                if len(values) != 4 or any(
                    isinstance(value, bool) or not isinstance(value, (int, float))
                    or not math.isfinite(float(value)) for value in values
                ) or any(float(value) < 0 for value in values[2:]):
                    errors.append(f"portrait runtime {event_id} {phase_name} {bbox_name} is invalid")
            snapshot = phase.get("snapshot")
            if not isinstance(snapshot, Mapping):
                errors.append(f"portrait runtime {event_id} {phase_name} snapshot is missing")
            else:
                snapshot_path = Path(str(snapshot.get("path") or "")).resolve()
                try:
                    current_hash = sha256_file(snapshot_path)
                    from PIL import Image

                    with Image.open(snapshot_path) as image:
                        image.verify()
                    with Image.open(snapshot_path) as image:
                        width, height = image.size
                    if width < 320 or height < 180:
                        errors.append(f"portrait runtime {event_id} {phase_name} snapshot is too small")
                    if snapshot.get("sha256") != current_hash:
                        errors.append(f"portrait runtime {event_id} {phase_name} snapshot hash is stale")
                except (OSError, ValueError):
                    errors.append(f"portrait runtime {event_id} {phase_name} snapshot is not decodable")
        hold = phase_by_name.get("hold")
        if isinstance(hold, Mapping):
            specifics = hold.get("recipe_specific")
            if not isinstance(specifics, Mapping):
                errors.append(f"portrait runtime {event_id} hold recipe observations are missing")
            else:
                bindings = expected_event.get("bindings") or {}
                if recipe_id == "PBM-03" and specifics.get("gesture_points") != str(
                    len((bindings.get("gestureBinding") or {}).get("points") or [])
                ):
                    errors.append(f"portrait runtime {event_id} gesture geometry differs")
                if recipe_id in {"PBM-02", "PBM-05"} and specifics.get("subject_evidence") != (
                    (bindings.get("subjectBinding") or {}).get("evidence_id")
                ):
                    errors.append(f"portrait runtime {event_id} subject binding differs")
                if recipe_id == "PBM-05" and specifics.get("source_camera_active") != "true":
                    errors.append(f"portrait runtime {event_id} source camera transform is missing")
                if recipe_id == "PBM-06":
                    if specifics.get("semantic_asset_hash") != (
                        (bindings.get("assetRef") or {}).get("sha256")
                    ) or specifics.get("semantic_asset_loaded") is not True:
                        errors.append(f"portrait runtime {event_id} semantic asset observation differs")
                    expected_asset_url = str(bindings.get("assetUrl") or "").removeprefix(".")
                    if specifics.get("semantic_asset_protocol") != "http:" or not str(
                        specifics.get("semantic_asset_current_src") or ""
                    ).endswith(expected_asset_url):
                        errors.append(f"portrait runtime {event_id} HTTP semantic asset binding differs")
                if recipe_id == "PBM-07" and specifics.get("chapter_boundary") != (
                    (bindings.get("chapterBoundaryBinding") or {}).get("evidence_id")
                ):
                    errors.append(f"portrait runtime {event_id} chapter boundary differs")
        if row.get("seek_sequence") != list(SEEK_SEQUENCE):
            errors.append(f"portrait runtime {event_id} seek sequence is incomplete")
        repeat = row.get("seek_repeat_snapshot")
        hold_snapshot = (hold or {}).get("snapshot") if isinstance(hold, Mapping) else None
        if not isinstance(repeat, Mapping) or not isinstance(hold_snapshot, Mapping):
            errors.append(f"portrait runtime {event_id} seek repeat snapshots are missing")
        else:
            repeat_path = Path(str(repeat.get("path") or "")).resolve()
            hold_path = Path(str(hold_snapshot.get("path") or "")).resolve()
            try:
                repeat_hash = sha256_file(repeat_path)
                measured_mae = _image_mae(hold_path, repeat_path)
                declared_mae = float(row.get("seek_repeat_mae"))
                if (
                    repeat.get("sha256") != repeat_hash
                    or row.get("seek_repeat_hold_sha256") != repeat_hash
                    or row.get("seek_repeat_reference_sha256") != hold_snapshot.get("sha256")
                    or not math.isfinite(declared_mae)
                    or abs(declared_mae - measured_mae) > 0.01
                    or measured_mae > 1.5
                ):
                    errors.append(f"portrait runtime {event_id} seek repeat evidence differs")
            except (OSError, ValueError, TypeError):
                errors.append(f"portrait runtime {event_id} seek repeat evidence is invalid")
        if row.get("seek_repeat_matches") is not True:
            errors.append(f"portrait runtime {event_id} seek repeat failed")

    negative = evidence.get("required_binding_negative_checks")
    observed_negative: dict[tuple[str, str, str], Mapping[str, Any]] = {}
    if not isinstance(negative, list):
        errors.append("portrait runtime binding negative checks must be a list")
    else:
        for index, row in enumerate(negative):
            if not isinstance(row, Mapping):
                errors.append(f"portrait runtime negative check {index} must be a mapping")
                continue
            key = (str(row.get("event_id") or ""), str(row.get("recipe_id") or ""), str(row.get("case") or ""))
            if key in observed_negative:
                errors.append(f"portrait runtime duplicates negative check {key}")
            observed_negative[key] = row
    expected_negative = {
        (event_id, recipe_id, case)
        for event_id, expected_event in expected_rows.items()
        for recipe_id in (str(expected_event.get("recipeId") or ""),)
        for case in NEGATIVE_CASES.get(recipe_id, ())
    }
    if set(observed_negative) != expected_negative:
        errors.append("portrait runtime binding negative matrix is incomplete or stale")
    if any(row.get("rejected") is not True for row in observed_negative.values()):
        errors.append("portrait runtime accepted a mutated required binding")
    expected_by_id = expected_rows
    for (event_id, recipe_id, case), row in observed_negative.items():
        marker = NEGATIVE_ERROR_MARKERS.get(case)
        if not marker or marker not in str(row.get("error") or ""):
            errors.append(
                f"portrait runtime negative check {(event_id, recipe_id, case)} has the wrong error"
            )
        expected_event = expected_by_id.get(event_id)
        if not isinstance(expected_event, Mapping):
            continue
        expected_mutation = _mutated_bindings(expected_event, case)
        if row.get("mutated_bindings") != expected_mutation:
            errors.append(
                f"portrait runtime negative check {(event_id, recipe_id, case)} mutation differs"
            )
    claims = evidence.get("claims")
    required_claims = (
        "hyperframes_timeline_registered", "seek_safety_verified",
        "required_recipe_bindings_fail_closed", "compiler_renderer_payload_consumed",
    )
    if not isinstance(claims, Mapping) or any(claims.get(key) is not True for key in required_claims):
        errors.append("portrait runtime evidence claims are incomplete")
    return errors


def replay_portrait_runtime_gate(
    evidence: Any, renderer_payload_path: Path, *, browser_path: Path | None = None,
) -> list[str]:
    """Independently rerun current browser capture; receipts alone are not authority."""
    structural = validate_portrait_runtime_evidence(evidence, renderer_payload_path)
    if structural:
        return structural
    engine = evidence.get("runtime_engine") if isinstance(evidence, Mapping) else None
    if not isinstance(engine, Mapping):
        return ["portrait runtime evidence runtime_engine is missing"]
    engine_path = Path(str(engine.get("path") or "")).resolve()
    if not engine_path.is_file() or engine.get("sha256") != sha256_file(engine_path):
        return ["portrait runtime evidence runtime_engine is missing or stale"]
    with tempfile.TemporaryDirectory(prefix="cpve-pbm-v2-runtime-replay-") as temporary:
        replay = capture(
            Path(temporary), browser_path=browser_path,
            hyperframes_gsap=engine_path,
            renderer_payload_path=renderer_payload_path,
        )
        replay_errors = validate_portrait_runtime_evidence(replay, renderer_payload_path)
        if replay.get("status") != "pass" or replay_errors:
            return ["portrait runtime browser replay failed", *replay_errors]
    return []


def _image_mae(first: Path, second: Path) -> float:
    from PIL import Image, ImageChops, ImageStat

    with Image.open(first).convert("RGB") as left, Image.open(second).convert("RGB") as right:
        means = ImageStat.Stat(ImageChops.difference(left, right)).mean
    return sum(means) / len(means)


def _fixture_html(
    *, timeline_enabled: bool = False,
    renderer_payload: Mapping[str, Any] | None = None,
) -> str:
    timeline_script = ""
    if timeline_enabled:
        timeline_script = """<script src="./assets/gsap.min.js"></script>
<script>
window.addEventListener('portrait-fixture-ready',()=>{
  window.__timelines=window.__timelines||{};
  const master=gsap.timeline({paused:true});
  const offsets={};
  window.fixtureEvents.forEach((row,index)=>{
    const recipeId=row.recipeId; const eventId=row.eventId;
    const node=document.getElementById(eventId);
    const at=index*2.2; offsets[eventId]=at;
    master.set(node,{display:'block',opacity:1,x:-18,scale:.96,attr:{'data-phase':'entrance'},'--pbm-progress':.22},at+0.10)
      .to(node,{x:0,scale:1,duration:.20,ease:'power3.out'},at+0.10)
      .set(node,{attr:{'data-phase':'explain'},'--pbm-progress':.62},at+0.45)
      .to(node,{y:-6,duration:.28,ease:'power2.inOut'},at+0.45)
      .set(node,{attr:{'data-phase':'hold'},'--pbm-progress':1},at+0.95)
      .to(node,{y:0,duration:.20,ease:'power2.out'},at+0.95)
      .set(node,{attr:{'data-phase':'exit'},'--pbm-progress':.45},at+1.45)
      .to(node,{opacity:0,x:14,duration:.22,ease:'power2.in'},at+1.45)
      .set(node,{display:'none',opacity:0,x:0,y:0,scale:1,attr:{'data-phase':'post_exit'},'--pbm-progress':0},at+1.90);
    if(recipeId==='PBM-05'){
      const source=document.getElementById('source-media');
      master.set(source,{scale:1.035,yPercent:-.8,attr:{'data-pbm-camera-active':'true'}},at+0.10)
        .set(source,{scale:1,yPercent:0,clearProps:'transform',attr:{'data-pbm-camera-active':'false'}},at+1.90);
    }
  });
  window.__timelines['portrait-fixture']=master;
  window.fixtureSeek=(eventId,time)=>{master.seek(offsets[eventId]+time,false);return window.fixtureManifest(eventId);};
  window.fixtureTimelineReady=true;
});
</script>"""
    payload_json = json.dumps(
        renderer_payload or {
            "schema_version": 1,
            "component_api": "hongrun-portrait-components-v2",
            "events": [],
            "payload_sha256": "",
        },
        ensure_ascii=False, separators=(",", ":"),
    ).replace("</", "<\\/")
    timeline_bootstrap = """
window.fixturePayload=__RENDERER_PAYLOAD__;
const fixtureEvents=window.fixturePayload.events;
const recipeIds=fixtureEvents.map(row=>row.recipeId);
function clone(value){return JSON.parse(JSON.stringify(value));}
function bindingKey(recipeId){return ({'PBM-02':'subjectBinding','PBM-03':'gestureBinding','PBM-05':'subjectBinding','PBM-07':'chapterBoundaryBinding'})[recipeId]||null;}
function mutatedProps(row,caseName){
  const props=clone(row); props.eventId=`negative-${row.eventId}-${caseName}`;
  props.bindings=clone(row.bindings); props.expectedBindings=clone(row.expectedBindings);
  const key=bindingKey(row.recipeId);
  if(caseName==='missing') props.bindings={};
  if(caseName==='wrong_kind'&&key) props.bindings[key].kind='transcript_word';
  if(caseName==='stale_hash'){
    if(row.recipeId==='PBM-06') props.bindings.assetRef.sha256='0'.repeat(64);
    else props.bindings[key].authority_sha256='0'.repeat(64);
  }
  if(caseName==='out_of_window'&&key) props.bindings[key].window={start_seconds:999,end_seconds:1000};
  props.expectedBindings=clone(props.bindings);
  return props;
}
const negativeCases={'PBM-02':['missing','wrong_kind','stale_hash','out_of_window'],'PBM-03':['missing','wrong_kind','stale_hash','out_of_window'],'PBM-05':['missing','wrong_kind','stale_hash','out_of_window'],'PBM-06':['missing','stale_hash'],'PBM-07':['missing','wrong_kind','stale_hash','out_of_window']};
fixtureEvents.forEach(row=>root.append(createPortraitMotion(row)));
window.fixtureRequiredBindingErrors=fixtureEvents.flatMap(row=>(negativeCases[row.recipeId]||[]).map(caseName=>{
  try {
    const mutated=mutatedProps(row,caseName);
    createPortraitMotion(mutated);
    return {event_id:row.eventId,recipe_id:row.recipeId,case:caseName,rejected:false,error:null,mutated_bindings:mutated.bindings};
  } catch (error) {
    const mutated=mutatedProps(row,caseName);
    return {event_id:row.eventId,recipe_id:row.recipeId,case:caseName,rejected:true,error:String(error&&error.message||error),mutated_bindings:mutated.bindings};
  }
}));
window.fixtureEvents=fixtureEvents;
window.fixtureRecipeIds=recipeIds;
window.fixtureManifest=(eventId)=>visibleCopyManifest(document.getElementById(eventId));
window.fixtureStaticPhase=(eventId,phase,progress)=>{const node=document.getElementById(eventId);applyPortraitPhase(node,phase,progress);return visibleCopyManifest(node)};
window.fixtureReady=true;
window.dispatchEvent(new Event('portrait-fixture-ready'));
""".replace("__RENDERER_PAYLOAD__", payload_json)
    return """<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=540,height=960">
<link rel="stylesheet" href="./hyperframes-portrait-components-v2.css">
<style>
html,body{margin:0;background:#030d0d}.composition{position:relative;width:540px;height:960px;overflow:hidden;background:#0b2524}
.source{position:absolute;inset:0;background:radial-gradient(circle at 51% 35%,#365b57 0 13%,transparent 13.5%),linear-gradient(145deg,#163b38,#061817 62%,#0e2928)}
.source::after{content:"";position:absolute;left:34%;top:22%;width:34%;height:60%;border-radius:46% 46% 18% 18%;background:linear-gradient(#8baaa3,#335d58 38%,#173b39);opacity:.9}
.caption-safe{position:absolute;left:5%;right:5%;bottom:6%;height:10%;border-top:1px dashed rgba(255,255,255,.12);color:#abc0bc;font:18px system-ui;display:flex;align-items:center;justify-content:center}
</style></head><body>
<main id="composition" class="composition" data-composition-id="portrait-fixture" data-start="0" data-width="540" data-height="960" data-duration="18">
<div id="source-media" class="source" data-pbm-camera-active="false"></div><div class="caption-safe" data-layout-allow-caption-zone>caption safe lane</div></main>
<script type="module">
import {createPortraitMotion,applyPortraitPhase,visibleCopyManifest} from './hyperframes-portrait-components-v2.js';
const root=document.getElementById('composition');
__TIMELINE_BOOTSTRAP__
    </script>""".replace("__TIMELINE_BOOTSTRAP__", timeline_bootstrap) + timeline_script + "</body></html>"


def _materialize_http_assets(
    output_dir: Path, renderer_payload: Mapping[str, Any],
) -> None:
    """Mirror hash-bound renderer assets at their declared project URLs."""
    for row in renderer_payload.get("events") or []:
        if not isinstance(row, Mapping) or row.get("recipeId") != "PBM-06":
            continue
        bindings = row.get("bindings")
        if not isinstance(bindings, Mapping):
            continue
        render_ref = bindings.get("renderAssetRef")
        asset_url = str(bindings.get("assetUrl") or "")
        if not isinstance(render_ref, Mapping) or not asset_url.startswith("./"):
            raise ValueError("PBM-06 renderer asset binding is incomplete")
        source = Path(str(render_ref.get("path") or "")).resolve()
        relative = Path(asset_url[2:])
        try:
            destination = safe_generated_target(output_dir, relative)
        except SafeGeneratedOutputError as error:
            raise ValueError(str(error)) from error
        if not source.is_file() or render_ref.get("sha256") != sha256_file(source):
            raise ValueError("PBM-06 renderer asset is missing or stale")
        atomic_replace_file(source, destination)
        if sha256_file(destination) != render_ref.get("sha256"):
            raise ValueError("PBM-06 HTTP renderer asset copy is stale")


def _mutated_bindings(event: Mapping[str, Any], case_name: str) -> dict[str, Any]:
    bindings = json.loads(json.dumps(event.get("bindings") or {}))
    recipe_id = str(event.get("recipeId") or "")
    key = {
        "PBM-02": "subjectBinding", "PBM-03": "gestureBinding",
        "PBM-05": "subjectBinding", "PBM-07": "chapterBoundaryBinding",
    }.get(recipe_id)
    if case_name == "missing":
        return {}
    if case_name == "wrong_kind" and key:
        bindings[key]["kind"] = "transcript_word"
    if case_name == "stale_hash":
        if recipe_id == "PBM-06":
            bindings["assetRef"]["sha256"] = "0" * 64
        elif key:
            bindings[key]["authority_sha256"] = "0" * 64
    if case_name == "out_of_window" and key:
        bindings[key]["window"] = {"start_seconds": 999, "end_seconds": 1000}
    return bindings


def _unverified_payload(
    output_dir: Path, html_path: Path, *, errors: list[str] | None = None,
    renderer_payload_path: Path | None = None,
) -> dict[str, Any]:
    payload = {
        "schema_version": 2,
        "status": "unverified",
        "capture_tool": {"path": str(CAPTURE_TOOL), "sha256": sha256_file(CAPTURE_TOOL)},
        **({"runtime_engine": {
            "path": str((output_dir / "assets" / "gsap.min.js").resolve()),
            "sha256": sha256_file(output_dir / "assets" / "gsap.min.js"),
        }} if (output_dir / "assets" / "gsap.min.js").is_file() else {}),
        "fixture": {"path": str(html_path), "sha256": sha256_file(html_path)},
        **({"renderer_payload": {
            "path": str(renderer_payload_path.resolve()),
            "sha256": sha256_file(renderer_payload_path),
        }} if renderer_payload_path is not None and renderer_payload_path.is_file() else {}),
        "component_assets": [
            {"path": str((output_dir / source.name).resolve()), "sha256": sha256_file(output_dir / source.name)}
            for source in (PORTRAIT_COMPONENT_JS, PORTRAIT_COMPONENT_CSS)
        ],
        "recipes": [],
        "errors": errors or ["GSAP runtime is required to verify seek-safe portrait components"],
        "claims": {
            "hyperframes_final_render": False,
            "style_reel": False,
            "synthetic_browser_fixture_only": True,
            "hyperframes_timeline_registered": False,
            "seek_safety_verified": False,
        },
    }
    write_json(output_dir / "runtime-evidence.json", payload)
    return payload


def capture(
    output_dir: Path, *, browser_path: Path | None = None,
    hyperframes_gsap: Path | None = None,
    renderer_payload_path: Path | None = None,
) -> dict[str, Any]:
    output_dir = Path(os.path.abspath(output_dir))
    output_dir.mkdir(parents=True, exist_ok=True)
    try:
        for source in (PORTRAIT_COMPONENT_JS, PORTRAIT_COMPONENT_CSS):
            atomic_replace_file(source, safe_generated_target(output_dir, Path(source.name)))
    except SafeGeneratedOutputError as error:
        raise ValueError(str(error)) from error
    if hyperframes_gsap is not None:
        hyperframes_gsap = hyperframes_gsap.resolve()
        if not hyperframes_gsap.is_file():
            raise FileNotFoundError(f"GSAP runtime is missing: {hyperframes_gsap}")
        try:
            assets = safe_generated_directory(output_dir, Path("assets"))
            atomic_replace_file(
                hyperframes_gsap, safe_generated_target(output_dir, Path("assets/gsap.min.js")),
            )
        except SafeGeneratedOutputError as error:
            raise ValueError(str(error)) from error
    renderer_payload: Mapping[str, Any] | None = None
    if renderer_payload_path is not None:
        renderer_payload_path = renderer_payload_path.resolve()
        if not renderer_payload_path.is_file():
            raise FileNotFoundError(f"portrait renderer payload is missing: {renderer_payload_path}")
        loaded_payload = json.loads(renderer_payload_path.read_text(encoding="utf-8"))
        payload_errors = _renderer_payload_errors(loaded_payload)
        if payload_errors:
            raise ValueError("; ".join(payload_errors))
        renderer_payload = loaded_payload
        _materialize_http_assets(output_dir, renderer_payload)
    try:
        html_path = safe_generated_target(output_dir, Path("index.html"))
    except SafeGeneratedOutputError as error:
        raise ValueError(str(error)) from error
    atomic_write_text(html_path, _fixture_html(
        timeline_enabled=hyperframes_gsap is not None,
        renderer_payload=renderer_payload,
    ))
    if hyperframes_gsap is None:
        return _unverified_payload(
            output_dir, html_path, renderer_payload_path=renderer_payload_path,
        )
    if renderer_payload is None or renderer_payload_path is None:
        return _unverified_payload(
            output_dir, html_path,
            errors=["A current compiler renderer payload is required for GSAP runtime verification"],
        )

    from playwright.sync_api import sync_playwright

    registry = load_portrait_recipe_registry()
    evidence: list[dict[str, Any]] = []
    with sync_playwright() as playwright, _serve_directory(output_dir) as base_url:
        launch: dict[str, Any] = {"headless": True, "args": ["--allow-file-access-from-files"]}
        resolved_browser = resolve_browser_executable(browser_path, playwright.chromium.executable_path)
        if resolved_browser is not None:
            launch["executable_path"] = str(resolved_browser)
        browser = playwright.chromium.launch(**launch)
        try:
            page = browser.new_page(viewport={"width": 540, "height": 960})
            page.goto(f"{base_url}/index.html", wait_until="domcontentloaded")
            page.wait_for_function("() => window.fixtureReady === true && window.fixtureTimelineReady === true")
            page.wait_for_function("() => [...document.images].every(image => image.complete && image.naturalWidth > 0)")
            required_binding_errors = page.evaluate("() => window.fixtureRequiredBindingErrors")
            recipes_by_id = {str(row["recipe_id"]): row for row in registry["recipes"]}
            for event_index, payload_event in enumerate(renderer_payload["events"]):
                recipe_id = str(payload_event["recipeId"])
                recipe = recipes_by_id[recipe_id]
                event_id = str(payload_event["eventId"])
                phase_rows = []
                hold_hash = None
                for phase in PHASES:
                    visible_copy = page.evaluate(
                        "([recipe,time]) => window.fixtureSeek(recipe,time)",
                        [event_id, PHASE_TIMES[phase]],
                    )
                    measurement = page.evaluate("""([eventId,phase]) => {
                      const canvas=document.getElementById('composition').getBoundingClientRect();
                      const event=document.getElementById(eventId); const primary=event.querySelector('[data-pbm-primary]');
                      const painted=[...event.querySelectorAll('.pbm-copy,.pbm-primitive,.pbm-focus-beam,.pbm-subject-depth,.pbm-relation-axis,.pbm-camera-frame,.pbm-semantic-asset,.pbm-chapter-bridge-line,.pbm-resolution-bloom')].map(n=>n.getBoundingClientRect()).filter(r=>r.width>0&&r.height>0);
                      const union=painted.length?{left:Math.min(...painted.map(r=>r.left)),top:Math.min(...painted.map(r=>r.top)),right:Math.max(...painted.map(r=>r.right)),bottom:Math.max(...painted.map(r=>r.bottom))}:{left:canvas.left,top:canvas.top,right:canvas.left,bottom:canvas.top};
                      const box=primary.getBoundingClientRect(); const source=document.getElementById('source-media');
                      const semanticAsset=event.querySelector('.pbm-semantic-asset');
                      return {phase,event_phase:event.dataset.phase,recipe:event.dataset.portraitRecipeId,opacity:Number(getComputedStyle(event).opacity),primary_bbox:{x:box.x,y:box.y,width:box.width,height:box.height},painted_bbox:{x:union.left,y:union.top,width:union.right-union.left,height:union.bottom-union.top},inside_canvas:union.left>=canvas.left-0.5&&union.top>=canvas.top-0.5&&union.right<=canvas.right+0.5&&union.bottom<=canvas.bottom+0.5,caption_clear:union.bottom<=canvas.top+canvas.height*.80,recipe_specific:{gesture_points:event.querySelector('.pbm-gesture-path')?.dataset.gesturePointCount||null,semantic_asset_hash:semanticAsset?.dataset.assetSha256||null,semantic_asset_loaded:semanticAsset?semanticAsset.complete&&semanticAsset.naturalWidth>0:null,semantic_asset_protocol:semanticAsset?new URL(semanticAsset.currentSrc).protocol:null,semantic_asset_current_src:semanticAsset?.currentSrc||null,subject_evidence:event.dataset.subjectEvidenceId||null,chapter_boundary:event.dataset.chapterBoundaryEvidenceId||null,source_camera_active:source.dataset.pbmCameraActive}};
                    }""", [event_id, phase])
                    screenshot = output_dir / f"{event_index:03d}-{recipe_id}-{phase}.png"
                    page.locator("#composition").screenshot(path=str(screenshot))
                    phase_rows.append({**measurement, "visible_copy": visible_copy, "snapshot": {"path": str(screenshot), "sha256": sha256_file(screenshot)}})
                    if phase == "hold":
                        hold_hash = sha256_file(screenshot)
                for phase in ("post_exit", "entrance", "hold"):
                    page.evaluate("([eventId,time]) => window.fixtureSeek(eventId,time)", [event_id, PHASE_TIMES[phase]])
                repeated = output_dir / f"{event_index:03d}-{recipe_id}-hold-repeat.png"
                page.locator("#composition").screenshot(path=str(repeated))
                hold_snapshot = output_dir / f"{event_index:03d}-{recipe_id}-hold.png"
                repeat_mae = _image_mae(hold_snapshot, repeated)
                evidence.append({
                    "event_id": event_id,
                    "recipe_id": recipe_id,
                    "fingerprints": recipe_fingerprint(recipe),
                    "phases": phase_rows,
                    "seek_sequence": list(SEEK_SEQUENCE),
                    "seek_repeat_snapshot": {
                        "path": str(repeated.resolve()), "sha256": sha256_file(repeated),
                    },
                    "seek_repeat_hold_sha256": sha256_file(repeated),
                    "seek_repeat_reference_sha256": hold_hash,
                    "seek_repeat_mae": repeat_mae,
                    "seek_repeat_matches": repeat_mae <= 1.5,
                })
        finally:
            browser.close()

    errors: list[str] = []
    if any(not row.get("rejected") for row in required_binding_errors):
        errors.append("one or more recipes accepted missing required runtime bindings")
    for row in evidence:
        phases = {phase["phase"]: phase for phase in row["phases"]}
        for phase in row["phases"]:
            if phase["event_phase"] != phase["phase"]:
                errors.append(f"{row['recipe_id']} phase drift")
            if not phase["inside_canvas"]:
                errors.append(f"{row['recipe_id']} {phase['phase']} leaves canvas")
            if phase["phase"] != "post_exit" and not phase["caption_clear"]:
                errors.append(f"{row['recipe_id']} {phase['phase']} enters caption lane")
            if phase["phase"] == "post_exit" and phase["opacity"] != 0:
                errors.append(f"{row['recipe_id']} post-exit is not clean")
        if not row["seek_repeat_matches"]:
            errors.append(f"{row['recipe_id']} timeline seek is not deterministic")
        semantics = phases["hold"]["recipe_specific"]
        expected_event = next(
            item for item in renderer_payload["events"]
            if item["eventId"] == row["event_id"]
        )
        if row["recipe_id"] == "PBM-03":
            expected_points = len(
                expected_event["bindings"]["gestureBinding"]["points"]
            )
            if semantics["gesture_points"] != str(expected_points):
                errors.append("PBM-03 did not consume compiler-bound gesture geometry")
        if row["recipe_id"] == "PBM-05" and semantics["source_camera_active"] != "true":
            errors.append("PBM-05 did not transform the bound source target")
        if row["recipe_id"] == "PBM-06" and semantics["semantic_asset_hash"] != (
            expected_event["bindings"]["assetRef"]["sha256"]
        ):
            errors.append("PBM-06 did not render the provenance-bound asset")
        if row["recipe_id"] == "PBM-07" and not semantics["chapter_boundary"]:
            errors.append("PBM-07 did not consume chapter-boundary evidence")

    payload = {
        "schema_version": 2,
        "status": "pass" if not errors else "failed",
        "capture_tool": {"path": str(CAPTURE_TOOL), "sha256": sha256_file(CAPTURE_TOOL)},
        "runtime_engine": {
            "path": str((output_dir / "assets" / "gsap.min.js").resolve()),
            "sha256": sha256_file(output_dir / "assets" / "gsap.min.js"),
        },
        "renderer_payload": {
            "path": str(renderer_payload_path),
            "sha256": sha256_file(renderer_payload_path),
        },
        "fixture": {"path": str(html_path), "sha256": sha256_file(html_path)},
        "component_assets": [
            {"path": str((output_dir / source.name).resolve()), "sha256": sha256_file(output_dir / source.name)}
            for source in (PORTRAIT_COMPONENT_JS, PORTRAIT_COMPONENT_CSS)
        ],
        "recipes": evidence,
        "required_binding_negative_checks": required_binding_errors,
        "errors": errors,
        "claims": {
            "hyperframes_final_render": False,
            "style_reel": False,
            "synthetic_browser_fixture_only": True,
            "hyperframes_timeline_registered": True,
            "seek_safety_verified": not errors,
            "required_recipe_bindings_fail_closed": not any(
                not row.get("rejected") for row in required_binding_errors
            ),
            "compiler_renderer_payload_consumed": True,
        },
    }
    validation_errors = validate_portrait_runtime_evidence(payload, renderer_payload_path)
    if validation_errors:
        payload["status"] = "failed"
        payload["errors"] = list(dict.fromkeys([*payload["errors"], *validation_errors]))
    write_json(output_dir / "runtime-evidence.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--browser", type=Path)
    parser.add_argument("--hyperframes-gsap", type=Path)
    parser.add_argument("--renderer-payload", type=Path)
    args = parser.parse_args()
    result = capture(
        args.out, browser_path=args.browser, hyperframes_gsap=args.hyperframes_gsap,
        renderer_payload_path=args.renderer_payload,
    )
    print(json.dumps({"status": result["status"], "errors": result["errors"]}, ensure_ascii=False))
    return 0 if result["status"] == "pass" else 1


if __name__ == "__main__":
    raise SystemExit(main())
