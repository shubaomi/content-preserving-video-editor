#!/usr/bin/env python3
"""Plan quality-bounded semantic attention events without density filler."""

from __future__ import annotations

import math
import re
from typing import Any


MOTION_PROFILES = {
    "calm": {"screen_tutorial": (1.5, 3.0), "polish_existing": (1.0, 2.5)},
    "balanced": {"screen_tutorial": (2.5, 4.5), "polish_existing": (2.0, 3.5)},
    "adaptive_dynamic": {"screen_tutorial": (3.5, 6.0), "polish_existing": (2.5, 4.5)},
}
MIN_SEMANTIC_SCORE = 2.6
ANCHOR_REPEAT_COOLDOWN_SECONDS = 40.0
MAX_EXACT_ANCHOR_OCCURRENCES = 2

CUE_RULES = (
    ("chapter_boundary", ("首先", "接下来", "然后", "最后", "总结", "第一", "第二", "第三", "first", "next", "finally", "summary")),
    ("contrast", ("但是", "而是", "区别", "对比", "不是", "instead", "but", "versus", "difference")),
    ("causality", ("因为", "所以", "导致", "因此", "结果", "because", "therefore", "result")),
    ("ui_action", ("点击", "打开", "添加", "选择", "切换", "输入", "保存", "删除", "刷新", "验证", "click", "open", "add", "select", "switch", "type", "save", "delete", "remove", "refresh", "verify", "validate")),
    ("conclusion", ("关键", "核心", "记住", "建议", "本质", "结论", "important", "key", "recommend", "remember")),
)

LOW_INFORMATION_ANCHORS = {
    "首先", "接下来", "然后", "最后", "总结", "第一", "第二", "第三",
    "点击", "打开", "添加", "选择", "切换", "输入", "保存", "删除", "刷新", "验证",
    "但是", "而是", "因为", "所以", "导致", "因此", "结果", "关键", "核心", "建议",
    "first", "next", "finally", "summary", "click", "open", "add", "select", "switch",
    "type", "save", "delete", "remove", "refresh", "verify", "validate", "because", "therefore",
    "important", "key", "recommend", "remember", "now", "then", "the", "this", "that", "your", "our",
}
ENGLISH_STOPWORDS = LOW_INFORMATION_ANCHORS | {
    "a", "an", "and", "or", "to", "of", "in", "on", "for", "with", "is", "are", "be", "it", "as",
    "from", "into", "by", "we", "you", "i", "can", "will", "just", "really", "than", "difference",
}
DOMAIN_TERMS = (
    "新建标签页", "新标签页", "浏览器插件", "添加列表", "标签页", "工作区", "收藏夹", "常用网址", "网址", "列表", "插件",
    "浏览器", "页面", "数据", "流程", "工作流", "字幕", "动效", "音效", "背景音乐", "封面", "模型",
    "步骤", "方法", "结论", "结果", "问题", "功能", "代码", "TabOut", "GitHub", "GPT Live", "AI",
)
GENERIC_ANCHORS = {
    "插件", "功能", "页面", "浏览器", "网址", "列表", "数据", "流程", "步骤", "方法", "问题", "结果",
    "系统", "工具", "概念", "模块", "请求",
}
CONCRETE_COMPOUNDS = (
    "语言模型", "核心原理", "概念学习", "知识作品", "历史记录", "短视频素材", "小红书文案",
    "客户解释", "请求流程", "请求透视", "核心功能", "测试题", "工作流程", "数据模型",
    "网站小工具", "模拟剧场", "类比故事", "概念分解", "相关概念", "表达素材", "自测问题",
    "一次请求", "完整流程", "原产品",
)
NOUN_SUFFIXES = (
    "模型", "原理", "机制", "概念", "版本", "素材", "文案", "记录", "流程", "请求", "系统",
    "工具", "作品", "模块", "故事", "剧场", "对比", "测试", "学习", "拆解", "方案",
)

