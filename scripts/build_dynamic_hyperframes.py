#!/usr/bin/env python3
"""Render a plan as an editable HyperFrames overlay composition."""
from __future__ import annotations

import argparse
import html
import json
import re
import shutil
from pathlib import Path

SFX_DURATION = {
    "riser_downlifter": 0.34, "short_whoosh": 0.26, "marker_scratch": 0.26,
    "subtle_glitch": 0.26,
}
SAFE_ZONES = {"top_left", "top_right", "side_left", "side_right", "lower_left", "lower_right"}
RESOLVED_COLLISION_STATUSES = {"clear", "resolved", "approved_safe_zone", "not_applicable"}
RESOLVED_REDUNDANCY_STATUSES = {"clear", "resolved", "complement", "replaced", "demoted", "not_applicable"}
SUPPORTED_VARIANTS = {
    "underline_draw", "count_up", "icon_pop", "icon_path", "cursor_click", "focus_ring", "tooltip_attach",
    "step_rail", "compare_split", "cause_effect_link", "micro_push", "freeze_emphasis",
    "mini_scene_window", "transparent_character_peek", "section_reveal", "soft_wipe",
}
VARIANT_RENDER_CONTRACT = {
    "cursor_click": ("cursor-target", ("scale", "rotation", "ripple")),
    "focus_ring": ("focus-spotlight", ("scale", "ring-pulse")),
    "tooltip_attach": ("tooltip-callout", ("y", "tail-reveal")),
    "compare_split": ("comparison-panel", ("split-reveal", "divider-grow")),
    "cause_effect_link": ("cause-effect-flow", ("node-stagger", "path-draw")),
    "step_rail": ("step-rail", ("step-stagger", "rail-grow")),
    "icon_pop": ("semantic-badge", ("scale", "orbit-pop")),
    "icon_path": ("icon-path", ("x", "path-draw")),
    "section_reveal": ("chapter-slate", ("mask-reveal", "rule-grow")),
    "soft_wipe": ("chapter-ribbon", ("wipe", "accent-slide")),
    "underline_draw": ("kinetic-underline", ("y", "underline-grow")),
    "count_up": ("numeric-hit", ("scale", "number-count")),
}


def display_terms(event: dict, mode: str) -> str:
    """Choose visible copy without rebuilding burned captions in polish mode."""
    anchors = [str(anchor).strip() for anchor in event.get("semantic_anchor", []) if str(anchor).strip()]
    if not anchors:
        return str(event.get("purpose", "key point"))
    if mode != "polish_existing":
        compact = [anchor for anchor in anchors if len(anchor) <= 16]
        return " · ".join(compact[:2]) if compact else str(event.get("purpose", "key point"))
    # Existing captions already carry the sentence. A second overlay must be a
    # genuine keyword, not a shortened clause that reads like duplicate subtitles.
    compact_patterns = (
        r"情绪和感受", r"(?:莆田|战疆|普通话|粤语|英语)?口音", r"AI模型|模型", r"不想敷衍",
        r"工作流", r"关键区别", r"重点", r"步骤", r"结果", r"建议",
    )
    for anchor in reversed(anchors):
        for pattern in compact_patterns:
            match = re.search(pattern, anchor)
            if match:
                return match.group(0)
    for anchor in reversed(anchors):
        fragments = [piece.strip() for piece in re.split(r"[，。！？、；：,.!?;:]", anchor) if piece.strip()]
        for fragment in reversed(fragments):
            fragment = re.sub(r"^(?:还有|而且|或者|就是|现在|其实|然后|我觉得|一个)", "", fragment).strip()
            if 1 <= len(fragment) <= 6:
                return fragment
            if len(fragment) > 6:
                return fragment[-6:].lstrip("的")
    return anchors[-1][-6:].lstrip("的")


