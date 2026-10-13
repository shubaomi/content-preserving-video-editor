"""Opt-in, browser-produced GSAP evidence; never substitutes fabricated CLI output."""
from __future__ import annotations

import importlib.metadata
import math
from pathlib import Path
from typing import Any, Mapping

from director_contracts import read_json, sha256_file, write_json
from renderer_project_manifest import validate_manifest

PHASES = ("entrance", "mid", "pre_exit", "post_exit")
DYNAMIC = {"opacity", "autoAlpha", "visibility", "x", "y", "xPercent", "yPercent",
           "scale", "scaleX", "scaleY", "rotation", "rotationX", "rotationY", "width",
           "height", "left", "top", "clipPath", "filter", "backgroundColor", "color",
           "strokeDashoffset", "strokeDasharray", "attr", "transform"}
PROPERTY_FIELDS = {
    "opacity": ("opacity",), "autoAlpha": ("opacity", "visibility"),
    "visibility": ("visibility",), "x": ("x", "transform"), "y": ("y", "transform"),
    "xPercent": ("x", "transform"), "yPercent": ("y", "transform"),
    "scale": ("width", "height", "transform"), "scaleX": ("width", "transform"),
    "scaleY": ("height", "transform"), "rotation": ("transform",),
    "rotationX": ("transform",), "rotationY": ("transform",),
    "width": ("width",), "height": ("height",), "left": ("x",), "top": ("y",),
    "clipPath": ("clipPath",), "filter": ("filter",), "backgroundColor": ("backgroundColor",),
    "color": ("color",), "strokeDashoffset": ("strokeDashoffset",),
    "strokeDasharray": ("strokeDasharray",), "transform": ("transform",),
}