FAMILY_BY_PURPOSE = {
    "chapter_boundary": "chapter_transition",
    "contrast": "structure",
    "causality": "structure",
    "ui_action": "ui_attention",
    "conclusion": "kinetic_text",
    "number": "kinetic_text",
    "explanation": "semantic_icon",
}
VARIANT_BY_PURPOSE = {
    "chapter_boundary": "section_reveal",
    "contrast": "compare_split",
    "causality": "cause_effect_link",
    "conclusion": "underline_draw",
    "number": "count_up",
    "explanation": "icon_pop",
}
UI_VARIANT_BY_CUE = {
    "点击": "cursor_click", "click": "cursor_click",
    "打开": "focus_ring", "open": "focus_ring",
    "添加": "tooltip_attach", "add": "tooltip_attach",
    "选择": "focus_ring", "select": "focus_ring",
    "切换": "focus_ring", "switch": "focus_ring",
    "输入": "tooltip_attach", "type": "tooltip_attach",
    "保存": "tooltip_attach", "save": "tooltip_attach",
    "删除": "cursor_click", "delete": "cursor_click", "remove": "cursor_click",
    "刷新": "focus_ring", "refresh": "focus_ring",
    "验证": "tooltip_attach", "verify": "tooltip_attach", "validate": "tooltip_attach",
}
SFX_BY_FAMILY = {
    "kinetic_text": ("text_mark", 1.06),
    "semantic_icon": ("semantic_pluck", 1.14),
    "ui_attention": ("ui_confirm", 0.96),
    "structure": ("structure_sequence", 1.24),
    "chapter_transition": ("chapter_chime", 1.45),
}

RENDER_CONTRACT_BY_VARIANT = {
    "cursor_click": {"markup_family": "cursor-target", "animation_signature": ["scale", "rotation", "ripple"]},
    "focus_ring": {"markup_family": "focus-spotlight", "animation_signature": ["scale", "ring-pulse"]},
    "tooltip_attach": {"markup_family": "tooltip-callout", "animation_signature": ["y", "tail-reveal"]},
    "compare_split": {"markup_family": "comparison-panel", "animation_signature": ["split-reveal", "divider-grow"]},
    "cause_effect_link": {"markup_family": "cause-effect-flow", "animation_signature": ["node-stagger", "path-draw"]},
    "step_rail": {"markup_family": "step-rail", "animation_signature": ["step-stagger", "rail-grow"]},
    "icon_pop": {"markup_family": "semantic-badge", "animation_signature": ["scale", "orbit-pop"]},
    "icon_path": {"markup_family": "icon-path", "animation_signature": ["x", "path-draw"]},
    "section_reveal": {"markup_family": "chapter-slate", "animation_signature": ["mask-reveal", "rule-grow"]},
    "soft_wipe": {"markup_family": "chapter-ribbon", "animation_signature": ["wipe", "accent-slide"]},
    "underline_draw": {"markup_family": "kinetic-underline", "animation_signature": ["y", "underline-grow"]},
    "count_up": {"markup_family": "numeric-hit", "animation_signature": ["scale", "number-count"]},
}


def _midpoint(segment: dict[str, Any]) -> float:
    return (float(segment.get("start", 0)) + float(segment.get("end", 0))) / 2


def _compact(term: str) -> str:
    term = re.sub(r"^[\s，。！？、；：,.!?;:]+|[\s，。！？、；：,.!?;:]+$", "", term)
    term = re.sub(r"^(?:(?:其实|就是|现在|然后|接下来|我们|我|你|他|它|可以|通过|直接|再次|再|这些|那些|一些|一个|这个|那个|某个|还有|下面|另外|的))+", "", term)
    term = re.sub(r"(?:的时候|之后|一下|进行|就可以|就能)$", "", term)
    return term.strip()