def visual_markup(event: dict, index: int, mode: str, ip_asset_url: str | None = None) -> str:
    terms = display_terms(event, mode)
    purpose = html.escape(str(event.get("purpose", "重点")).replace("_", " "))
    family = event["visual_family"]; variant = event["motion_variant"]
    tag = html.escape(terms[:32]); event_id = html.escape(event["id"])
    payload = event.get("visual_payload", {})
    anchors = [html.escape(str(item)) for item in event.get("semantic_anchor", []) if str(item).strip()]
    auxiliary = "<span class=\"motion-accent\"></span>"
    if family == "ip_visual" and not ip_asset_url:
        raise ValueError(f"{event['id']}: an approved IP asset is required; generic placeholders are forbidden")
    if variant == "cursor_click":
        surface = f'<span class="cursor-pointer">↖</span><span class="cursor-target-label">{tag}</span><span class="click-ripple"></span>'
    elif variant == "focus_ring":
        surface = f'<span class="focus-halo"><i></i><b>◎</b></span><strong>{tag}</strong>'
    elif variant == "tooltip_attach":
        surface = f'<span class="tooltip-kicker">TIP</span><strong>{tag}</strong><span class="tooltip-tail" data-layout-allow-overflow="true"></span>'
    elif variant == "compare_split":
        left = html.escape(str(payload.get("left") or (anchors[0] if anchors else "Before")))
        right = html.escape(str(payload.get("right") or (anchors[1] if len(anchors) > 1 else tag)))
        surface = f'<div class="compare-grid"><span class="compare-left">{left}</span><span class="compare-divider">VS</span><span class="compare-right">{right}</span></div>'
    elif variant == "cause_effect_link":
        nodes = [html.escape(str(item)) for item in payload.get("nodes", []) if str(item).strip()] or anchors[:3] or [tag]
        nodes = (nodes + ["结果"] * 3)[:3]
        surface = f'<div class="flow-nodes"><span>{nodes[0]}</span><i>→</i><span>{nodes[1]}</span><i>→</i><span>{nodes[2]}</span></div><svg class="flow-path" viewBox="0 0 300 24"><path d="M4 12H296"/></svg>'
    elif variant == "step_rail":
        steps = [html.escape(str(item)) for item in payload.get("steps", []) if str(item).strip()] or anchors[:3] or [tag]
        surface = '<div class="step-items">' + ''.join(f'<span><b>{n}</b>{item}</span>' for n, item in enumerate(steps[:3], 1)) + '</div><i class="step-line"></i>'
    elif variant == "icon_pop":
        icon = html.escape(str(payload.get("icon", "✦")))
        surface = f'<span class="semantic-orbit"><i></i><b>{icon}</b></span><strong>{tag}</strong>'
    elif variant == "icon_path":
        icon = html.escape(str(payload.get("icon", "✦")))
        surface = f'<svg class="semantic-path" viewBox="0 0 64 64"><path d="M8 48C18 12 44 12 56 32"/><circle cx="56" cy="32" r="5"/></svg><span class="path-icon">{icon}</span><strong>{tag}</strong>'
    elif variant in {"micro_push", "freeze_emphasis"}:
        surface = f'<span class="variant-glyph">⌁</span><strong>{tag}</strong>'
    elif variant in {"mini_scene_window", "transparent_character_peek"}:
        surface = f'<span class="ip-portrait"><img src="{html.escape(ip_asset_url or "", quote=True)}" alt="HongRun IP" /></span><strong>{tag}</strong>'
    elif variant in {"section_reveal", "soft_wipe"}:
        chapter = html.escape(str(payload.get("chapter", index)).zfill(2))
        surface = f'<span class="chapter-index">{chapter}</span><div class="chapter-copy"><small>CHAPTER</small><strong>{tag}</strong><i class="chapter-rule"></i></div>'
    elif variant == "count_up":
        unit = html.escape(str(payload.get("unit", "")))
        surface = f'<span class="count-kicker">DATA</span><strong class="count-value">{tag}</strong><span class="count-unit">{unit}</span>'
    else:
        surface = f'<span class="kinetic-kicker">KEY IDEA</span><strong class="kinetic-word">{tag}</strong><span class="marker"></span>'
    if mode == "polish_existing":
        label = {
            "kinetic_text": "重点",
            "ui_attention": "操作提示",
            "structure": "结构化理解",
            "camera_motion": "画面聚焦",
            "ip_visual": "主题插图",
        }.get(family, "")
    else:
        label = purpose
    label_markup = f"<small>{label}</small>" if label else ""
    safe_zone = event.get("safe_zone") if event.get("safe_zone") in SAFE_ZONES else "top_right"
    return f'''<div id="{event_id}" class="clip attention-event {family} {variant}" data-variant="{html.escape(variant)}" data-start="{event['start']:.3f}" data-duration="{event['duration']:.3f}" data-track-index="{4 + index}">
  <div class="event-host {safe_zone}"><div class="motion-wrapper"><div class="editable-surface family-{family}">{label_markup}{surface}{auxiliary}</div></div></div></div>'''


