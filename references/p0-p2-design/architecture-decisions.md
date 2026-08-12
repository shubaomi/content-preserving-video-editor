# P0-P2 Architecture Decisions

Status: design-freeze candidate; no production implementation is authorized by
this document.

## Current-state audit

- The Director has 19 stages and correctly separates media analysis, semantic
  planning, sample approval, full-project QA, render authorization, composition,
  optional manual finish, and delivery QA.
- The current capability registry has 56 entries: 46
  `director_integrated`, 10 `fixture_validated`, 0
  `real_project_validated`, and 0 `production_default` for the current code.
- Storyboard semantic inheritance, source-state target contracts, composite
  contrast, audio decisions, preview/render parity, caption-last composition,
  one universal output, and returned-NLE revalidation already exist and must be
  preserved.
- The current Brand Motion Playbook compiles one global entrance/reveal/hold/exit
  grammar. The older dynamic renderer exposes named variants, but several share
  one card shell and simple entrance/exit tweens. Neither is a sufficient motion
  quality engine.
- The current sample contract hard-requires four events/structures. This can
  manufacture motion when the source does not justify it and will be replaced
  by risk-based sample selection.
- The current review dashboard is a read-only artifact index, not a paired
  creative review surface.
- HyperFrames already provides GSAP timelines, FLIP, paths, masks, SVG, CSS,
  WAAPI, Lottie, Three/WebGL, animation-map analysis, and keyframe diagnostics.
  The Director does not yet bind those capabilities to event-level recipes and
  keyframe receipts.

## ADR-001 — Director remains the system of record

**Decision:** The Director owns policy, workflow state, semantic approvals,
provider/cost governance, evidence binding, invalidation, review proposals, and
delivery gates.

**Why:** Moving orchestration into a renderer or NLE would split truth across
tools and recreate false completion states.

**Consequences:** HyperFrames, video-use, FFmpeg, Remotion, and NLE adapters
return artifacts and receipts. They never set a Director stage to complete by
themselves.

**Trace:** RQ-001, RQ-009, RQ-015–RQ-020.

## ADR-002 — video-use owns words, EDL, and timeline correctness

**Decision:** video-use remains the only owner of word timestamps, edit ranges,
output remapping, master captions, and final-edit-correctness. The Director may
validate and request these artifacts but cannot invent them and stamp the owner.

**Why:** Caption sync and preservation depend on one authoritative timeline.

**Consequences:** Caption grouping defects are fixed in the local bridge when
they concern consumption/presentation; upstream video-use changes require an
independent minimal reproduction of an upstream-owned defect.

**Trace:** RQ-001, RQ-010.

## ADR-003 — Semantic opportunity and render event are separate contracts

**Decision:** The semantic brief records all chapter opportunities and explicit
`render`, `caption_only`, `annotation`, `reuse_source`, or `quiet_source`
decisions. A Storyboard contains only selected render events and maps each to one
approved semantic event. It does not need one rendered event per brief row.

**Why:** The current exact event-count equality plus four-event minimum can turn
coverage into filler. Selection must be complete without forcing rendering.

**Consequences:** Every opportunity has a decision; every rendered event has a
semantic parent; zero unrelated or unapproved events are permitted. Sample
selection is risk-based, not quota-based.

**Trace:** RQ-002, RQ-005, RQ-020.

## ADR-004 — Add a Director-owned Motion Quality Engine compiler

**Decision:** A new logical compiler transforms approved semantic opportunities,
target bindings, design tokens, layout constraints, and audio policy into
versioned `motion-design-contract` and `motion-recipe` instances. It does not
render pixels.

**Why:** Today the semantic plan jumps too directly to a free-form Storyboard,
while static variant names cannot prove choreography.

**Consequences:** Recipe selection is deterministic from explicit preconditions
and recorded creative decisions. Templates are mechanisms, not automatic
content. Unknown/unsafe cases become `caption_only`, `quiet_source`, or
`action_required`.

**Trace:** RQ-002–RQ-008, RQ-012, RQ-016.

## ADR-005 — Target binding is stateful, not a single rectangle

**Decision:** A target binding includes target IDs, source/output active windows,
source-state signatures, observed boxes, confidence, tracking mode, and
invalidation policy. Static/scene-bounded bindings fail when state changes;
keyframed bindings must cover each change.

**Why:** A box correct at one frame can be wrong seconds later after a scroll,
modal, route, zoom, or layout change.