def _semantic_terms(text: str, cue_words: tuple[str, ...] = (), glossary: tuple[str, ...] = ()) -> list[str]:
    """Extract compact objects/topics; never expose transition or action verbs alone."""
    lowered = text.lower()
    terms: list[str] = []

    def add(raw: str) -> None:
        term = _compact(raw)
        key = term.lower()
        if not term or key in LOW_INFORMATION_ANCHORS or key in ENGLISH_STOPWORDS:
            return
        if len(term) > 16:
            return
        if any(key in existing.lower() for existing in terms):
            return
        terms[:] = [existing for existing in terms if existing.lower() not in key]
        if key not in {item.lower() for item in terms}:
            terms.append(term)

    for quoted in re.findall(r"[“\"「『](.{2,16}?)[”\"」』]", text):
        add(quoted)

    canonical_terms = tuple(dict.fromkeys((*glossary, *DOMAIN_TERMS)))
    if re.search(r"浏览器.{0,2}插件", text):
        add("浏览器插件")
    if re.search(r"\bTab\s*Out\b", text, flags=re.IGNORECASE):
        add("TabOut")

    # Prefer concrete product/UI nouns and keep the longest overlapping term.
    occupied: list[tuple[int, int]] = []
    for term in sorted(canonical_terms, key=len, reverse=True):
        position = lowered.find(term.lower())
        if position < 0:
            continue
        bounds = (position, position + len(term))
        if any(left <= bounds[0] and right >= bounds[1] for left, right in occupied):
            continue
        add(term)
        occupied.append(bounds)

    # Use compact concrete noun phrases when the project glossary does not
    # already provide a term. The suffix is semantic (model, process, module,
    # etc.); transition verbs alone never become visible copy.
    for compound in CONCRETE_COMPOUNDS:
        if compound in text:
            add(compound)
    suffix_pattern = "|".join(sorted((re.escape(item) for item in NOUN_SUFFIXES), key=len, reverse=True))
    for match in re.finditer(rf"[\u4e00-\u9fff]{{1,8}}(?:{suffix_pattern})", text):
        raw = match.group(0)
        if any(raw.endswith(compound) for compound in CONCRETE_COMPOUNDS):
            continue
        matched_suffix = next((item for item in sorted(NOUN_SUFFIXES, key=len, reverse=True) if raw.endswith(item)), "")
        prefix = raw[:-len(matched_suffix)] if matched_suffix else raw
        prefix = re.sub(r"^(?:这些|那些|一些|一个|这个|那个|某个|通过|还有|下面|另外|就是|可以|能够|需要)", "", prefix)
        prefix = prefix[-4:]
        if re.search(r"(?:的|是|了|有|会|要|用|过|给|让|把|做|来|去|发|些|或者)", prefix):
            prefix = ""
        add(prefix + matched_suffix)

    cue_keys = {word.lower() for word in cue_words}
    known_ascii = {term.lower() for term in canonical_terms if re.search(r"[A-Za-z]", term)}
    for token in re.findall(r"[A-Za-z][A-Za-z0-9_+-]{2,}", text):
        verified = token.lower() in known_ascii or bool(re.search(r"[0-9_+\-]|[a-z][A-Z]", token))
        if verified and token.lower() not in cue_keys and token.lower() not in ENGLISH_STOPWORDS:
            add(token)

    # When an action has a clear English object, use the object rather than the verb.
    for cue in cue_words:
        if not re.fullmatch(r"[A-Za-z]+", cue):
            continue
        match = re.search(
            rf"\b{re.escape(cue)}\b(?:\s+(?:the|a|an|this|that|your|our))?\s+"
            r"([A-Za-z][A-Za-z0-9_-]*(?:\s+[A-Za-z][A-Za-z0-9_-]*){0,2})",
            text,
            flags=re.IGNORECASE,
        )
        if match:
            words = [word for word in match.group(1).split() if word.lower() not in ENGLISH_STOPWORDS]
            unverified_title = any(word[:1].isupper() and word.lower() not in known_ascii for word in words)
            if words and not unverified_title:
                add(" ".join(words))

    return terms[:3]


def _ui_action_terms(text: str, cues: tuple[str, ...], glossary: tuple[str, ...]) -> list[str]:
    """Bind an action only to objects in the same spoken clause."""
    clauses = [piece.strip() for piece in re.split(r"[，。！？；：,.!?;:]", text) if piece.strip()]
    terms: list[str] = []
    for cue in cues:
        clause = next((piece for piece in clauses if cue.lower() in piece.lower()), "")
        if not clause:
            continue
        for term in _semantic_terms(clause, (cue,), glossary):
            if term not in terms:
                terms.append(term)
    return terms[:3]


