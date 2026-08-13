#!/usr/bin/env python3
"""Generate a dependency-free evidence view with optional pending proposals."""
from __future__ import annotations

import html
import ipaddress
import json
from pathlib import Path
from typing import Any, Mapping
from urllib.parse import urlsplit

from director_contracts import sha256_file


ARTIFACTS = (
    ("Production Contract", "production-contract.json"),
    ("Provider Decision", "provider-decision.json"),
    ("Cost Ledger", "cost-ledger.json"),
    ("Brand Motion Playbook", "brand-motion/brand-motion-playbook.json"),
    ("Sample Visual Dynamics QA", "sample-qa/visual-dynamics-qa.json"),
    ("Visual Dynamics QA", "full-qa/visual-dynamics-qa.json"),
    ("Preview/Render Parity", "full-qa/preview-render-parity.json"),
    ("Audio QA", "full-hyperframes/audio-plan.json"),
    ("Delivery QA", "delivery-contract.json"),
    ("Correction Ledger", "manual-finish/correction-ledger.json"),
    ("Action Required", "action-required.json"),
)


def _read(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _card(label: str, path: Path) -> str:
    if not path.is_file():
        return (
            f'<article><h3>{html.escape(label)}</h3><p class="missing">unavailable</p>'
            f'<p>{html.escape(str(path.resolve()))}</p></article>'
        )
    payload = _read(path)
    summary = json.dumps(payload, ensure_ascii=False, indent=2) if payload is not None else "binary artifact"
    return (
        f'<article><h3>{html.escape(label)}</h3><p><a href="{path.resolve().as_uri()}">open artifact</a></p>'
        f'<p class="hash">SHA-256 {sha256_file(path)}</p><pre>{html.escape(summary)}</pre></article>'
    )


def _artifact_uri(value: Any) -> str:
    path = Path(str((value or {}).get("path") or "")) if isinstance(value, dict) else Path("")
    return path.resolve().as_uri() if path.is_file() else ""


def _validated_interactive_api_url(value: str | None) -> str | None:
    if value is None:
        return None
    parsed = urlsplit(value)
    host = (parsed.hostname or "").lower()
    loopback = host == "localhost"
    if not loopback:
        try:
            loopback = ipaddress.ip_address(host).is_loopback
        except ValueError:
            loopback = False
    if (
        parsed.scheme != "http" or not loopback or parsed.path != "/api/proposals"
        or parsed.query or parsed.fragment or parsed.username or parsed.password
    ):
        raise ValueError("interactive review API must be an http loopback /api/proposals URL")
    return value


def _creative_review_section(
    review_path: Path | None, motion_design_contract_path: Path | None,
    interactive_api_url: str | None, interactive_session: Mapping[str, str] | None,
) -> str:
    if review_path is None or not review_path.is_file():
        return ""
    review = _read(review_path)
    if not isinstance(review, dict):
        return '<section><h2>Paired creative review</h2><p class="missing">unavailable</p></section>'
    motion = _read(motion_design_contract_path) if motion_design_contract_path else {}
    opportunities = {
        str(row.get("semantic_event_id")): row
        for row in (motion or {}).get("opportunities") or [] if isinstance(row, dict)
    }
    baseline = review.get("baseline") or {}
    candidate = review.get("candidate") or {}
    proposal_target = motion_design_contract_path.resolve() if (
        motion_design_contract_path is not None and motion_design_contract_path.is_file()
    ) else None
    proposal_target_hash = sha256_file(proposal_target) if proposal_target else ""
    interactive = (
        interactive_api_url is not None and proposal_target is not None
        and isinstance(interactive_session, Mapping)
        and bool(interactive_session.get("authorization"))
        and bool(interactive_session.get("csrf"))
    )
    event_cards: list[str] = []
    for row in review.get("event_comparisons") or []:
        event_id = str(row.get("semantic_event_id") or row.get("event_id") or "")
        opportunity = opportunities.get(event_id) or {}
        phases = row.get("phase_artifacts") or {}
        phase_html = "".join(
            '<figure><img loading="lazy" src="{}" alt="{} {}"><figcaption>{}</figcaption></figure>'.format(
                html.escape(_artifact_uri(phases.get(phase)), quote=True),
                html.escape(event_id, quote=True), html.escape(phase, quote=True),
                html.escape(phase),
            )
            for phase in ("entrance", "mid", "pre_exit", "post_exit")
        )
        audio_html = "".join(
            '<label>{}<audio controls preload="none" src="{}"></audio></label>'.format(
                html.escape(name), html.escape(_artifact_uri(artifact), quote=True),
            )
            for name, artifact in (row.get("audio_auditions") or {}).items()
        )
        copy_text = " / ".join(str(value) for value in row.get("approved_visible_copy") or [])
        targets = ", ".join(str(value) for value in row.get("target_binding_ids") or []) or "none"
        baseline_time = float(row.get("baseline_timestamp_seconds") or 0)
        candidate_time = float(row.get("candidate_timestamp_seconds") or 0)
        proposal_controls = (
            f"""<label>动作<select name="action"><option value="move">move</option><option value="resize">resize</option><option value="hide">hide</option><option value="change_variant">change_variant</option><option value="change_sfx">change_sfx</option><option value="request_regeneration">request_regeneration</option></select></label>
<label>选择器<input name="selector" required value="#{html.escape(event_id, quote=True)}"></label>
<label>修改前<textarea name="before_value" required></textarea></label>
<label>修改后<textarea name="after_value" required></textarea></label>
<label>原因<textarea name="reason" required></textarea></label>
<label>提交人<input name="approver" required></label>
<button type="submit">仅生成 pending proposal</button><output class="proposal-status" aria-live="polite"></output>"""
            if interactive else
            f"""<label>选择器<input name="selector" required value="#{html.escape(event_id, quote=True)}"></label>
<label>属性<input name="property" required placeholder="position / scale / sfx"></label>
<label>原因<textarea name="reason" required></textarea></label>
<button type="button" disabled title="启动安全本地交互服务后提交">仅生成 pending proposal</button>"""
        )
        event_cards.append(f"""
<article class="event" id="event-{html.escape(event_id, quote=True)}">
<div class="event-head"><div><p class="eyebrow">{html.escape(event_id)}</p><h3>{html.escape(copy_text or 'Source-led visual')}</h3></div>
<button type="button" class="seek" data-baseline="{baseline_time:.6f}" data-candidate="{candidate_time:.6f}">对齐播放此事件</button></div>
<dl><dt>原句</dt><dd>{html.escape(str(row.get('source_sentence') or ''))}</dd>
<dt>解释价值</dt><dd>{html.escape(str(row.get('viewer_takeaway') or ''))}</dd>
<dt>选择理由</dt><dd>{html.escape(str(opportunity.get('rationale') or ''))}</dd>
<dt>目标绑定</dt><dd>{html.escape(targets)}</dd></dl>
<div class="phases">{phase_html}</div><div class="auditions">{audio_html}</div>
<form class="proposal" data-event="{html.escape(event_id, quote=True)}" data-target="{html.escape(str(proposal_target or ''), quote=True)}" data-target-sha256="{html.escape(proposal_target_hash, quote=True)}"><strong>待审修正建议</strong>
{proposal_controls}</form>
</article>""")
    user = review.get("user_review") or {}
    proposal_script = ""
    if interactive:
        endpoint = json.dumps(interactive_api_url, ensure_ascii=False)
        authorization = json.dumps(interactive_session["authorization"], ensure_ascii=False)
        csrf = json.dumps(interactive_session["csrf"], ensure_ascii=False)
        proposal_script = f"""<script>
const proposalEndpoint={endpoint};
const proposalAuthorization={authorization};
const proposalCsrf={csrf};
document.querySelectorAll('form.proposal').forEach(function(form){{
form.addEventListener('submit',async function(event){{
event.preventDefault();
const status=form.querySelector('.proposal-status');
const body={{status:'pending',action:form.elements.action.value,event_id:form.dataset.event,
target_path:form.dataset.target,target_sha256:form.dataset.targetSha256,
selector:form.elements.selector.value,before_value:form.elements.before_value.value,
after_value:form.elements.after_value.value,reason:form.elements.reason.value,
approver:form.elements.approver.value,timestamp:new Date().toISOString(),
related_files:[{{path:form.dataset.target,sha256:form.dataset.targetSha256}}]}};
status.textContent='提交中…';
try{{const response=await fetch(proposalEndpoint,{{method:'POST',headers:{{
'Authorization':'Bearer '+proposalAuthorization,'X-CSRF-Token':proposalCsrf,'Content-Type':'application/json'}},
body:JSON.stringify(body)}});const payload=await response.json();
if(!response.ok)throw new Error(payload.error||('HTTP '+response.status));
status.textContent='已生成 pending proposal：'+payload.proposal_id;
}}catch(error){{status.textContent='提交失败：'+String(error.message||error);}}
}});
}});
</script>"""
    return f"""
<section class="creative-review"><h2>Paired creative review</h2>
<p>技术状态：<strong>{html.escape(str((review.get('automated_status') or {}).get('status')))}</strong> · 用户决定：<strong>{html.escape(str(user.get('decision') or 'pending'))}</strong></p>
<p>页面只展示证据和创建待审建议；不会替用户批准，也不会直接修改工程。</p>
<div class="media-pair"><article><h3>Baseline</h3><video id="baseline-video" controls preload="metadata" src="{html.escape(_artifact_uri(baseline), quote=True)}"></video></article>
<article><h3>Candidate</h3><video id="candidate-video" controls preload="metadata" src="{html.escape(_artifact_uri(candidate), quote=True)}"></video></article></div>
<div class="event-list">{''.join(event_cards)}</div></section>
<script>document.querySelectorAll('.seek').forEach(function(button){{button.addEventListener('click',function(){{
var baseline=document.getElementById('baseline-video');var candidate=document.getElementById('candidate-video');
baseline.currentTime=Number(button.dataset.baseline);candidate.currentTime=Number(button.dataset.candidate);
baseline.pause();candidate.pause();}});}});</script>{proposal_script}"""


def generate_dashboard(
    *, project_root: Path, director_root: Path, output: Path,
    creative_review_path: Path | None = None,
    motion_design_contract_path: Path | None = None,
    style_reel_dashboard_path: Path | None = None,
    interactive_api_url: str | None = None,
    interactive_session: Mapping[str, str] | None = None,
) -> Path:
    project_root = project_root.resolve()
    director_root = director_root.resolve()
    state_path = director_root / "director-state.json"
    state = _read(state_path) or {"status": "unavailable", "stages": {}}
    stage_rows = "".join(
        f"<tr><td>{html.escape(name)}</td><td>{html.escape(str(row.get('status')))}</td>"
        f"<td>{html.escape(str(row.get('error') or ''))}</td></tr>"
        for name, row in (state.get("stages") or {}).items()
    )
    known_cards = "".join(_card(label, director_root / relative) for label, relative in ARTIFACTS)
    evidence_paths = sorted({
        *director_root.rglob("*.png"), *director_root.rglob("*.jpg"),
        *director_root.rglob("*.jpeg"), *director_root.rglob("*.mp4"),
        *project_root.glob("edit/video-use/transcripts/*.json"),
        *project_root.glob("edit/video-use/edl.json"),
        *project_root.glob("exports/*.mp4"), *project_root.glob("exports/*cover*"),
    })
    evidence = "".join(
        f'<li><a href="{path.resolve().as_uri()}">{html.escape(path.name)}</a> '
        f'<span>{html.escape(str(path.resolve()))} · SHA-256 {sha256_file(path)}</span></li>'
        for path in evidence_paths if path.is_file()
    ) or "<li>unavailable</li>"
    interactive_api_url = _validated_interactive_api_url(interactive_api_url)
    creative = _creative_review_section(
        creative_review_path, motion_design_contract_path, interactive_api_url,
        interactive_session,
    )
    style_reel_link = ""
    if style_reel_dashboard_path is not None and style_reel_dashboard_path.is_file():
        style_reel_link = (
            '<section><h2>HongRun portrait Style Reel</h2>'
            '<p><a href="{}">Open synchronized Source / A / B / C review</a></p>'
            '<p>This separate surface is pending-only and cannot approve brand taste.</p></section>'
        ).format(html.escape(style_reel_dashboard_path.resolve().as_uri(), quote=True))
    dashboard_mode = (
        "Interactive evidence dashboard — it creates pending proposals only and never edits media, "
        "applies corrections, or replaces human approval."
        if interactive_api_url else
        "Read-only evidence dashboard — it does not edit media or replace human aesthetic and identity approval."
    )
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    document = f"""<!doctype html>
<html lang="zh-CN"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width">
<title>Director Review</title><style>
body{{font-family:system-ui,sans-serif;margin:0;background:#f5f7f3;color:#10251e}}header{{padding:28px;background:#0b3328;color:#fff}}
main{{max-width:1180px;margin:auto;padding:24px}}.grid{{display:grid;grid-template-columns:repeat(auto-fit,minmax(320px,1fr));gap:16px}}
article,section{{background:#fff;border:1px solid #dbe6df;border-radius:16px;padding:18px;margin-bottom:18px;box-shadow:0 8px 24px #10251e12}}
pre{{max-height:320px;overflow:auto;white-space:pre-wrap;font-size:12px}}table{{width:100%;border-collapse:collapse}}td,th{{padding:8px;border-bottom:1px solid #e5ece8;text-align:left}}
.missing{{color:#8a4b3d}}.hash,li span{{font-size:11px;color:#62736c;word-break:break-all}}a{{color:#087e64}}
.media-pair{{display:grid;grid-template-columns:1fr 1fr;gap:16px}}video{{width:100%;background:#111;border-radius:12px}}
.event{{border-left:5px solid #18a383}}.event-head{{display:flex;justify-content:space-between;gap:16px;align-items:center}}.eyebrow{{font-size:12px;color:#62736c}}
.phases{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px}}figure{{margin:0}}figure img{{display:block;width:100%;aspect-ratio:16/9;object-fit:contain;background:#eef3ef;border-radius:8px}}figcaption{{font-size:12px;margin-top:4px}}
.auditions{{display:grid;grid-template-columns:repeat(auto-fit,minmax(220px,1fr));gap:10px}}audio{{display:block;width:100%;margin-top:4px}}dt{{font-weight:700}}dd{{margin:0 0 8px}}.proposal{{display:grid;gap:8px;background:#f4f8f5;padding:12px;border-radius:10px}}.proposal label{{display:grid;gap:4px}}input,textarea{{font:inherit;padding:8px}}
@media(max-width:760px){{.media-pair,.phases{{grid-template-columns:1fr}}.event-head{{align-items:flex-start;flex-direction:column}}}}
</style></head><body><header><h1>Director Review</h1><p>{html.escape(dashboard_mode)}</p>
<p>Status: <strong>{html.escape(str(state.get('status')))}</strong> · Current stage: {html.escape(str(state.get('current_stage') or 'none'))}</p></header>
<main>{creative}{style_reel_link}<section><h2>Stage progress</h2><table><thead><tr><th>Stage</th><th>Status</th><th>Note</th></tr></thead><tbody>{stage_rows}</tbody></table></section>
<section><h2>Sample / Full snapshots, covers, source evidence and Universal MP4</h2><p>Snapshot phases include entrance, midpoint, pre-exit and post-exit when available.</p><ul>{evidence}</ul></section>
<div class="grid">{known_cards}</div></main></body></html>"""
    output.write_text(document, encoding="utf-8")
    return output
