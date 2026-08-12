# P0-P2 Requirements Traceability

Status: design-freeze candidate
Canonical objective: `E:\Projects\Skills\content-preserving-video-editor\references\p0-p2-design\goal-objective.md`
Canonical objective SHA-256: `402ec6d6b96d8e0b964f3b24eb0ce4231d4e9947ece28ad5650eb283810d3a12`

## Decision

This is a real requirement, not a request for more decorative motion. Previous
projects demonstrated that a technically valid render can still be semantically
wrong, visually distracting, geometrically inaccurate, or incomplete as a
publishable package. The design therefore optimizes explanatory value and
truthful completion, not event count.

The simpler alternative—adding more templates or lowering the motion-gap
threshold—would reproduce the observed failure mode. It is rejected because it
rewards filler and cannot prove that a target, word, or visual claim is correct.

## Maturity vocabulary

Every capability and acceptance row uses exactly one of these states:

- `documented`: policy or design exists only.
- `director_integrated`: Director has a real route, state, invalidation, and
  failure contract.
- `fixture_validated`: deterministic fixtures and negative tests pass.
- `real_project_validated`: the exact implementation passed both current
  landscape and portrait canaries with human evidence.
- `production_default`: enabled by default after real-project evidence and a
  safe migration.

The current capability inventory contains 56 routes: 46 are
`director_integrated`, 10 are `fixture_validated`, and none of the current
implementation is `real_project_validated` or `production_default` under this
new design. Historical project reports do not promote changed code.

## Traceability rules

1. Every implementation task, configuration field, test, and evidence artifact
   MUST cite one or more `RQ-*` identifiers.
2. A structural JSON pass is not visual, semantic, likeness, or publishability
   approval.
3. A requirement may be `not_applicable` only through an evidence-backed
   decision owned by the responsible stage.
4. No feature may be promoted beyond its evidence maturity.
5. The test and evidence columns below are acceptance obligations, not claims
   that the implementation already exists.

## Requirement matrix

