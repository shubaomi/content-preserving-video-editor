# P0-P2 Risk and Cost Ledger

Status: design-freeze candidate.
Scope: implementation and production risks for RQ-001–RQ-020.

## 1. Decision summary

The largest risk is not render failure; it is a convincing but semantically
wrong or visually harmful render. The design therefore spends more validation
effort on semantic/target/keyframe binding and paired human review than on adding
effect families. Expensive advanced effects and external editors remain optional.

## 2. Risk ledger

| ID | Risk | Likelihood / impact | Prevention and detection | Fallback / owner |
|---|---|---|---|---|
| RK-001 | Semantic Goodhart: more events pass a density metric but reduce clarity | high / critical | opportunity decisions, approved copy, viewer takeaway, no cadence/quota, paired review | quiet/source/caption fallback; Director |
| RK-002 | Geometry is correct at one frame but stale after source change | high / critical | state signatures, active windows, multi-phase observations, lost-target fail-close | exit/rebind/simpler non-target recipe; target binding |
| RK-003 | Renderer metadata claims copy/geometry that pixels do not show | medium / critical | DOM visible-text/geometry export, decoded full-size snapshots, parity and hash binding | block render authorization; HyperFrames adapter/Director |
| RK-004 | Keyframe craft becomes a checklist with mechanical motion | medium / high | role-specific grammar, choreography fingerprints, multimodal and paired review | simpler recipe or source quiet; MQE |
| RK-005 | Composite contrast changes with source frames | high / high | measure after compositing at all phases; adaptive surface/placement | dim/outline/reposition/fallback; visual QA |
| RK-006 | SFX quota creates noise; filenames game diversity | high / high | decision coverage, adaptive audible corridor, perceptual fingerprints, short-window mix | intentionally silent; audio stage |
| RK-007 | Caption, BGM, cover, or IP request is mistaken for a finished asset | medium / critical | readiness states and exact artifact/hash/decode gates | `action_required` or evidenced N/A; Director |
| RK-008 | Automated or multimodal review impersonates user approval | medium / critical | separate actor fields, state-transition authorization, immutable review receipts | pending user review; Director |
| RK-009 | Identity leakage into third-party footage | medium / critical | explicit identity mode, forbidden assets/copy/intro/outro, rights receipt | generic visual treatment; Production Contract |
| RK-010 | Generative cover/IP anatomy, text, or likeness defect | high / high | component padding, anatomy/text/semantic checks, real-size review, user likeness gate | regenerate/neutral diagram/no IP; cover/IP stages |
| RK-011 | One layout breaks portrait/landscape/rotation | high / high | orientation variants, face/hand/UI/caption protection, two canaries | format-specific recipe fallback; layout engine |
| RK-012 | Schema migration silently changes old projects | medium / critical | additive in-memory v10 migration, byte-preservation fixture, opt-in migrated MQE | run legacy path; project config |
| RK-013 | Cache reuses semantically or visually stale output | medium / critical | content-addressed dependency graph and renderer/browser hashes | invalidate broader scope; cache owner |
| RK-014 | Long render fails late or repeats expensive work | medium / high | sample-first, event cache, stage resume, budget reservation/reconciliation | resume affected events; Director/provider governance |
| RK-015 | Cloud upload exposes private/third-party media | medium / critical | explicit provider/privacy/rights gate, local default, minimal event-scoped upload | local provider or action required; provider governance |
| RK-016 | GPU/3D effect cost exceeds explanatory gain | high / medium | cost tier, default-off advanced flag, preview estimate, fallback requirement | DOM/SVG/2.5D recipe; MQE/HyperFrames |
| RK-017 | Optional NLE round trip loses effects/timing | medium / high | typed manifest, OTIO/NLE capability report, round-trip diff, returned-master full QA | deliver automatic universal MP4; manual finish owner |
| RK-018 | License incompatibility from AGPL or proprietary effect copying | medium / critical | use methods/specs only, do not copy source/assets, per-dependency license review | keep adapter out-of-process or omit; maintainer |
| RK-019 | Upstream feature/API is planned but not real | medium / high | verify installed skill/CLI/version; unavailable is explicit | no adapter/action required; adapter owner |
| RK-020 | Hook/cover/title promises drift or invent claims | medium / high | one evidence-bound promise ledger and prohibited claims | neutral educational language; editorial stage |
| RK-021 | Review UI creates path traversal, XSS, CSRF, or unauthorized edits | medium / critical | loopback-only, path allowlist, escaped content, CSRF, read-only default, pending proposals | static review bundle; review service |
| RK-022 | Full suite/acceptance receipt becomes stale after source changes | high / high | source-tree hashes, fully-qualified test IDs, immutable log bytes, CI validation | rerun exact suite; completion audit |
| RK-023 | Human review burden cancels automation gains | medium / high | risk-selected sample, paired event review, correction proposals, correction-time metric | reduce recipe complexity/scope; UX/Director |
| RK-024 | Universal output fails one platform safe zone | low / high | validate same bytes against both platform profiles and previews | one transformed derivative only if media truly differs; delivery |