def _finite(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def _visual_value_valid(field: str, value: Any) -> bool:
    if field in {"x", "y", "width", "height"}:
        return _finite(value)
    if field == "opacity":
        try:
            return not isinstance(value, bool) and math.isfinite(float(value)) and 0 <= float(value) <= 1
        except (ValueError, TypeError):
            return False
    return isinstance(value, str) and bool(value) and not any(token in value.lower() for token in ("nan", "infinity"))


def global_interval(duration: float, chain: list[dict[str, Any]]) -> tuple[float, float]:
    """Transform local tween time through each parent, excluding composition root."""
    if not _finite(duration) or duration <= 0 or not chain:
        raise ValueError("positive duration and parent chain required")
    start, end = 0.0, float(duration)
    for node in chain:
        offset, scale = node.get("start"), node.get("time_scale")
        if not _finite(offset) or not _finite(scale) or scale <= 0:
            raise ValueError("unsupported parent start/timeScale")
        start, end = offset + start / scale, offset + end / scale
    return start, end


def validate_runtime_tree(tweens: list[dict[str, Any]], events: Mapping[str, Any],
                          probes: list[dict[str, Any]]) -> list[str]:
    errors: list[str] = []
    covered: set[str] = set()
    if not tweens:
        return ["runtime animation tree is empty"]
    ids = [row.get("id") for row in tweens]
    if len(set(ids)) != len(ids):
        errors.append("duplicate runtime tween IDs")
    for tween in tweens:
        ident, event = tween.get("id"), tween.get("event_id")
        if event not in events:
            errors.append(f"{ident}: unowned or unknown event")
            continue
        selectors = tween.get("targets")
        if not isinstance(selectors, list) or not selectors or any(not isinstance(s, str) or not s.startswith("#") for s in selectors):
            errors.append(f"{ident}: missing DOM targets")
            continue
        if tween.get("target_ownership") != [event] * len(selectors):
            errors.append(f"{ident}: target ownership mismatch")
        properties = set(tween.get("properties") or []).intersection(PROPERTY_FIELDS)
        if not properties:
            errors.append(f"{ident}: no supported dynamic properties")
        try:
            start, end = global_interval(tween.get("duration"), tween.get("chain"))
        except (ValueError, TypeError, AttributeError):
            errors.append(f"{ident}: invalid nested timing")
            continue
        if any(not _finite(tween.get(key)) or abs(tween[key] - expected) > 1e-6
               for key, expected in (("start", start), ("end", end), ("gsap_start", start), ("gsap_end", end))):
            errors.append(f"{ident}: global interval differs from parent transform or GSAP")
        window = events[event]
        left, right = max(start, window["start_seconds"]), min(end, window["end_seconds"])
        if right <= left:
            errors.append(f"{ident}: tween does not overlap event window")
            continue
        samples = [p for p in probes if p.get("tween_id") == ident]
        by_direction = {direction: sorted((p for p in samples if p.get("direction") == direction), key=lambda p: p.get("time", -1))
                        for direction in ("forward", "reverse")}
        forward, reverse = by_direction["forward"], by_direction["reverse"]
        if len(forward) != 2 or len(reverse) != 2:
            errors.append(f"{ident}: requires two forward and reverse dynamic probes")
            continue
        expected_times = (left + (right-left)*.2, left + (right-left)*.8)
        for f, r, expected_time in zip(forward, reverse, expected_times):
            if not _finite(f.get("time")) or not left <= f["time"] <= right or f.get("time") != r.get("time") or f.get("targets") != r.get("targets"):
                errors.append(f"{ident}: probe window or reverse-seek mismatch")
            if not _finite(f.get("time")) or abs(f["time"]-expected_time) > 1e-7:
                errors.append(f"{ident}: challenge time differs from 20/80 percent interval")
            for probe in (f, r):
                targets = probe.get("targets") or []
                if [t.get("selector") for t in targets] != selectors or any(t.get("owner") != event for t in targets):
                    errors.append(f"{ident}: probe target missing or unowned")
        changed = False
        for before, after in zip(forward[0].get("targets") or [], forward[1].get("targets") or []):
            first, last = before.get("state") or {}, after.get("state") or {}
            for prop in properties:
                fields = PROPERTY_FIELDS[prop]
                if any(not _visual_value_valid(field, state.get(field)) for state in (first, last) for field in fields):
                    errors.append(f"{ident}: invalid measured visual property")
                    continue
                # Only the tween's declared visual channels may establish motion.
                if any(first[field] != last[field] for field in fields):
                    changed = True
        if not changed:
            errors.append(f"{ident}: no observed dynamic change; static list rejected")
        else:
            covered.add(event)
    for event in events.keys() - covered:
        errors.append(f"{event}: no observed dynamic interval")
    return errors


COLLECT_TREE = r"""({eventIds}) => {
 const composition=document.querySelector('[data-composition-id]');
 const root=window.__timelines?.[composition?.dataset.compositionId];
 if(!root || !window.gsap)throw Error('GSAP composition not registered');
 const owners=eventIds.map(id=>{const candidates=[...new Set([document.getElementById(id),
   ...[...document.querySelectorAll('[data-semantic-event-id]')].filter(el=>el.dataset.semanticEventId===id)].filter(Boolean))];
   if(candidates.length!==1)throw Error('event root missing or ambiguous: '+id);return {id,el:candidates[0]};});
 const owner=el=>owners.find(o=>o.el===el||o.el.contains(el))?.id||null;
 const selector=el=>{if(!(el instanceof Element))throw Error('non-DOM animation target');
   const parts=[];let n=el;while(n){if(n.id){parts.unshift('#'+CSS.escape(n.id));break;}
   const peers=[...n.parentElement.children].filter(x=>x.tagName===n.tagName);
   parts.unshift(n.tagName.toLowerCase()+':nth-of-type('+(peers.indexOf(n)+1)+')');n=n.parentElement;}
   const s=parts.join(' > ');if(document.querySelectorAll(s).length!==1)throw Error('non-unique selector');return s;};
 const rows=[],ignored=[];
 root.getChildren(true,true,false).forEach((t,index)=>{
   if(t.duration()<=0)return;
   const targets=t.targets(),owned=targets.map(owner);
   if(!owned.some(Boolean)){ignored.push({id:'t'+index,reason:'unowned_global_tween'});return;}
   if(owned.some(x=>x!==owned[0]))throw Error('mixed ownership tween');
   const chain=[];let n=t;
   while(n!==root){if(!n||n.repeat()!==0||n.yoyo()||n.reversed()||n.paused())throw Error('unsupported repeated/reversed/paused parent');
     chain.push({start:n.startTime(),time_scale:n.timeScale()});n=n.parent;}
   const map=local=>chain.reduce((v,c)=>c.start+v/c.time_scale,local);
   rows.push({id:'t'+index,event_id:owned[0],targets:targets.map(selector),target_ownership:owned,
     duration:t.duration(),chain,start:map(0),end:map(t.duration()),
     gsap_start:(t.globalTime(0)-root.globalTime(0))*root.timeScale(),
     gsap_end:(t.globalTime(t.duration())-root.globalTime(0))*root.timeScale(),properties:Object.keys(t.vars)});
 });
 return {tweens:rows,ignored,event_roots:owners.map(o=>({event_id:o.id,selector:selector(o.el)})),gsap_version:gsap.version,composition_id:composition.dataset.compositionId,
   width:Number(composition.dataset.width),height:Number(composition.dataset.height)};
}"""

SEEK_AND_MEASURE = r"""async ({time,targets,eventIds}) => {
 const root=document.querySelector('[data-composition-id]');
 const owners=eventIds.map(id=>{const candidates=[...new Set([document.getElementById(id),
   ...[...document.querySelectorAll('[data-semantic-event-id]')].filter(el=>el.dataset.semanticEventId===id)].filter(Boolean))];
   if(candidates.length!==1)throw Error('event root missing or ambiguous: '+id);return {id,el:candidates[0]};});
 window.__timelines[root.dataset.compositionId].pause().seek(time,false);
 const media=[];
 for(const video of document.querySelectorAll('video')){
   const start=Number(video.dataset.start||0),duration=Number(video.dataset.duration||0);
   const active=time>=start && time<start+duration;
   if(!active)continue;
   if(!video.readyState){await new Promise((ok,bad)=>{
     const cleanup=()=>{clearTimeout(timer);video.removeEventListener('loadedmetadata',loaded);video.removeEventListener('error',failed);};
     const loaded=()=>{cleanup();ok();},failed=()=>{cleanup();bad(Error('media metadata failed'));};
     const timer=setTimeout(()=>{cleanup();bad(Error('media metadata timeout'));},10000);
     video.addEventListener('loadedmetadata',loaded,{once:true});video.addEventListener('error',failed,{once:true});video.load();});}
   const desired=Number(video.dataset.mediaStart||0)+time-start+0.00001;
   video.pause();video.currentTime=desired;
   await new Promise((ok,bad)=>{const begin=performance.now();const poll=()=>{
     if(!video.seeking&&video.readyState>=2&&Math.abs(video.currentTime-desired)<0.0001)ok();
     else if(performance.now()-begin>10000)bad(Error('media seek failed'));else setTimeout(poll,10);};poll();});
   media.push({id:video.id,desired,current_time:video.currentTime});
 }
 await new Promise(ok=>requestAnimationFrame(()=>requestAnimationFrame(ok)));
 const observed=targets.map(selector=>{const all=document.querySelectorAll(selector);if(all.length!==1)throw Error('target missing/non-unique');
   const el=all[0],r=el.getBoundingClientRect(),s=getComputedStyle(el);
   const owner=owners.find(o=>o.el===el||o.el.contains(el))?.id||null;
   return {selector,owner,state:{x:r.x,y:r.y,width:r.width,height:r.height,opacity:s.opacity,visibility:s.visibility,
     display:s.display,transform:s.transform,clipPath:s.clipPath,filter:s.filter,color:s.color,backgroundColor:s.backgroundColor,
     strokeDashoffset:s.strokeDashoffset,strokeDasharray:s.strokeDasharray,attributes:[...el.attributes].filter(a=>a.name!=='style').map(a=>[a.name,a.value])}};});
 return {targets:observed,media};
}"""


def _artifact(path: Path) -> dict[str, str]:
    return {"path": str(path.resolve()), "sha256": sha256_file(path)}


def _check_artifact(ref: Any, expected: Path | None = None) -> bool:
    if not isinstance(ref, dict):
        return False
    path = Path(str(ref.get("path") or ""))
    return path.is_absolute() and path.is_file() and (expected is None or path.resolve() == expected.resolve()) and ref.get("sha256") == sha256_file(path)


def runtime_event_coverage(evidence: Mapping[str, Any]) -> dict[str, list[str]]:
    result: dict[str, list[str]] = {}
    for tween in evidence.get("tweens") or []:
        result.setdefault(tween["event_id"], []).append(tween["id"])
    return result


def validate_runtime_animation_evidence(evidence: Mapping[str, Any], *, project_artifact: Path,
                                        motion_contract_path: Path, renderer_export_path: Path) -> list[str]:
    errors: list[str] = []
    if evidence.get("schema_version") != 1 or evidence.get("kind") != "runtime_gsap_animation_map" or evidence.get("producer") != "playwright_live_gsap_collector":
        errors.append("not a runtime collector evidence source")
    for name, path in (("project_artifact", project_artifact), ("motion_contract", motion_contract_path),
                       ("renderer_export", renderer_export_path), ("collector", Path(__file__))):
        if not _check_artifact(evidence.get(name), path):
            errors.append(f"stale or missing {name}")
    if errors:
        return errors
    errors.extend(validate_manifest(read_json(project_artifact), project_artifact))
    browser = evidence.get("browser") or {}
    if not _check_artifact(browser.get("executable")) or not browser.get("version") or not evidence.get("playwright_version") or not evidence.get("gsap_version"):
        errors.append("missing actual browser/tool identity")
    contract, export = read_json(motion_contract_path), read_json(renderer_export_path)
    events = {o["semantic_event_id"]: o["output_window"] for o in contract["opportunities"] if o.get("decision") == "render"}
    if export.get("project_artifact") != evidence["project_artifact"] or export.get("motion_design_contract_sha256") != evidence["motion_contract"]["sha256"]:
        errors.append("renderer export input binding is stale")
    if [e.get("event_id") for e in export.get("events") or []] != list(events):
        errors.append("renderer export event inventory mismatch")
    errors.extend(validate_runtime_tree(evidence.get("tweens") or [], events, evidence.get("probes") or []))
    rows = evidence.get("phase_observations") or []
    if len(rows) != len(events) * 8:
        errors.append("four-phase observations contain missing or extra rows")
    for event in export.get("events") or []:
        if [p.get("phase") for p in event.get("phases") or []] != list(PHASES):
            errors.append("renderer export phase order mismatch")
        for phase in event["phases"]:
            matches = [r for r in rows if r.get("event_id") == event["event_id"] and r.get("phase") == phase["phase"]]
            if len(matches) != 2 or {r.get("direction") for r in matches} != {"forward", "reverse"}:
                errors.append("missing forward/reverse four-phase correspondence")
                continue
            for row in matches:
                if row.get("timestamp_seconds") != phase["timestamp_seconds"] or row.get("export_snapshot") != phase["snapshot"] or not _check_artifact(row.get("export_snapshot")) or not _check_artifact(row.get("snapshot")):
                    errors.append("stale or mismatched four-phase snapshot")
                expected_targets = sorted({s for t in evidence.get("tweens") or [] if t.get("event_id") == event["event_id"] for s in t.get("targets") or []})
                if not expected_targets or [t.get("selector") for t in row.get("targets") or []] != expected_targets or any(t.get("owner") != event["event_id"] for t in row.get("targets") or []):
                    errors.append("four-phase DOM target ownership mismatch")
            if matches[0].get("targets") != matches[1].get("targets"):
                errors.append("four-phase reverse seek mismatch")
    return errors


def capture_runtime_animation_evidence(*, project_root: Path, project_artifact: Path,
                                       motion_contract_path: Path, renderer_export_path: Path,
                                       browser_path: Path, output_path: Path) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    initial = {name: _artifact(path) for name, path in (("project_artifact", project_artifact),
        ("motion_contract", motion_contract_path), ("renderer_export", renderer_export_path), ("collector", Path(__file__)))}
    errors = validate_manifest(read_json(project_artifact), project_artifact)
    if errors:
        raise ValueError("; ".join(errors))
    contract, export = read_json(motion_contract_path), read_json(renderer_export_path)
    if Path(read_json(project_artifact)["project_root"]).resolve() != project_root.resolve():
        raise ValueError("project root differs from current manifest")
    events = {o["semantic_event_id"]: o["output_window"] for o in contract["opportunities"] if o.get("decision") == "render"}
    if set(events) != {e["event_id"] for e in export["events"]}:
        raise ValueError("export event inventory differs from motion contract")
    snapshots = output_path.parent / (output_path.stem + "-snapshots")
    snapshots.mkdir(parents=True, exist_ok=True)
    probes, phases = [], []
    with sync_playwright() as p:
        browser = p.chromium.launch(executable_path=str(browser_path), headless=True, args=["--allow-file-access-from-files"])
        try:
            page = browser.new_page()
            page.goto((project_root / "index.html").resolve().as_uri(), wait_until="domcontentloaded")
            page.wait_for_function("Boolean(window.gsap && window.__timelines)")
            tree = page.evaluate(COLLECT_TREE, {"eventIds": list(events)})
            page.set_viewport_size({"width": tree["width"], "height": tree["height"]})
            jobs = []
            for tween in tree["tweens"]:
                window = events[tween["event_id"]]
                start, end = max(tween["start"], window["start_seconds"]), min(tween["end"], window["end_seconds"])
                if end <= start:
                    raise ValueError("runtime tween is outside its owner window")
                for ratio in (.2, .8):
                    jobs.append({"tween_id": tween["id"], "time": start+(end-start)*ratio, "targets": tween["targets"]})
            phase_jobs = []
            for event in export["events"]:
                if [p["phase"] for p in event["phases"]] != list(PHASES):
                    raise ValueError("invalid four phase order")
                selectors = sorted({s for t in tree["tweens"] if t["event_id"] == event["event_id"] for s in t["targets"]})
                for phase in event["phases"]:
                    phase_jobs.append({"event_id": event["event_id"], "phase": phase["phase"], "time": phase["timestamp_seconds"],
                                       "targets": selectors, "export_snapshot": phase["snapshot"]})
            for direction, reverse in (("forward", False), ("reverse", True)):
                for job in sorted(jobs + phase_jobs, key=lambda j: j["time"], reverse=reverse):
                    observed = page.evaluate(SEEK_AND_MEASURE, {"time":job["time"], "targets":job["targets"], "eventIds":list(events)})
                    if "tween_id" in job:
                        probes.append({"tween_id":job["tween_id"],"time":job["time"],"direction":direction,**observed})
                    else:
                        path = snapshots / f"{len(phases):03d}-{direction}-{job['phase']}.png"
                        page.screenshot(path=str(path))
                        phases.append({"event_id":job["event_id"],"phase":job["phase"],"timestamp_seconds":job["time"],
                                       "direction":direction,"export_snapshot":job["export_snapshot"],"snapshot":_artifact(path),**observed})
            evidence = {"schema_version":1,"kind":"runtime_gsap_animation_map","producer":"playwright_live_gsap_collector",**initial,
                "browser":{"executable":_artifact(browser_path),"version":browser.version},
                "playwright_version":importlib.metadata.version("playwright"),"gsap_version":tree["gsap_version"],
                "composition_id":tree["composition_id"],"tweens":tree["tweens"],"ignored_unowned":tree["ignored"],
                "event_roots":tree["event_roots"],
                "probes":probes,"phase_observations":phases}
        finally:
            browser.close()
    errors = validate_runtime_animation_evidence(evidence, project_artifact=project_artifact,
        motion_contract_path=motion_contract_path, renderer_export_path=renderer_export_path)
    if errors:
        raise ValueError("; ".join(errors))
    write_json(output_path, evidence)
    return evidence