def _anchor(text: str, glossary: tuple[str, ...] = ()) -> tuple[str, list[str], float]:
    lowered = text.lower()
    chapter_terms = _semantic_terms(text, glossary=glossary)
    if chapter_terms and re.search(r"(?:这是|这个是|另外|下面|接下来|最新|第[一二三四五六七八九十\d]+).{0,14}(?:版本|功能|部分|章节)|(?:版本|功能).{0,8}(?:叫|是|来自)", text):
        return "chapter_boundary", chapter_terms, 3.3 + min(0.6, len(chapter_terms) * 0.2)
    for purpose, words in CUE_RULES:
        matched = tuple(word for word in words if word.lower() in lowered)
        if matched:
            terms = _ui_action_terms(text, matched, glossary) if purpose == "ui_action" else _semantic_terms(text, matched, glossary)
            if not terms:
                return purpose, [], 0.5
            generic_only = all(term in GENERIC_ANCHORS for term in terms)
            return purpose, terms, (2.3 if generic_only else 2.8 + min(1.2, len(terms) * 0.35))
    numbers = re.findall(r"(?:\d+(?:\.\d+)?[%个项步次分钟秒]*)", text)
    if numbers:
        terms = numbers + _semantic_terms(text, glossary=glossary)
        return "number", terms[:3], 3.0
    terms = _semantic_terms(text, glossary=glossary)
    generic_only = terms and all(term in GENERIC_ANCHORS for term in terms)
    return ("explanation", terms, 2.3 if generic_only else (2.7 if terms else 0.4))


def _target_count(duration: float, profile: str, content_type: str) -> int:
    """Return an upper quality budget, never a quota that must be filled."""
    _, high = MOTION_PROFILES.get(profile, MOTION_PROFILES["adaptive_dynamic"]).get(content_type, (3, 8))
    return max(0, math.floor(max(duration, 0.0) / 60.0 * high))


def _candidate(segment: dict[str, Any], index: int, duration: float, glossary: tuple[str, ...]) -> dict[str, Any]:
    text = str(segment.get("text", "")).strip()
    purpose, terms, semantic_score = _anchor(text, glossary)
    start, end = float(segment.get("start", 0)), float(segment.get("end", 0))
    midpoint = _midpoint(segment)
    boundary_bonus = 0.6 if index == 0 or midpoint >= duration - 12 else 0.0
    pace = max(0.25, end - start)
    score = semantic_score + min(0.8, len(text) / 60) + boundary_bonus + min(0.5, pace / 10)
    cue = next((word for _, words in CUE_RULES for word in words if word.lower() in text.lower()), None)
    return {
        "candidate_id": f"{index}:primary",
        "segment_index": index,
        "start": start,
        "end": end,
        "midpoint": midpoint,
        "text": text,
        "purpose": purpose,
        "cue": cue,
        "semantic_anchor": terms,
        "semantic_score": round(semantic_score, 4),
        "score": round(score, 4),
    }


def _tier(score: float, purpose: str) -> str:
    if purpose == "chapter_boundary" and score >= 3.8:
        return "macro"
    if score >= 3.8:
        return "meso"
    return "micro"


def _duration(tier: str) -> float:
    return {"micro": 1.15, "meso": 2.2, "macro": 3.0}[tier]


def _family(candidate: dict[str, Any]) -> str:
    variant = _variant(candidate)
    if variant in {"compare_split", "cause_effect_link", "step_rail"}:
        return "structure"
    if variant in {"section_reveal", "soft_wipe"}:
        return "chapter_transition"
    if variant in {"cursor_click", "focus_ring", "tooltip_attach"}:
        return "ui_attention"
    if variant in {"underline_draw", "count_up"}:
        return "kinetic_text"
    return "semantic_icon"


def _variant(candidate: dict[str, Any]) -> str:
    if candidate["purpose"] == "ui_action":
        return UI_VARIANT_BY_CUE.get(str(candidate.get("cue", "")).lower(), "focus_ring")
    if candidate["purpose"] in {"contrast", "causality"} and len(candidate.get("semantic_anchor", [])) < 2:
        return "underline_draw"
    if candidate["purpose"] == "chapter_boundary":
        return "section_reveal" if int(candidate.get("segment_index", 0)) % 2 == 0 else "soft_wipe"
    if candidate["purpose"] == "explanation":
        text = str(candidate.get("text", ""))
        terms = candidate.get("semantic_anchor", [])
        if len(terms) >= 2 and int(candidate.get("segment_index", 0)) % 3 == 0:
            return "step_rail"
        if re.search(r"(?:这里|下面|页面|功能|记录|按钮|入口)", text):
            return "focus_ring" if int(candidate.get("segment_index", 0)) % 2 == 0 else "tooltip_attach"
        return "icon_pop" if int(candidate.get("segment_index", 0)) % 2 == 0 else "icon_path"
    return VARIANT_BY_PURPOSE.get(candidate["purpose"], "icon_pop")