def sfx_markup(event: dict, index: int) -> str:
    sfx = event.get("sfx", {})
    if not sfx.get("enabled"):
        return ""
    duration = float(sfx.get("duration_seconds", SFX_DURATION.get(str(sfx.get("family")), 1.0)))
    landing = float(sfx.get("landing_offset_seconds", 0.22))
    volume = float(sfx.get("volume", 0.28))
    return f'<audio id="sfx-{index:03d}" class="clip" src="assets/sfx/{sfx["variant"]}" data-start="{event["start"] + landing:.3f}" data-duration="{duration:.2f}" data-track-index="{40 + index}" data-volume="{volume:.2f}"></audio>'


def timeline_event(event: dict, index: int) -> str:
    selector = f"#${event['id']}".replace("#$", "#")
    start = float(event["start"]); duration = float(event["duration"]); variant = event["motion_variant"]
    from_vars, to_vars = {
        "cursor_click": ("{opacity:0,scale:.82,rotation:-4}", "{opacity:1,scale:1,rotation:0,duration:.24,ease:'back.out(1.5)'}"),
        "focus_ring": ("{opacity:0,scale:.9}", "{opacity:1,scale:1,duration:.28,ease:'power2.out'}"),
        "tooltip_attach": ("{opacity:0,y:16}", "{opacity:1,y:0,duration:.3,ease:'power3.out'}"),
        "compare_split": ("{opacity:0,x:-30}", "{opacity:1,x:0,duration:.38,ease:'expo.out'}"),
        "cause_effect_link": ("{opacity:0,y:-18}", "{opacity:1,y:0,duration:.4,ease:'power3.out'}"),
        "step_rail": ("{opacity:0,x:-24}", "{opacity:1,x:0,duration:.34,ease:'power3.out'}"),
        "icon_pop": ("{opacity:0,scale:.55,rotation:-12}", "{opacity:1,scale:1,rotation:0,duration:.34,ease:'back.out(1.7)'}"),
        "icon_path": ("{opacity:0,x:-20}", "{opacity:1,x:0,duration:.36,ease:'sine.out'}"),
        "micro_push": ("{opacity:0,scale:.94}", "{opacity:1,scale:1,duration:.48,ease:'sine.out'}"),
        "freeze_emphasis": ("{opacity:0,filter:'blur(4px)'}", "{opacity:1,filter:'blur(0px)',duration:.36,ease:'power2.out'}"),
        "mini_scene_window": ("{opacity:0,y:22,scale:.86}", "{opacity:1,y:0,scale:1,duration:.46,ease:'back.out(1.2)'}"),
        "transparent_character_peek": ("{opacity:0,x:26}", "{opacity:1,x:0,duration:.42,ease:'power3.out'}"),
        "section_reveal": ("{opacity:0,clipPath:'inset(0 100% 0 0 round 16px)'}", "{opacity:1,clipPath:'inset(0 0% 0 0 round 16px)',duration:.4,ease:'expo.out'}"),
        "soft_wipe": ("{opacity:0,x:-28}", "{opacity:1,x:0,duration:.42,ease:'sine.out'}"),
        "underline_draw": ("{opacity:0,y:16}", "{opacity:1,y:0,duration:.28,ease:'power3.out'}"),
        "count_up": ("{opacity:0,scale:.7}", "{opacity:1,scale:1,duration:.36,ease:'back.out(1.4)'}"),
    }[variant]
    exit_at = start + max(0.72, duration - 0.2)
    detail = ""
    if variant == "cursor_click":
        detail = f"tl.fromTo('{selector} .click-ripple',{{opacity:.6,scale:.4}},{{opacity:0,scale:1.5,duration:.34,ease:'power2.out'}},{start + 0.12:.3f});"
    elif variant == "focus_ring":
        detail = f"tl.fromTo('{selector} .focus-halo i',{{opacity:.5,scale:.55}},{{opacity:0,scale:1.7,duration:.5,ease:'power2.out'}},{start + 0.08:.3f});"
    elif variant == "compare_split":
        detail = f"tl.fromTo('{selector} .compare-divider',{{scaleY:0,opacity:0}},{{scaleY:1,opacity:1,duration:.34,ease:'power2.out'}},{start + 0.12:.3f});"
    elif variant == "cause_effect_link":
        detail = f"tl.from('{selector} .flow-nodes span',{{opacity:0,y:10,duration:.28,stagger:.12,ease:'power2.out'}},{start + 0.08:.3f});tl.fromTo('{selector} .flow-path path',{{strokeDasharray:300,strokeDashoffset:300}},{{strokeDashoffset:0,duration:.55,ease:'power2.inOut'}},{start + 0.12:.3f});"
    elif variant == "step_rail":
        detail = f"tl.from('{selector} .step-items span',{{opacity:0,x:-16,duration:.28,stagger:.1,ease:'power3.out'}},{start + 0.08:.3f});tl.fromTo('{selector} .step-line',{{scaleY:0,transformOrigin:'top'}},{{scaleY:1,duration:.5,ease:'power2.out'}},{start + 0.1:.3f});"
    elif variant == "icon_pop":
        detail = f"tl.fromTo('{selector} .semantic-orbit i',{{opacity:.7,scale:.4}},{{opacity:0,scale:1.55,duration:.48,ease:'power2.out'}},{start + 0.06:.3f});"
    elif variant == "icon_path":
        detail = f"tl.fromTo('{selector} .semantic-path path',{{strokeDasharray:120,strokeDashoffset:120}},{{strokeDashoffset:0,duration:.5,ease:'power2.inOut'}},{start + 0.06:.3f});"
    elif variant in {"section_reveal", "soft_wipe"}:
        detail = f"tl.fromTo('{selector} .chapter-rule',{{scaleX:0,transformOrigin:'left'}},{{scaleX:1,duration:.46,ease:'expo.out'}},{start + 0.12:.3f});"
    elif variant == "underline_draw":
        detail = f"tl.fromTo('{selector} .marker',{{scaleX:0,transformOrigin:'left center'}},{{scaleX:1,duration:.36,ease:'power2.out'}},{start + 0.08:.3f});"
    return f"tl.fromTo('{selector} .motion-wrapper',{from_vars},{to_vars},{start:.3f});{detail}tl.to('{selector} .motion-wrapper',{{opacity:0,scale:.97,duration:.18,ease:'power2.in'}},{exit_at:.3f});tl.set('{selector} .motion-wrapper',{{opacity:0}},{start + duration:.3f});"