| ID | Source problem / user outcome | Priority | Target effect | Non-goal | Owner and planned configuration | Automated / fixture evidence | Real sample and human evidence |
|---|---|---:|---|---|---|---|---|
| RQ-001 | Preserve the original narrative and most source material | P0 | Source remains immutable; every omission is EDL-backed and explained; default delivery covers the retained timeline | Retention optimization by deleting caveats, debugging, or the ending | video-use timeline; Director preservation policy; `editing.preservation` | EDL bounds, word-boundary, tail, long-omission, and final-edit-correctness tests | Side-by-side source/final coverage review; user confirms no material loss |
| RQ-002 | Motion copy was irrelevant, random, repeated, or reduced to words such as “打开” | P0 | Every rendered event inherits one approved semantic event, approved visible copy, evidence words, rationale, and viewer takeaway | Keyword scoring, subtitle restatement, or Storyboard-authored meaning | Director semantic brief and Motion Quality Engine; `motion_quality.semantic_binding` | Counterexamples for low-information anchors, extra copy, reordered IDs, missing evidence, and semantic drift | Multimodal event review against original sentence and frame; user rejects/accepts the explanatory value |
| RQ-003 | Boxes and connectors missed the intended source UI | P0 | Source-bound effects identify real targets, edges, and useful content, with measured geometry | Guessing coordinates from a single representative frame | Director target binding; HyperFrames selector/geometry implementation; `motion_quality.target_binding` | Target count, occupancy, endpoint distance, crop, selector, and source-window tests | Entrance/mid/pre-exit overlays compared with source at identical times |
| RQ-004 | Source state changed while an old overlay remained | P0 | Every target binding has a state-valid active window; scene changes invalidate static geometry or require tracking keyframes | A box that merely stays on screen for the narration duration | Target-binding state signatures; `static`, `scene_bounded`, or `keyframed` tracking | Seed modal/page/scroll/layout changes; stale geometry must fail | Canary includes at least one changing UI state and one lost/changed target |
| RQ-005 | Motion was either too sparse or mechanically overfilled | P0 | The engine records a decision for every meaningful opportunity and permits evidenced quiet intervals; density follows content energy | Fixed “one event every N seconds”, minimum card quota, or random family rotation | Motion opportunity selector; `motion_quality.density` | Opportunity-decision coverage, concurrent-layer, quiet-evidence, repetition, and attention-budget tests | Paired sample review scores “helps comprehension” and “not distracting”; event count is reported only as context |
| RQ-006 | Motion lacked keyframes, easing, layering, depth, and cinematic finish | P0 | A recipe declares visible poses, phase timing, easing, hierarchy, camera/composite intent, final hold, and proof commands | Copying CapCut/Jianying proprietary effects or forcing GPU effects | HyperFrames + `hyperframes-keyframes`; `motion_quality.recipes` | Recipe schema, seek safety, keyframe receipt, animation-map, focused shot, first/final state tests | Four-phase contact sheet and real-time sample playback; user selects candidate over baseline |
| RQ-007 | Foreground disappeared against similar source colors | P0 | Readability is measured after compositing over the real source and repaired through surface/outline/shadow/placement strategy | Internal component contrast without source compositing | Director composite contrast gate; HyperFrames style tokens; `motion_quality.contrast` | Per-event foreground/background measurements, caption collision, protected-zone, and crop tests | Full-size and thumbnail review on light, dark, and mixed source states |
| RQ-008 | SFX was single-note, quiet, repetitive, missing, or masked by speech | P1 | Every event has an audio decision; selected cues use appropriate multi-phase motifs, measured onset and dialogue-relative audibility | Making every event audible or making every cue unique | Director audio policy and FFmpeg mix; `audio.motion_sfx` | Audio decodability/hash, onset, duration, family fingerprint, cooldown, masking, and true-peak tests | A/B audition with SFX off/on; user confirms audible but not distracting |
| RQ-009 | BGM, captions, cover, or IP stages could be bypassed while the workflow looked complete | P0 | Required deliverables reach `asset_ready` or explicit `not_applicable`; contract-only stages cannot satisfy delivery | Pretending a request packet or sidecar file is a finished asset | Director stage readiness; `delivery.required_assets` | Stage-state, artifact hash, invalidation, missing-caption, missing-audio, and missing-cover tests | Pre-publish checklist opens exact universal MP4, cover, and evidence; user sees unresolved actions |
| RQ-010 | Captions were absent, mis-segmented, or out of sync | P0 | Word-timed, natural sentence captions use punctuation for segmentation, preserve wording, and are applied last | LLM summaries as subtitles or one-character karaoke by default | video-use word/timeline owner; Director caption delivery; `captions` | Punctuation-tail, terminology, EDL remap, SRT hash/filter-chain, sample-sync, and final-output tests | First/middle/last and cut-boundary review at 1× speed |
| RQ-011 | One video should publish to multiple platforms without duplicate identical outputs | P0 | Deliver one universal MP4 by default and validate the same bytes for each platform | Two identical platform MP4 files | Director delivery; `delivery.output_mode=universal` | Same-hash platform reports, decode, dimensions, loudness, safe-zone tests | User reviews one master plus platform crop/safe-zone previews |
| RQ-012 | Landscape screen recordings and portrait human footage need different composition logic | P0 | Orientation, rotation, source type, faces, captions, and safe zones select adaptive layout constraints | Blind center crop or one landscape coordinate table reused in portrait | Director evidence/layout policy; HyperFrames orientation variants; `motion_quality.layout` | Rotation/display-ratio, portrait/landscape contracts, face/UI collision, lost-track tests | One 30–90s landscape screen canary and one 30–90s portrait talking-head canary |
| RQ-013 | Third-party authorized footage must not impersonate HongRun | P0 | Identity mode is explicit; third-party mode forbids HongRun face, IP art, intro/outro, and first-person claims | Inferring creator identity from the workspace directory | Production Contract; `identity.mode=self|third_party|generic` | Forbidden-asset/copy/intro/outro negative tests and authorization receipt | User confirms identity treatment and rights basis before sample approval |
| RQ-014 | Personal IP visuals and covers must be topic relevant, complete, and anatomically credible | P1 | Self-owned projects may use topic-specific, componentized IP assets and reference-guided covers with separate likeness approval | Generic old IP images, pasted face cutouts, or automated likeness approval | Director IP/cover pipeline; `visuals.ip_production`, `cover.production` | Provenance, semantic-event, alpha/padding, anatomy roles, layout, OCR, and crop tests | Full-resolution anatomy/topic review; user alone approves likeness and cover appeal |
| RQ-015 | Sample approval must protect the exact full build | P0 | Sample/full are separate projects; approval, QA, and final render authorization are hash-bound and invalidated by drift | Treating a Storyboard board or green tests as final-render approval | Director sample/full stages; `review.sample` | Receipt/invalidation/parity/golden-regression tests | User approves embedded sample after paired review, then separately authorizes final render |
| RQ-016 | Review artifacts are hard to inspect and cause repeated correction cycles | P0 | One read-only paired creative review surface embeds baseline/candidate, event timeline, four phases, semantic rationale, and audio toggles; edits become pending ledger proposals | A dashboard of raw JSON links or direct untracked DOM/file edits | Director review service; `review.creative` | Hash/CSRF/loopback/stale-proposal/correction-ledger tests | User can identify and request a correction at an event without describing the whole frame |
| RQ-017 | OpenCut/OpenChatCut/OpenMontage/Jianying/OTIO/Remotion could blur ownership | P2 | Optional adapters exchange typed, hash-bound artifacts; no external editor becomes a required automated backend | Claiming unavailable MCP/API/headless features or copying AGPL code | Director handoff; video-use timeline; HyperFrames full-motion owner; feature flags default off | Disabled-default, unavailable, round-trip, loss report, and returned-media revalidation tests | Human finish remains `action_required`; returned master passes all delivery gates again |
| RQ-018 | Expensive runs need predictable cost, privacy, caching, and recovery | P1 | Event-scoped analysis, provider reservation/reconciliation, hash-safe cache, and local/private defaults minimize repeated work | Silent downloads, implicit cloud upload, or cache reuse without equivalence | Director governance/cache; `provider_governance`, `render.cache` | Budget, reservation, retry, cache invalidation, privacy, rights, and interruption/resume tests | Canary records wall time, provider cost, tokens, GPU/render time, and rerun savings |
| RQ-019 | Commercial hook, title, cover, and publishing copy can promise different things | P1 | One evidence-bound editorial-intent/promise ledger supplies audience, viewer job, promise, proof, tone, CTA, and prohibited claims; unknown intent defaults to neutral education | Inventing conversion goals, performance claims, or guaranteed CTR | Director editorial intent; `editorial.intent` | Claim provenance and cross-artifact consistency tests | User judges hook/title/cover promise and willingness to publish/click |
| RQ-020 | Automated tests can falsely imply aesthetics or release readiness | P0 | Completion states distinguish structural tests, multimodal review, and user approval; only exact evidence promotes maturity | Aggregate “aesthetic score” or fixture-only production claims | Director completion audit and real-project validation contract | Tamper/stale/hash/placeholder/fixture-vs-real evidence tests | User records publishability, taste, likeness when applicable, and correction time |