**Consequences:** PySceneDetect/OCR/MediaPipe may supply optional evidence, but
the target contract and review remain tool-neutral. Missing reliable geometry
cannot fall back to guessed coordinates.

**Trace:** RQ-003, RQ-004, RQ-007, RQ-012.

## ADR-006 — HyperFrames owns full-duration motion pixels

**Decision:** HyperFrames remains the default owner of editable high-quality
motion and final motion render. The full project must load
`hyperframes-core`, `hyperframes-creative`, `hyperframes-animation`,
`hyperframes-keyframes`, and `hyperframes-cli` when advanced recipes are used.

**Why:** Its seek-safe HTML/GSAP contract, Studio preview, strict check,
animation-map, keyframe shots, snapshots, and deterministic rendering match the
required proof model.

**Consequences:** A recipe declares its runtime and proof commands. Complex
effects may use Lottie, Three/WebGL, CSS, WAAPI, or TypeGPU only when their
benefit and render cost are explicit. Painted pixels outrank logs. The existing
sample/full separation and final approval gate remain.

**Trace:** RQ-006, RQ-015.

## ADR-007 — Remotion is a selected-event adapter only

**Decision:** Remotion remains default-off and may render only named events with
existing React component evidence. HyperFrames stays composition owner.

**Why:** Choosing two full-video render systems increases parity and maintenance
cost without solving the present semantic and geometry defects.

**Consequences:** No new Remotion project is generated merely to imitate a
HyperFrames effect. Commercial-license obligations must be checked before a
production adapter is enabled.

**Trace:** RQ-017, RQ-018.

## ADR-008 — FFmpeg owns final media mechanics, not creative motion

**Decision:** FFmpeg owns concat, caption-last application, BGM/SFX mix,
normalization, codec/export, full decode, and technical media validation. It may
implement simple equivalent fades or masks but not replace a failed motion
project with static cards.

**Why:** This preserves deterministic media correctness without making filter
graphs the creative source of truth.

**Trace:** RQ-001, RQ-008–RQ-011.

## ADR-009 — Audio uses decision coverage, not mandatory cue coverage

**Decision:** Every non-quiet event has a `cue` or `intentionally_silent`
decision. Audible cue coverage is adaptive (recommended initial corridor
35–65% of motion events), based on semantic importance, source audio, chapter
energy, and masking risk.

**Why:** Requiring sound on every event creates clutter; counting filenames lets
near-identical sounds game diversity.

**Consequences:** QA measures decodability, hashes, onset, duration, short-window
dialogue-relative audibility, motif fingerprint, cooldown, and final mix. Three
to five coherent sonic motifs are preferable to arbitrary uniqueness.

**Trace:** RQ-008, RQ-018, RQ-020.

## ADR-010 — Required deliverables use readiness states

**Decision:** A required stage is deliverable only as `asset_ready`, `ready`, or
evidenced `not_applicable`. `contract_ready` may resume the workflow but cannot
satisfy final delivery.

**Why:** Writing an audio, cover, or caption request is not producing the asset.

**Consequences:** Project mode determines applicability. Source-first caption
delivery defaults to required; BGM remains optional; cover is required only
when the configured publish package requires one; identity/IP is forbidden for
third-party mode unless it belongs to and is already present in the source.

**Trace:** RQ-009–RQ-014, RQ-020.

## ADR-011 — One universal MP4 is the default media deliverable

**Decision:** Platform validators inspect the same universal file. Additional
files are generated only when a real media transform differs.

**Why:** Duplicate identical outputs create confusion without platform value.

**Trace:** RQ-011.

## ADR-012 — Identity mode is explicit and fail-closed

**Decision:** Production Contract schema adds `identity.mode` with `self`,
`third_party`, or `generic`. `third_party` forbids HongRun identity and
first-person brand expression.

**Why:** Workspace location is not evidence of speaker identity or permission.

**Trace:** RQ-013, RQ-014.

## ADR-013 — Human/NLE handoff is optional and auditable

**Decision:** OpenCut, OpenMontage, OpenChatCut, Jianying/CapCut draft export,
other NLEs, and OTIO are optional handoffs or interchange adapters, all default
off. Pending work is `action_required`; returned media invalidates old delivery
QA and is fully revalidated.

**Why:** OpenTimelineIO is an interchange model, not a renderer. AGPL projects
may inspire methods but their source is not copied. Advertised or planned
upstream APIs are not assumed.