def _validate_events(events: list[dict], *, layout_preview: bool) -> None:
    unsupported = [{"id": event.get("id"), "variant": event.get("motion_variant")} for event in events if event.get("motion_variant") not in SUPPORTED_VARIANTS]
    if unsupported:
        raise ValueError(f"unsupported motion variants require a real renderer implementation: {unsupported}")
    contract_mismatches = []
    for event in events:
        contract = event.get("render_contract")
        if not contract:
            continue
        expected = VARIANT_RENDER_CONTRACT.get(event.get("motion_variant"))
        actual = (str(contract.get("markup_family", "")), tuple(str(item) for item in contract.get("animation_signature", [])))
        if expected and actual != expected:
            contract_mismatches.append({"id": event.get("id"), "expected": expected, "actual": actual})
    if contract_mismatches:
        raise ValueError(f"render contract does not match implemented variant: {contract_mismatches}")
    if layout_preview:
        return
    unresolved = []
    for event in events:
        collision = str(event.get("collision_check", {}).get("status", "")).lower()
        redundancy = str(event.get("redundancy_check", {}).get("status", "")).lower()
        if collision not in RESOLVED_COLLISION_STATUSES or redundancy not in RESOLVED_REDUNDANCY_STATUSES or event.get("safe_zone") not in SAFE_ZONES:
            unresolved.append({"id": event.get("id"), "collision": collision or "missing", "redundancy": redundancy or "missing", "safe_zone": event.get("safe_zone", "missing")})
    if unresolved:
        raise ValueError(f"unresolved layout/redundancy blocks render; use layout-preview only for geometry review: {unresolved}")