def _visual_payload(candidate: dict[str, Any], variant: str) -> dict[str, Any]:
    terms = candidate.get("semantic_anchor", [])
    if variant == "compare_split" and len(terms) >= 2:
        return {"left": terms[0], "right": terms[1]}
    if variant == "cause_effect_link" and len(terms) >= 2:
        return {"nodes": terms[:3]}
    if variant == "step_rail":
        return {"steps": terms[:3]}
    if variant in {"section_reveal", "soft_wipe"}:
        return {"chapter": str(int(candidate.get("segment_index", 0)) + 1).zfill(2)}
    return {}


def _sfx(events: list[dict[str, Any]]) -> None:
    for index, event in enumerate(events, 1):
        profile = SFX_BY_FAMILY.get(event["visual_family"])
        if not profile:
            event["sfx"] = {
                "enabled": False,
                "decision": "intentionally_silent",
                "reason": "no treatment-specific sound profile exists; requires review",
            }
            continue
        family, duration = profile
        slug = re.sub(r"[^a-zA-Z0-9_-]+", "-", str(event["id"])).strip("-").lower()
        event["sfx"] = {
            "enabled": True,
            "family": family,
            "variant": f"event-{index:03d}-{slug}.wav",
            "duration_seconds": duration,
            "landing_offset_seconds": 0.22,
            "volume": (0.26, 0.28, 0.30)[(index - 1) % 3],
            "track": "sfx",
            "reason": f"unique multi-note motif matched to {event['purpose']} motion",
        }