## Positive, negative, and boundary examples

### Positive

- A speaker says “CTR rose while CPC fell”; the approved event binds the exact
  words and visible chart state, then uses a comparison recipe with two verified
  plot targets. The effect lands on the spoken contrast and leaves before the
  page scrolls.
- A 22-second dense product interaction receives no overlay because cursor and
  source UI already explain the action. A `quiet_source` decision cites frames
  and is treated as a valid editorial decision, not a missing-motion defect.

### Negative

- A transcript contains “打开报表”; an overlay shows only “打开” and places a
  generic card in the corner. It fails RQ-002 even if it is readable and within
  the safe zone.
- A bounding box was correct at entrance but the modal closed before pre-exit.
  Static geometry fails RQ-004; a single midpoint screenshot cannot excuse it.
- Six differently named whoosh files with the same perceptual envelope do not
  satisfy RQ-008 diversity.

### Boundary cases

- If the source has fewer than four real visual opportunities, the sample may
  contain fewer than four motion events. The evidence set must still cover a
  typical event, the densest or riskiest state, and any available connector/IP
  case; no filler is created.
- If a third-party video contains the speaker's own logo, preserving that source
  content is allowed. Adding HongRun identity material is still forbidden.
- If no authorized BGM asset/provider is available, `disabled` with reason is a
  truthful audio outcome. It must not be reported as an enabled BGM asset.

## Requirement-to-design index

| Design asset | Requirements covered |
|---|---|
| `motion-quality-engine-v1.md` | RQ-002–RQ-008, RQ-012, RQ-015–RQ-016 |
| `machine-contracts.md` and schemas | RQ-002–RQ-008, RQ-012–RQ-020 |
| `architecture-decisions.md` | RQ-001, RQ-009–RQ-020 |
| `p0-p2-implementation-plan.md` | all requirements |
| `acceptance-matrix.md` | all requirements, with evidence owner and maturity |
| `risk-and-cost-ledger.md` | RQ-005, RQ-008, RQ-014, RQ-017–RQ-020 |