## 3. Cost model

### Cost units recorded per stage

- wall-clock seconds and retry count;
- local CPU/GPU time and peak memory when observable;
- rendered frames and cached/reused events;
- cloud requests, tokens, generated seconds/images, and billed amount;
- bytes uploaded/downloaded and provider/data-retention policy reference;
- human review and correction minutes.

The provider governance ledger reserves cost before a request and reconciles the
actual amount after completion. Unknown cost or rights blocks the request.

### Recommended execution order by cost

1. schema, hashes, semantic and target contract checks;
2. static DOM/geometry and keyframe snapshot checks;
3. short local preview/sample render;
4. multimodal review on selected evidence only;
5. user paired review;
6. full render and final media gates;
7. optional cloud/3D/NLE operations only when approved.

This order prevents spending render or provider budget on a semantically invalid
event.

## 4. Licensing and upstream boundary

- OpenTimelineIO may be used as an interchange model, not a renderer.
- AGPL projects such as OpenChatCut/OpenMontage can inform architecture and may
  be used through a separately reviewed adapter/deployment, but their source is
  not copied into this Skill by default.
- CapCut/Jianying visual quality may be studied at the level of general motion
  principles—timing, easing, layering, masks, transitions, sound design—but
  proprietary presets/assets/implementation are not reproduced or claimed.
- Remotion licensing and any commercial terms are verified for the actual usage
  and version before enabling a production adapter.
- Generated music, images, fonts, icons, and SFX require asset-level provenance
  and commercial-use evidence; a provider plan does not automatically prove
  rights for every asset.

## 5. Privacy boundary

- Local inspection/transcription/rendering is preferred for private or
  third-party footage.
- A cloud request must name provider, model, artifact subset, purpose, rights
  basis, cost ceiling, retention/privacy policy reference, and user/project
  authorization.
- Upload only event-scoped clips/frames when sufficient; never upload an entire
  source by convenience.
- Secrets remain environment/config references and are never written into
  manifests, logs, reviews, or commits.
- Logs and reports redact tokens, credentials, absolute personal paths, and
  private metadata before persistent storage; unsafe redaction fails closed.

## 6. Pseudo-needs and rejected optimizations

| Tempting metric/feature | Why it is harmful | Accepted replacement |
|---|---|---|
| motion every N seconds | rewards filler and fights real speaking rhythm | decision coverage + explanatory value |
| minimum four event families | forces fake variety when content is simple | risk-based sample selection |
| every event has SFX | masks dialogue and makes sound mechanical | 100% decision coverage, adaptive cues |
| every SFX filename is unique | perceptually identical files game the metric | motif/fingerprint diversity |
| automatic aesthetic total score | collapses taste into a gameable number | measurable gates + reject/recommend + user choice |
| more 3D/WebGL | increases cost and failure without guaranteed clarity | feature-off advanced recipe with 2D fallback |
| two identical platform videos | confuses delivery without changing media | one universal MP4 |
| automatic NLE backend | creates unsupported API/dependency claims | optional auditable handoff |
| two full candidates every run | doubles render/review cost | one sample candidate versus preserved baseline |
| “looks like Jianying” as acceptance | proprietary and subjective, no executable definition | explicit craft, keyframe, composite, sound and user preference criteria |

## 7. Stop and rollback triggers

Stop the affected stage and preserve evidence when:

- semantic/visible-copy/target ownership is unresolved;
- source rights or identity mode is unknown;
- cloud privacy/cost/license evidence is incomplete;
- the target is lost or source state changes outside binding coverage;
- strict check, keyframe, parity, caption, audio, decode, or final-edit gate fails;
- review hashes are stale;
- the user rejects the sample or prefers the baseline;
- correction time exceeds the canary threshold without a clear reusable fix.

Fallback order is: simpler verified recipe → caption/source emphasis → quiet
source → `action_required`. A generic decorative card is never a fallback.

## 8. Residual risks requiring user judgment

Even after all automated and multimodal gates pass, the user must decide:

- whether the motion style fits the intended audience and personal taste;
- whether a real-person depiction looks sufficiently like the subject;
- whether a cover is compelling without becoming misleading;
- whether the commercial promise and CTA are appropriate;
- whether the correction time and provider/render cost justify production use.

These are not implementation defects to hide behind a score; they are explicit
release decisions.