def build(plan: dict, baseline: Path, composition_id: str, width: int, height: int, mode: str, overlay_only: bool = False,
          matte_color: str | None = None, ip_asset_url: str | None = None, layout_preview: bool = False) -> str:
    duration = float(plan["duration"]); events = plan.get("attention_events", plan.get("events", []))
    _validate_events(events, layout_preview=layout_preview)
    visuals = "\n".join(visual_markup(event, index, mode, ip_asset_url) for index, event in enumerate(events, 1))
    audio = "\n".join(sfx_markup(event, index) for index, event in enumerate(events, 1))
    timeline = "\n".join(timeline_event(event, index) for index, event in enumerate(events, 1))
    portrait = height > width
    base_media = "" if overlay_only else f'<video id="baseline-video" class="clip baseline" src="baseline.mp4" data-start="0" data-duration="{duration:.3f}" data-track-index="0" muted playsinline></video><audio id="baseline-audio" class="clip" src="baseline.mp4" data-start="0" data-duration="{duration:.3f}" data-track-index="1" data-volume="1"></audio>'
    canvas_background = matte_color if overlay_only and matte_color else ("transparent" if overlay_only else "#0f211a")
    return f'''<!doctype html><html lang="zh-CN"><head><meta charset="utf-8"><title>{html.escape(composition_id)}</title></head><body>
<div id="{html.escape(composition_id)}" data-composition-id="{html.escape(composition_id)}" data-start="0" data-duration="{duration:.3f}" data-width="{width}" data-height="{height}">
{base_media}{audio}{visuals}
<style>
@font-face{{font-family:'Microsoft YaHei';src:local('Microsoft YaHei')}}*{{box-sizing:border-box}}html,body{{margin:0;width:100%;height:100%;overflow:hidden;background:{canvas_background};font-family:'Microsoft YaHei',sans-serif}}#{composition_id}{{position:relative;width:{width}px;height:{height}px;overflow:hidden;color:#15382d;background:{canvas_background}}}.baseline{{position:absolute;inset:0;width:{width}px;height:{height}px;object-fit:cover}}.attention-event{{position:absolute;inset:0;z-index:20;overflow:hidden}}.event-host{{position:absolute;width:max-content;max-width:{'520px' if portrait else '460px'};min-height:72px}}.top_left{{top:{'150px' if portrait else '150px'};left:{'42px' if portrait else '58px'}}}.top_right{{top:{'150px' if portrait else '150px'};right:{'42px' if portrait else '58px'}}}.side_left{{top:{'660px' if portrait else '365px'};left:{'42px' if portrait else '58px'}}}.side_right{{top:{'660px' if portrait else '365px'};right:{'42px' if portrait else '58px'}}}.lower_left{{bottom:{'390px' if portrait else '300px'};left:{'42px' if portrait else '58px'}}}.lower_right{{bottom:{'390px' if portrait else '300px'};right:{'42px' if portrait else '58px'}}}.motion-wrapper{{opacity:0;max-width:100%;will-change:transform,opacity}}.editable-surface{{position:relative;display:flex;align-items:center;gap:14px;max-width:100%;min-height:76px;padding:14px 18px;border:2px solid rgba(41,116,86,.25);border-radius:20px;background:rgba(248,253,250,.94);box-shadow:0 12px 28px rgba(8,42,31,.18);backdrop-filter:blur(7px);overflow:hidden}}.editable-surface small{{position:absolute;top:5px;left:14px;color:#4d7467;font-size:12px;font-weight:700;letter-spacing:.04em}}.editable-surface strong{{display:block;padding-top:10px;max-width:360px;font-size:{'28px' if portrait else '27px'};line-height:1.22;letter-spacing:-.025em;overflow-wrap:anywhere}}.motion-accent{{position:absolute;right:16px;bottom:10px;width:42px;height:4px;border-radius:99px;background:#ef9343}}.variant-glyph{{display:grid;place-items:center;flex:0 0 42px;width:42px;height:42px;border-radius:14px;background:#dff5ea;color:#218060;font-size:24px;font-weight:800}}.click-ripple{{position:absolute;left:31px;top:31px;width:24px;height:24px;border:3px solid #35c99a;border-radius:50%}}.tooltip-tail{{position:absolute;left:28px;bottom:-8px;width:16px;height:16px;transform:rotate(45deg);background:rgba(248,253,250,.94);border-right:2px solid rgba(41,116,86,.25);border-bottom:2px solid rgba(41,116,86,.25)}}.marker{{position:absolute;left:18px;bottom:10px;width:58%;height:5px;border-radius:9px;background:#ef9343}}
.family-semantic_icon{{width:max-content;min-height:76px;padding:13px 18px;border-radius:999px;background:rgba(255,255,255,.95);box-shadow:0 10px 24px rgba(8,42,31,.16)}}.family-semantic_icon small,.family-semantic_icon .motion-accent{{display:none}}.family-semantic_icon strong{{font-size:{'25px' if portrait else '24px'}}}.family-ui_attention{{min-height:88px;padding:14px 20px;background:rgba(247,255,251,.72);border-style:dashed;box-shadow:0 10px 22px rgba(8,42,31,.12)}}.family-ui_attention .motion-accent{{display:none}}.family-structure{{border-left:8px solid #35c99a}}.family-chapter_transition{{min-height:84px;padding:13px 22px;border:0;border-radius:16px;background:#173d31;color:#fff;box-shadow:0 13px 25px rgba(8,42,31,.28)}}.family-chapter_transition small{{background:#ef9343;color:#15382d}}.family-chapter_transition .motion-accent{{background:#dff5ea}}.family-camera_motion{{width:max-content;min-height:78px;padding:13px 18px;border-radius:18px;background:rgba(255,250,243,.96)}}.family-camera_motion small,.family-camera_motion .motion-accent{{display:none}}.family-ip_visual{{width:max-content;min-height:82px;padding:12px 18px;border-radius:999px;background:linear-gradient(120deg,#e4f8ee,#f7fff9);border-color:#35c99a}}.family-ip_visual .motion-accent{{display:none}}.ip-portrait{{display:block;position:relative;flex:0 0 54px;width:54px;height:54px;border-radius:50%;overflow:hidden;background:#dff5ea;border:2px solid #35c99a}}.ip-portrait img{{position:absolute;width:300px;max-width:none;height:auto;left:-76px;top:-18px;mix-blend-mode:multiply}}
.cursor_click .editable-surface{{min-width:230px;background:transparent;border:0;box-shadow:none;overflow:visible}}.cursor_click .editable-surface>small{{display:none}}.cursor-pointer{{font-size:44px;color:#173d31;filter:drop-shadow(0 4px 5px rgba(0,0,0,.22))}}.cursor-target-label{{padding:12px 18px;border-radius:14px;background:#fff;border:2px solid #35c99a;font-size:24px;font-weight:800}}.focus_ring .editable-surface{{background:rgba(255,255,255,.82);border:0}}.focus-halo{{position:relative;display:grid;place-items:center;width:54px;height:54px}}.focus-halo i{{position:absolute;inset:0;border:3px solid #35c99a;border-radius:50%}}.focus-halo b{{font-size:30px;color:#218060}}.tooltip_attach .editable-surface{{border-radius:18px;border-left:7px solid #ef9343;overflow:visible}}.tooltip-kicker{{padding:5px 8px;border-radius:7px;background:#ef9343;color:#173d31;font-size:13px;font-weight:900}}.compare_split .editable-surface{{padding:0;border:0;background:transparent;box-shadow:none;overflow:visible}}.compare-grid{{display:grid;grid-template-columns:1fr 52px 1fr;align-items:stretch;min-width:438px;border-radius:20px;overflow:hidden;box-shadow:0 12px 28px rgba(8,42,31,.18)}}.compare-grid>span{{display:grid;place-items:center;min-height:92px;padding:18px;font-size:23px;font-weight:800}}.compare-left{{background:#fff;color:#173d31}}.compare-right{{position:relative;z-index:1;background:#173d31;color:#fff}}.compare-divider{{position:relative;z-index:2;padding:18px 10px!important;background:#ef9343;color:#173d31}}.cause_effect_link .editable-surface{{display:block;min-width:480px;padding:40px 20px 18px}}.cause_effect_link .editable-surface>small,.step_rail .editable-surface>small{{z-index:4}}.flow-nodes{{position:relative;z-index:2;display:flex;align-items:center;justify-content:space-between;gap:8px}}.flow-nodes span{{padding:10px 13px;border-radius:12px;background:#fff;font-size:19px;font-weight:800;box-shadow:0 5px 12px rgba(8,42,31,.1)}}.flow-nodes i{{color:#ef9343;font-size:25px;font-style:normal}}.flow-path{{display:block;width:100%;height:20px;margin-top:6px}}.flow-path path,.semantic-path path{{fill:none;stroke:#35c99a;stroke-width:5;stroke-linecap:round}}.step_rail .editable-surface{{display:block;min-width:360px;padding:40px 20px 18px 36px}}.step-items{{position:relative;z-index:2;display:grid;gap:9px}}.step-items span{{font-size:20px;font-weight:750}}.step-items b{{position:relative;z-index:3;display:inline-grid;place-items:center;width:27px;height:27px;margin-right:10px;border-radius:50%;background:#173d31;color:#fff}}.step-line{{position:absolute;z-index:1;left:48px;top:55px;bottom:28px;width:3px;background:#35c99a}}.icon_pop .editable-surface,.icon_path .editable-surface{{border-radius:999px;min-height:76px}}.semantic-orbit{{position:relative;display:grid;place-items:center;width:50px;height:50px}}.semantic-orbit i{{position:absolute;inset:0;border:3px solid #35c99a;border-radius:50%}}.semantic-orbit b,.path-icon{{font-size:25px;color:#218060}}.semantic-path{{width:60px;height:60px;overflow:visible}}.section_reveal .editable-surface{{min-width:420px;background:#173d31;color:#fff;border:0;border-radius:14px}}.soft_wipe .editable-surface{{min-width:390px;background:#fff;border:0;border-left:12px solid #ef9343;border-radius:3px 18px 18px 3px}}.chapter-index{{font-size:44px;font-weight:900;color:#ef9343;font-variant-numeric:tabular-nums}}.chapter-copy{{display:grid;gap:4px}}.chapter-copy small{{position:static;color:#829378}}.chapter-copy strong{{padding:0;font-size:30px}}.chapter-rule{{display:block;width:180px;height:5px;border-radius:8px;background:#35c99a}}.underline_draw .editable-surface{{display:block;min-width:350px;padding:16px 22px;border:0;background:rgba(255,255,255,.91);box-shadow:0 8px 20px rgba(8,42,31,.14)}}.underline_draw .editable-surface>small{{display:none}}.kinetic-kicker{{display:block;font-size:12px;font-weight:900;letter-spacing:.16em;color:#829378}}.kinetic-word{{padding:0!important;font-size:32px!important}}.count_up .editable-surface{{display:flex;align-items:flex-end;background:#173d31;color:#fff;border:0}}.count-kicker{{font-size:12px;letter-spacing:.15em;color:#ef9343}}.count_up .count-value{{padding:0;font-size:{'50px' if portrait else '44px'};font-variant-numeric:tabular-nums}}.count-unit{{font-size:16px;color:#dff5ea}}.mini_scene_window .family-ip_visual{{border-radius:20px}}.transparent_character_peek .family-ip_visual{{background:transparent;border:0;box-shadow:none}}
</style><script src="assets/gsap.min.js"></script><script>window.__timelines=window.__timelines||{{}};const tl=gsap.timeline({{paused:true}});{timeline}window.__timelines['{composition_id}']=tl;</script></div></body></html>'''


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__); parser.add_argument("--plan", required=True); parser.add_argument("--baseline", required=True); parser.add_argument("--out", required=True); parser.add_argument("--composition-id", required=True); parser.add_argument("--width", type=int, required=True); parser.add_argument("--height", type=int, required=True); parser.add_argument("--mode", choices=("screen_tutorial", "polish_existing"), required=True); parser.add_argument("--overlay-only", action="store_true"); parser.add_argument("--layout-preview", action="store_true", help="Allow unresolved placement only for a non-export geometry review preview."); parser.add_argument("--matte-color", help="Reserved for direct HTML inspection; export a key matte with an opaque key-color baseline video instead."); parser.add_argument("--ip-asset", type=Path, help="Approved personal-IP reference image to mount as a cropped animated component."); args = parser.parse_args()
    if args.overlay_only and args.matte_color:
        parser.error("--overlay-only cannot produce a reliable key matte. Use an opaque key-color baseline video without --overlay-only.")
    plan = json.loads(Path(args.plan).read_text(encoding="utf-8")); baseline = Path(args.baseline)
    if not baseline.is_file(): raise FileNotFoundError(baseline)
    output = Path(args.out); output.parent.mkdir(parents=True, exist_ok=True)
    ip_asset_url = None
    if args.ip_asset:
        if not args.ip_asset.is_file(): raise FileNotFoundError(args.ip_asset)
        target = output.parent / "assets" / "ip" / args.ip_asset.name
        target.parent.mkdir(parents=True, exist_ok=True); shutil.copyfile(args.ip_asset, target)
        ip_asset_url = f"assets/ip/{target.name}"
    output.write_text(build(plan, baseline, args.composition_id, args.width, args.height, args.mode, args.overlay_only, args.matte_color, ip_asset_url, args.layout_preview), encoding="utf-8"); print(output.resolve()); return 0


if __name__ == "__main__": raise SystemExit(main())