def plan_attention_events(
    segments: list[dict[str, Any]],
    duration: float,
    *,
    profile: str = "adaptive_dynamic",
    content_type: str = "screen_tutorial",
    seed: str = "default",
    burned_captions: bool = False,
    glossary: list[str] | tuple[str, ...] | None = None,
) -> dict[str, Any]:
    valid = [segment for segment in segments if str(segment.get("text", "")).strip()]
    glossary_terms = tuple(str(term).strip() for term in (glossary or []) if str(term).strip())
    candidates = [_candidate(segment, index, duration, glossary_terms) for index, segment in enumerate(valid)]
    eligible = [
        candidate for candidate in candidates
        if candidate["semantic_anchor"] and candidate["semantic_score"] >= MIN_SEMANTIC_SCORE
    ]
    budget = _target_count(duration, profile, content_type)
    ranked = sorted(eligible, key=lambda item: (-item["score"], item["midpoint"], item["segment_index"]))
    selected: list[dict[str, Any]] = []
    anchor_history: dict[str, list[float]] = {}

    def select(candidate: dict[str, Any]) -> bool:
        midpoint = float(candidate["midpoint"])
        if midpoint < 0.5 or midpoint > duration - 0.5:
            return False
        if any(abs(midpoint - float(prior["midpoint"])) < 3.0 for prior in selected):
            return False
        available_terms = []
        for term in candidate["semantic_anchor"]:
            key = str(term).lower()
            previous = anchor_history.get(key, [])
            if len(previous) >= MAX_EXACT_ANCHOR_OCCURRENCES:
                continue
            if previous and any(abs(midpoint - prior) < ANCHOR_REPEAT_COOLDOWN_SECONDS for prior in previous):
                continue
            available_terms.append(term)
        if not available_terms:
            return False
        selected_candidate = {**candidate, "semantic_anchor": available_terms}
        selected.append(selected_candidate)
        for term in available_terms:
            anchor_history.setdefault(str(term).lower(), []).append(midpoint)
        return True

    # Cover the timeline before using the remaining quality budget. This avoids
    # clustering equally strong events in one chapter while leaving minute-long
    # gaps elsewhere. Empty slots remain empty when they have no eligible idea.
    if budget:
        slot_width = duration / budget
        for slot in range(budget):
            left, right = slot * slot_width, (slot + 1) * slot_width
            candidates = [item for item in eligible if left <= float(item["midpoint"]) < right]
            for candidate in sorted(candidates, key=lambda item: (-item["score"], item["midpoint"])):
                if select(candidate):
                    break
    for candidate in ranked:
        if len(selected) >= budget:
            break
        if candidate not in selected:
            select(candidate)

    selected.sort(key=lambda item: item["midpoint"])
    events: list[dict[str, Any]] = []
    for ordinal, candidate in enumerate(selected, 1):
        tier = _tier(candidate["score"], candidate["purpose"])
        event_duration = _duration(tier)
        event_start = min(
            max(0.0, candidate["midpoint"] - event_duration * 0.42),
            max(0.0, duration - event_duration),
        )
        terms = candidate["semantic_anchor"][:3]
        variant = _variant(candidate)
        events.append({
            "id": f"attention-{ordinal:03d}",
            "tier": tier,
            "start": round(event_start, 3),
            "end": round(event_start + event_duration, 3),
            "duration": event_duration,
            "semantic_anchor": terms,
            "transcript_evidence": {
                "segment_index": candidate["segment_index"],
                "start": candidate["start"],
                "end": candidate["end"],
                "text": candidate["text"],
            },
            "purpose": candidate["purpose"],
            "visual_family": _family(candidate),
            "motion_variant": variant,
            "render_contract": RENDER_CONTRACT_BY_VARIANT[variant],
            "visual_payload": _visual_payload(candidate, variant),
            "safe_zone": "unresolved",
            "layout_selector": "requires_geometry",
            "caption": {
                "mode": "keyword_only" if burned_captions else "natural_phrase",
                "highlight_terms": terms,
                "max_highlights": 3,
                "duplicate_full_caption_forbidden": burned_captions,
            },
            "redundancy_check": {
                "status": "pending_visual_inventory",
                "decision": "must compare with source captions, callouts, PIP, and existing motion",
            },
            "collision_check": {
                "status": "pending_geometry_snapshot",
                "avoid": ["captions", "face", "cursor", "platform_ui", "important_source_ui"],
            },
            "semantic_score": candidate["semantic_score"],
            "selection_reason": "high-confidence compact semantic anchor; no density filler",
            "intentional_quiet": False,
        })
    _sfx(events)
    low, high = MOTION_PROFILES.get(profile, MOTION_PROFILES["adaptive_dynamic"]).get(content_type, (3, 8))
    return {
        "schema_version": 2,
        "planner": "quality_bounded_semantic_attention",
        "deterministic_seed": seed,
        "profile": profile,
        "content_type": content_type,
        "glossary_terms": list(glossary_terms),
        "duration": round(duration, 3),
        "recommended_events_per_minute": [low, high],
        "events": events,
        "intentional_quiet_sections": _quiet_sections(events, duration),
        "constraints": {
            "event_rate_policy": "quality_bounded_target",
            "minimum_events_per_minute": low,
            "target_events_per_minute": round((low + high) / 2, 2),
            "maximum_events_per_minute": high,
            "same_family_max_consecutive": 3,
            "normal_window_min_families": 1,
            "family_max_share": 0.65,
            "maximum_visual_quiet_gap_seconds": 20,
            "quiet_gap_policy": "long quiet requires verified source-activity evidence",
            "require_distinct_render_contract": True,
            "max_concurrent_layers": 1,
            "anchor_repeat_cooldown_seconds": ANCHOR_REPEAT_COOLDOWN_SECONDS,
            "max_exact_anchor_occurrences": MAX_EXACT_ANCHOR_OCCURRENCES,
            "same_sfx_file_cooldown_seconds": 20,
            "sfx_max_event_ratio": 1.0,
            "sfx_max_per_minute": 6,
        },
    }


def _quiet_sections(events: list[dict[str, Any]], duration: float) -> list[dict[str, Any]]:
    cursor = 0.0
    quiet = []
    reason = "planner found no high-confidence non-redundant semantic anchor; visual review is still required"
    for event in sorted(events, key=lambda item: float(item["start"])):
        start = float(event["start"])
        if start - cursor > 20:
            quiet.append({
                "start": round(cursor, 3), "end": round(start, 3), "reason": reason,
                "evidence": {"kind": "planner_no_candidate", "verified": False, "samples": []},
            })
        cursor = max(cursor, float(event["end"]))
    if duration - cursor > 20:
        quiet.append({
            "start": round(cursor, 3), "end": round(duration, 3), "reason": reason,
            "evidence": {"kind": "planner_no_candidate", "verified": False, "samples": []},
        })
    return quiet