**Consequences:** The Director timeline remains authoritative and every adapter
emits a loss/parity report. No upstream source modification occurs without a
minimal upstream-defect reproduction.

**Trace:** RQ-017, RQ-020.

## ADR-014 — Review is paired and evidence-bound

**Decision:** `creative-review` compares baseline and candidate at the same
events/times, embeds four phases, source sentence, rationale, target overlay,
and SFX/BGM auditions, then writes pending correction proposals. It cannot
approve itself or edit final files directly.

**Why:** Raw JSON links make visual problems expensive to communicate and do
not reveal whether a new version is actually better.

**Trace:** RQ-002–RQ-008, RQ-015, RQ-016, RQ-020.

## ADR-015 — Automated, multimodal, and user gates are distinct

**Decision:** Automated gates approve only measurable facts. A multimodal agent
may reject or recommend semantic/aesthetic choices. Only the user approves
publishability, personal taste, real-person likeness, and click appeal.

**Why:** A single score invites Goodhart behavior and cannot represent identity
or taste.

**Trace:** RQ-014–RQ-016, RQ-020.

## ADR-016 — Schema v10 is additive and migrated in memory

**Decision:** Implementation will introduce project schema v10. New Motion
Quality Engine and editorial-intent fields are additive. Migration returns a
copy and never rewrites existing `project.yaml`. Expensive or experimental P2
features remain disabled by default.

**Why:** Existing projects must resume without silent behavior changes.

**Consequences:** Legacy fixtures prove v1–v9 migration. Enabling the new P0
engine for an existing project requires an explicit migration/feature decision
until real canaries justify a production default.

**Trace:** RQ-015, RQ-017, RQ-018, RQ-020.

## Tool boundary summary

| Surface | Owns | Does not own |
|---|---|---|
| Director | decisions, contracts, evidence, cost, cache/invalidation, review, delivery gates | word timing, creative pixel rendering, codec implementation |
| video-use | media inspection, word transcript, EDL, output timeline, captions, final edit correctness | motion semantics, visual styling, cover/IP generation |
| HyperFrames | editable composition, advanced motion, Studio preview, keyframes, motion render | preservation policy, semantic approval, final media delivery |
| FFmpeg | extraction/concat, captions last, mix, normalization, encode/decode/probe | semantic selection, rich motion authorship, aesthetic approval |
| Remotion | optional named React event render | full workflow or default full-video renderer |
| OpenCut/OpenMontage/OpenChatCut/Jianying/OTIO | optional human finish or typed interchange | required automation backend, Director truth, automatic completion |

## External research anchors

Only official project sources below informed the boundary decisions; they are
research inputs, not bundled dependencies or implemented adapters:

- OpenTimelineIO — editorial interchange/data model, not a media container or
  renderer: <https://github.com/AcademySoftwareFoundation/OpenTimelineIO>
- OpenChatCut — local-first conversational editor with a copyleft license; any
  adapter needs an independent license/deployment review:
  <https://github.com/0xsline/OpenChatCut>
- OpenMontage — agentic pipeline/provenance ideas, also requiring independent
  license review: <https://github.com/calesthio/OpenMontage>
- WhisperX — word alignment/diarization methods that may inform an optional
  evidence adapter: <https://github.com/m-bain/whisperX>
- FunClip — transcript/speaker-selected clipping methods, without transferring
  its model-license assumptions: <https://github.com/modelscope/FunClip>
- VideoLingo — subtitle segmentation/glossary methods:
  <https://github.com/Huanshere/VideoLingo>
- PySceneDetect — optional cut/fade evidence; a scene boundary is not edit
  permission: <https://github.com/Breakthrough/PySceneDetect>
- Revideo — programmable TypeScript video patterns, not a replacement for the
  selected HyperFrames full-composition owner:
  <https://github.com/midrender/revideo>

## Open decisions for user approval

1. Recommended: adopt schema v10 additively and keep the new engine opt-in for
   migrated projects until both canaries pass; new projects may enable it after
   that promotion gate.
2. Recommended: use the current authorized landscape product-demo source as the
   landscape canary, and select one separate authorized portrait talking-head
   clip before implementation validation.
3. Recommended: keep advanced WebGL/3D/shader recipes default off unless a
   semantic beat needs depth; GSAP/DOM/SVG remain the normal path.
4. Recommended: adopt 100% audio-decision coverage with adaptive audible-cue
   coverage, not mandatory sound on every event.
