# Director Architecture

Use this reference when executing or extending the single professional workflow.

## Ownership boundary

| Stage | Owner | Required artifact |
| --- | --- | --- |
| Inspect and preservation policy | director | `workflow-contract.json` |
| Media, word transcript, EDL, cuts, remap | video-use | `edit/video-use/` artifacts |
| Semantic content reading | director + LLM | `semantic-brief.json` |
| Creative direction and motion | HyperFrames | `frame.md`, `storyboard.json`, `index.html` |
| SFX/BGM policy | director; FFmpeg final mix | `audio-contract.json`, per-event decisions, measured audibility, and licensed assets |
| Cover/IP/publishing assets | director | editorial plan, local template candidates, per-candidate QA, cover and provenance |
| Sample technical and aesthetic QA | director | `sample-qa/aesthetic-review.json` and gate report |
| Full motion project | HyperFrames | separate full-duration project and visual-vocabulary audit |
| Motion render | HyperFrames | actual render from the full project, never the sample project |
| Composite, mix, encode, decode | FFmpeg | one universal final MP4 and `final-media-report.json` |
| Optional manual finish | human editor in OpenCut or another NLE | `handoff-manifest.json`, `correction-ledger.json`, returned universal MP4, and fresh hash-bound QA |

## Capability registry and adapter boundary

`scripts/capability_registry.py` is the inventory source of truth. `inspect`
writes the effective capability and toolchain reports without installing or
updating dependencies. `scripts/director_adapters.py` supplies atomic state,
file locking, input/output/implementation hashes, timeout handling, reuse, and
failure boundaries. Optional adapters are disabled by schema-v8 migration and
must not change the legacy path.
Adapter execution uses a per-capability transaction lock around cache lookup,
execution, output hashing, and state persistence. Relative implementation paths
resolve from the adapter working directory, and concurrent invocations of the
same capability reuse one completed result rather than racing on shared output.

Director-integrated adapters include evidence analysis, local ASR routing,
OTIO projection, subject tracking, existing-edit polish, HyperFrames routing,
media-use/Catalog asset lookup, audio/IP/cover production, render cache,
platform occlusion/export validation, preferences, hook/publishing utilities,
conditional B-roll/multicam/isolation/localization, selected-event Remotion, and
user-supplied post-publish metrics. “Integrated” means the Director can route,
execute, cache, validate, or truthfully stop at the adapter boundary; it does
not claim an unavailable upstream API or paid-service authorization.

The media catalog runs only for semantic events with an explicit query and
purpose. It writes a request manifest that is passed through the configured
`{request_manifest}` argument and included as a hashed adapter input. Catalog
decisions must bind the current request set and per-event query/purpose before
their asset hashes, provenance, and rights are accepted. OpenCut remains
human-only. Remotion remains a named-event adapter; HyperFrames owns the full
composition.

Capability maturity uses exactly five ordered states: `documented`,
`director_integrated`, `fixture_validated`, `real_project_validated`, and
`production_default`. Promotions are one step at a time. Real-project promotion
requires the same implementation hash on both current landscape and portrait
canaries plus explicit user review; production default requires a separate
explicit promotion approval.

## State machine

Before the state machine leaves `inspect`, resolve input mode from explicit
project evidence or a cached `input-mode-evidence.json`. When neither exists,
run the conservative existing-edit analyzer. Bind the decision to source size,
mtime, and SHA-256 so a replaced source cannot inherit an old mode. Strong
existing-edit markers select `polish_existing`; absent strong evidence selects
`preserve`. Pixel-density caption heuristics remain review candidates and never
become strong evidence without independent verification.

The canonical entry is `scripts/director.py`. It owns these ordered stages:

1. `inspect`
2. `provider_governance`
3. `video_use_timeline`
4. `evidence_acquisition`
5. `semantic_brief`
6. `production_contract`
7. `brand_motion_playbook`
8. `hyperframes_storyboard`
9. `audio`
10. `cover`
11. `sample_qa`
12. `preview_approval`
13. `full_hyperframes_storyboard`
14. `full_hyperframes_qa`
15. `final_render`
16. `final_compose`
17. `derived_content`
18. `manual_finish_handoff`
19. `delivery_qa`

Each stage is `pending`, `running`, `action_required`, `failed`, or `complete`.
State writes are atomic. A completed stage is skipped on resume. Resetting one
stage invalidates every downstream stage.

Inside `cover`, an enabled enhanced editorial path validates
`semantic-brief.cover_direction`, writes `cover-editorial-plan.json`, resolves
the reference-regenerated, authentic-frame, or real-person/IP-hybrid route,
writes one generation request per A/B strategy, composes exact text through a
controlled template family, and runs hash-bound candidate QA before comparison
and promotion. External image generation remains an explicit adapter boundary;
missing or unauthorized calls become `action_required`.

Top-level status is reconciled from all stage rows. Revalidating a completed
upstream stage must not overwrite or delete a downstream `action_required`
stage or its action packet. Only an explicit reset at that stage or an upstream
stage may invalidate the packet.

Use `director.py approve-sample` for the `preview_approval` transition. It
records the approver and SHA-256 values for the current Storyboard, aesthetic
review, and sample gate. `stage_preview_approval` rejects a stale approval if
any of those artifacts has changed. Creating `preview-approval.json` manually
is not a supported path.

With Motion Quality enabled, the same transition also requires a paired
`sample-qa/creative-review.json`. The Director compares distinct, duration-
aligned 60–90 second baseline and candidate media at the same semantic events,
shows four receipt phases and SFX/BGM auditions, and binds the compiler,
Storyboard, audio decisions, automated gates, media, and receipts by SHA-256.
For a cue-bearing sample, FFmpeg first materializes a complete SFX-mixed
candidate and `sample-review-mix.json`; this is a Director-owned review/final-
mix responsibility, not a second motion render. The receipt validates the
ordered cue assets against the current audio plan and fails closed on path,
hash, inventory, command, or output drift. Caption delivery then runs last on
that mixed candidate and on the clean baseline using the same `master.srt`.
The review defaults to `pending_user_review`; drift marks it stale and resets the
decision. `approve-sample` requires a named human, publish willingness, and a
baseline/candidate/tie preference plus a non-empty reason. Agent or multimodal review may recommend but
cannot author user approval.

`action_required` is a real owner handoff, not a documentation pause. The agent
must load the named specialized Skill, produce the expected artifact, then run
the same director entry again. Never edit `director-state.json` by hand.

`manual_finish_handoff` is disabled by default. Disabled or backend `none` is a
completed no-op and preserves the existing automatic path. Backend `opencut` or
`other_nle`, or the separate `openmontage_handoff` configuration, creates a
human-facing action packet only after `final_compose`; it
does not invoke an NLE and does not require an OpenCut runtime. OpenCut currently
has no assumed MCP, Editor API, CLI, or headless renderer contract here.

The handoff directory is `work/director/manual-finish/`. Its manifest records
absolute paths and current SHA-256 values for every available source, automatic
master, clean A-roll, caption, transparent motion, BGM/SFX stem, and cover file;
missing optional assets remain explicit `unavailable` records. The correction
ledger stores approved before/after property changes with related file hashes and
a drift guard so structured corrections are auditable and replayable.

Schema-v12 projects may explicitly enable `manual_finish.nle_package`. Director
then assembles `nle-package-v2` after final compose, while retaining the v1
manifest and correction ledger. The package is editor-neutral: automatic master,
clean A-roll, editable SRT, ASS/style references, available media/audio/IP/outro
layers, OTIO/layer timeline, rights evidence, and an import guide are copied into
a complete hash inventory. It neither creates nor mutates a Jianying draft.
Personal-IP and outro assets require a role-specific current rights receipt;
configuration paths alone do not authorize copying. A modular HongRun outro may
contribute editable copy, individual SVG icons, and a deterministic HyperFrames
source-project archive while its transparent overlay/reference render remains
preview-gated and explicitly unavailable.
Once HongRun explicitly approves that preview, the approval receipt binds the
preview contract and snapshot without claiming encryption or identity
authentication. The renderer publishes a text-free ProRes 4444 layer, a
byte-identical approved reference composite, alpha/decode evidence, and a new
source archive. The NLE timeline may append the four-second overlay while the
base media retains its original duration.
Every nested package file is a Director stage artifact, so deletion or drift
reopens manual finishing. The stage still remains `action_required` until a
distinct human-returned export passes the existing full return QA.

On return, the director records the returned file's hash, size, and mtime, resets
old delivery QA, and performs a full FFmpeg decode plus ffprobe. The stage remains
`action_required` until caption, audio, visual, and video-use
`final-edit-correctness.json` evidence all reference the exact returned hash. A
later byte change or missing return automatically reopens both the manual stage
and `delivery_qa`.

## video-use contract

Store the EDL at `edit/video-use/edl.json`, the source transcript at
`edit/video-use/transcripts/<source-stem>.json`, mapped words at
`edit/video-use/mapped-words.json`, natural captions at
`edit/video-use/captions.json`, and the sampled timing report at
`edit/video-use/caption-sync-report.json`.

Also require `media-analysis.json` and `edit-correctness-preflight.json` before
semantic planning. The former binds ffprobe inventory and actual source
timeline views; the latter binds the EDL/transcript hashes, duration, tail and
every proposed boundary. `delivery_qa` later requires
`final-edit-correctness.json` from video-use, bound to the effective universal output hash
and first/midpoint/final plus every real cut-boundary timeline view.

The transcript must have top-level word items with `type=word`, exact text,
`start`, and `end`. `video_use_bridge.py` imports video-use's real word-range
helper and applies its output formula:

`word.start - segment.start + segment.timeline_start`

The bridge may group words into phrases and apply evidenced terminology fixes.
It may not summarize, add ideas, or retime speech.

If `edl.json` is absent, the director writes `edl-request.json` and delegates the
decision to video-use; it never creates ranges and then merely stamps
`owner=video-use`. The validator requires the real owner, legal source bounds,
cut padding/fades, preserved tail, and explicit approval for material deletion
from an already-edited timeline.

## Semantic brief contract

Require:

- `generated_by` identifying an LLM author;
- `content_reading=raw_word_transcript_and_evidence_frames`;
- transcript SHA-256 and stored evidence frames;
- direct word IDs, transcript quote, source time, relevance rationale, and
  viewer takeaway per event;
- a five-field visual-structure intent;
- stored frame evidence for long intentional quiet intervals.

When schema v10 has `motion_quality.enabled=true`, the brief uses semantic
schema v3 with `opportunity_model=decision_complete_v1`. Every opportunity has
one decision and a rationale, its source/output start preserves narrative order,
and only `render` decisions require the full visual/motion intent and an explicit
unique visible-copy list. `caption_only`, `reuse_source`, `quiet_source`, and
`annotation` remain accounted-for non-render decisions; `action_required` pauses
the Director for a material editorial choice. The legacy schema-v1/v2 validator
is unchanged while motion quality is disabled.

The deterministic validator rejects low-information anchors, repeated anchors,
subtitle-length duplication, missing evidence, and duplicate visual contracts.
It never invents the semantic plan.

Evidence acquisition uses bounded, full-duration sampling and stores a timestamp
and coverage interval for each managed frame. When this metadata exists, a
semantic event's every target-frame reference must overlap the event's source
interval, and the frame's actual timestamp must be within 15 seconds of that
interval. Capped long-video sampling therefore blocks until supplemental
event-level frames are supplied when needed; automatic supplemental capture is
not yet a built-in path. Managed count or timestamp mismatch fails closed instead
of expanding a remaining frame across the source. Legacy evidence without
timestamps remains readable but cannot claim measured temporal coverage.

## HyperFrames contract

Require `renderer=hyperframes`, all five HyperFrames capability Skills, and
`motion_output=hyperframes_render`. Every event's five-field signature must be
unique when it claims to be a distinct variant.

For a decision-complete brief, Storyboard events must equal the ordered subset
of opportunities whose decision is `render`; exact count equality with all
brief opportunities is forbidden. The mapping binds semantic event ID, anchor,
transcript word IDs, source/output timing, frame evidence, relevance rationale,
visual mechanism, viewer takeaway, and the approved visible-copy list. Legacy
schema-v1/v2 briefs retain their one-to-one compatibility behavior.
Storyboard-authored semantic fallback is forbidden. Each event carries an exact
derived `visible_copy_manifest`; common headline/text/label/component payloads
outside it are rejected. Any other string must be approved copy or an explicit
non-visible metadata path; nested authority fields fail closed. Both the sample
and the full project are validated against their respective current briefs.
Rendered DOM/OCR inspection remains a separate visual-review responsibility
rather than an automatic semantic claim.

Relation-bearing visual structures (`connector`, `brace`, `route`, `arrow`,
`flow`, `branch`, or `dependency`) require typed connector metadata with a
declared count, from/to nodes, attachment edges, and attachment intent.
Source-bound visual structures (`focus`, `highlight`, `overlay`, `callout`,
`cursor`, or `target`) require a target-region contract. That contract separates
the semantic event window from the narrower geometry-active window and binds
three source-state frames to it. Storyboard validation checks the schema and
time ownership; aesthetic QA verifies image hashes, useful-content occupancy,
target count, empty/orphan geometry, and source-state stability. Motion snapshot
planning uses the geometry-active output window so an otherwise correct event
cannot be reviewed only before or after its actual target exists.
The aesthetic validator rejects boolean-only geometry reports. It recomputes
connector attachment distances and target useful-content occupancy from
hash-bound browser/DOM measurement receipts, and recomputes panel/text contrast
over the actual source crop from midpoint/post-exit evidence.

The stateful target-binding layer supersedes a single static target-region box
when Motion Quality is enabled. Evidence acquisition emits an adaptive layout
contract with different protected-region policy for landscape UI and portrait
people footage. Sample and full scopes use separate binding directories. Every
render event explicitly declares whether it is targetless; source-bound events
must reference resolved binding files whose semantic parent, source/output
windows, active windows, state signatures, visibility/loss observations, and
evidence hashes validate. Static bindings cannot cross scene, route, modal,
scroll, zoom, layout, visibility, or rotation changes. Scene-bounded bindings
exit before the mapped state boundary; keyframed bindings require observations
on both sides of every state change. Missing detectors or lost targets yield a
declared fallback or `action_required`, never guessed coordinates. Four-phase
renderer geometry is recomputed by `target_binding_qa.py` and bound into the
HyperFrames keyframe gate. Current maturity is `fixture_validated`, not
real-project validated.

`build_real_project_validation.py` is the sole materializer for a real-canary
receipt. It probes source/baseline/candidate media, recomputes file and config
hashes, binds the current Git commit and scripts/tests source tree, then invokes
`validate_real_project_validation` before writing JSON. Caller-provided hashes
or dimensions are not trusted. Landscape and portrait receipts remain separate;
cross-canary maturity is not promoted until both pass under the same
implementation binding.

When Motion Quality is enabled, the Director compiles a separate sample/full
`motion-design-contract.json` and `hyperframes-choreography.json` from the
decision-complete brief, Production Contract, evidence bundle, Brand Motion
Playbook, adaptive layout, and any already resolved target bindings. The
versioned `motion-recipes-v1.json` registry contains exactly MQE-01 through
MQE-16. `motion_contracts.py` validates all seven frozen schemas and the
motion/recipe cross-contract invariants; `motion_quality_engine.py` selects only
from structured semantic role/form and follows declared fallback chains. The
renderer route exposes `typed_choreography_only`: HyperFrames cannot reselect
meaning, visible copy, recipe, or target geometry. Storyboard validation binds
the exact contract ID, recipe ID, choreography fingerprint, semantic ordering,
and target-binding IDs. This compiler is fixture-validated; it does not promote
visual quality until both current real canaries and user review pass.

The compiler also emits a content-format grammar. Screen/product work prioritizes
verified UI targets and explanatory relations. Portrait talking-head work uses
face-safe kinetic type, rhythmic emphasis, side rails, depth/light accents,
semantic cutaways, and chapter energy changes, and excludes floating dashboard
cards. Technical canary approval and user publish willingness do not silently
approve brand taste: the current portrait canary is evidence that the delivery
chain works, while its product-demo-like visual vocabulary remains an explicit
rejected taste observation for future creative iteration.

Advanced runtime selection is a separate fail-closed gate. The Director accepts
only current absolute file/hash records for seek safety, deterministic 2D
fallback, preview/render parity, device support, licensing, and cost. Without
all six records, the MQE selects its declared 2D fallback. HyperFrames does not
self-authorize advanced execution.

Use HyperFrames Core and Creative rules before HTML. Run HyperFrames check and
multi-phase snapshots. Studio is the editable review surface. An actual
sample command set remains stored in `hyperframes-commands.json`. After approval,
create a different full-duration project and store its render authority in
`full-hyperframes-commands.json`. The final command must execute with that
project as `cwd`; the 60–90 second sample can never become the final render by
path reuse.

For a Motion Quality project, the Director writes a hash-bound
`renderer-evidence-contract.json` after Storyboard validation. Once the actual
project source is complete, `renderer_project_manifest.py` inventories and
hashes every project source file while excluding only named runtime evidence
outputs. The Director request includes the executable
`capture_hyperframes_runtime_evidence.py` route. It uses Playwright with the
browser returned by `npx hyperframes browser path`, opens the pinned local
project through `file://`, verifies exact media seek/current-time state, and
exports `renderer-export.json` from the painted DOM. Missing Playwright or a
usable browser is `action_required`; request metadata cannot replace execution.
The project then produces one `keyframe-receipt` per compiled event. Each receipt has
exactly four ordered observations: `entrance`, `mid`, `pre_exit`, and
`post_exit`. The snapshot planner's `midpoint` label maps to receipt phase
`mid`; it is not an additional fifth phase.

`keyframe_receipt.py` validates the exact manifest, motion contract, recipe,
source media, target bindings, strict-check and animation-map receipts,
renderer export, phase images, and parity artifact. It rejects extra or stale
project sources, unapproved painted text, guessed/missing targets, connector
drift, clipping, caption overlap, low composite contrast, and any post-exit
remnant. `preview_render_parity.py` compares Studio and final-render snapshots
for every compiled event and all four phases in this mode. Request packets and
authored pass flags cannot satisfy these gates. Missing renderer evidence yields
`action_required`; no upstream HyperFrames API or CLI is inferred.

`animation_map` is the contract name, not an assumed CLI command. Its evidence
must come from the installed HyperFrames operation
`npx hyperframes keyframes <project> --json`, whose diagnostics cover GSAP, CSS,
Anime.js, and path keyframes. A fabricated `animation-map` command is rejected.
`build_keyframe_receipts.py` runs both required commands, preserves their raw
machine output in hash-bound tool artifacts, and verifies both per-event
time-window coverage and ownership by a selector observed inside that event's
painted DOM root. A concurrent global or neighboring-event tween cannot satisfy
the event. The builder then emits the schema-valid receipt set and cannot run
before the scope's parity artifact exists.

The resulting `review/creative-review.html` embeds the aligned media, event seek
markers, source sentence, explanatory value, compiler rationale, target IDs,
four phases, and audio auditions. Its optional interactive mode is default-off,
loopback-only, session-nonce-protected, path-contained, and hash-bound. A
`file://` dashboard gets only a narrowly enabled `Origin: null` preflight;
Director generates the short-lived authorization and CSRF values automatically
for that local session, so the user configures no key. The
UI can create pending correction proposals only. Approval and correction-ledger
replay remain separate explicit commands.

Under the decision-complete model, `quiet_source` and every other non-render
decision remain in the semantic brief and are absent from the Storyboard. Legacy
briefs may still carry quiet rows for compatibility; the motion snapshot planner
excludes them from DOM selectors, motion-sidecar assertions, and four-phase
motion captures.

Every sample and full storyboard must include `visual-vocabulary-audit.json`.
It must explicitly select or reject, with evidence, keyword typography, UI
focus, process, comparison, steps, numeric/result, chapter, PiP/zoom, IP assets,
and quiet source footage. A full-video audit additionally records a decision for
every semantic chapter. This is a relevance gate, not a quota.

Never call project-local scripts that generate a full card/event array. Never
use PIL or FFmpeg translation to impersonate the approved storyboard.

## Aesthetic gate

`scripts/aesthetic_qa.py` requires every applicable criterion to have
`status=pass` and evidence. It also requires HyperFrames check, caption sync,
overlap, overflow, and decode results. In Motion Quality mode, aesthetic review
must cite the exact receipt-bound image for every compiled event and phase;
legacy projects retain their representative review behavior.

Visual snapshot, connector, and anatomy evidence must decode as an image and be
large enough for meaningful review. General evidence is at least 320x180 in
either orientation; anatomy review uses unique `full_frame`, `left_hand`, and
`right_hand` images, with roles required on structured records. A path that
exists but contains placeholder or corrupt bytes fails the gate. Evidence
records may additionally bind SHA-256.

Automated tests validate the gate implementation; they do not supply taste or
visual evidence. A reviewer must inspect actual frames at full size.

## Render authority

Without explicit approval, stop at Studio/snapshot QA. `--approve-final-render`
only unlocks the stage; `--execute-external` additionally allows the stored
HyperFrames command to run. Keep both absent while rendering is paused.

After HyperFrames output exists, `final_compose` uses FFmpeg for the single
automatic universal encode and performs a full decode plus ffprobe report. If
the motion render, selected BGM, full audio plan, FFmpeg settings, schema, or
Director version changes, the compose signature changes and the intermediate is
rebuilt. Two-pass normalization validates target parameters, first-pass data,
post-normalization loudness/true peak/LRA, and exact source/output hashes. If
manual finishing is disabled, that master proceeds directly to `delivery_qa`.
For every project with no independently verified existing caption layer, the
current video-use `master.srt` is hash-bound into the compose signature and
burned as the final picture filter. A `polish_existing` label alone is not
caption evidence; only independently verified existing captions preserve the
established layer.
If enabled, only the revalidated human return becomes the effective universal
output. `delivery_qa` then blocks on the final aesthetic review, speech-dominant audio plan with
provenance, topic/identity/expression-approved cover, and Douyin plus WeChat
Channels reports that reference the exact same file hash.
Identity references and user likeness approval are conditional on the cover
review's `identity_applicable` flag. A generic editorial cover sets it to `false`
and still must pass topic relevance, composition/energy, hash, crop, and safe-zone
checks without fabricating a human identity subject.
The final aesthetic review binds `reviewed_output_sha256`; the cover review,
both platform reports, and delivery contract bind the exact cover SHA-256 as
well. Changing either file invalidates delivery evidence instead of reusing a
path-based pass.

Director state schema v7 binds the exact project and source bytes plus every
completed stage artifact. Resume always re-hashes these inputs, including when
file size and modification time are unchanged, and invalidates the earliest
affected stage and all downstream stages when bytes drift.
Legacy state that lacks contemporaneous byte-bound fingerprints is invalidated from
`inspect`; it is never upgraded by hashing today's files and preserving an old
`complete` flag. A returned manual-finish file is likewise re-hashed on every
resume, so same-size and same-mtime byte changes reopen manual finishing and
delivery QA.

Run `scripts/completion_audit.py` to obtain an honest sixteen-item acceptance
report. A paused full render remains `pending`; it must never be reported as
complete merely because code tests and sample snapshots pass. The audit
independently revalidates full HyperFrames checks, snapshots, preview/render
parity, render authorization, final aesthetics, cover, full decode, video-use
correctness, platform bindings, delivery contract, state artifact records, and
input fingerprints.

## Production governance and editorial regression

`provider_governance` writes deterministic provider decisions and a cost ledger
before any optional paid or local model is considered. It ranks only configured,
available, authorized candidates and records rejected reasons and evidence.
Reservations occur only immediately before an actual adapter invocation, survive
resume, and are reconciled on both success and failure from configured fixed,
result-field, or local-runtime evidence. Delivery rejects unresolved reservations.
An external callback cannot run without current governance artifacts and a selected
provider for every requested task. The ledger is the one deliberately mutable
governance artifact: each valid reserve/reconcile transition is atomic and refreshes
the `provider_governance` stage artifact receipt so resume cannot mistake recorded
spend for tampering. A positive incremental monetary cost is governed as paid even
when the author omitted `requires_paid_call`. Successful reconciliation requires a
provider-result receipt whose result and output-file inventory can be recomputed;
an existing reserved call blocks retry until its real outcome is reconciled.
No provider name is treated as proof that its command, quota, credentials, or
rights are available.

`production_contract` then binds source/project evidence, preservation coverage,
allowed motion families and density ceilings, quiet-interval policy, IP/audio/
cover requirements, provider decisions, derived outputs, and manual handoff.
All later gates validate the current contract hash. `brand_motion_playbook`
compiles profile/project/design-token evidence into machine JSON, CSS variables,
and human-readable design rules without overwriting optical corrections already
approved in the correction ledger.

Sample and full QA each emit `visual-dynamics-qa.json`. The gate checks semantic
event evidence and exact render-subset binding. Legacy briefs retain cadence and
family/structure checks; decision-complete briefs never use fixed gaps, event
minimums, or family ratios as pass/fail quality proxies. The gate also checks
quiet intervals, IP/connector correctness, cue decisions, safe zones, captions,
faces, UI, and canvas bounds. If editorial regression is enabled, sample approval
creates the Golden baseline; the full stage compares structural event/family/
anchor/quiet/IP/connector/SFX/BGM/cover evidence and permits only hash-bound,
approved ledger corrections. Preview approval binds the baseline path and hash;
the Director stage also hashes the baseline itself. Baseline inputs,
implementation, integrity, removed events, full-storyboard corrections, and correction
before-value/target guards are independently revalidated. Mutable cover evidence is
snapshotted at approval, while each correction must target and hash the Storyboard,
semantic brief, audio plan, or cover artifact that actually owns the changed field.

Current Golden schema v2 adds actual renderer evidence: normalized DOM-tree,
motion-phase, and geometry fingerprints plus perceptual hashes of the overlay
crop, not the whole source frame. Sample motion-audio contracts may be retained
in the approved baseline, but they are never reused as proof for a full-timeline
audio plan; delivery audio has its own full-media gates. Schema v1 remains a
truthful legacy compatibility format.

The editorial promise closure joins hook, one publishing title and description,
optional cover, CTA, and proof-event motion copy to the same promise/proof
ledger. Missing surfaces, prohibited claims, stale proof, or mechanical
cross-surface repetition blocks the enabled workflow.

Before Motion Quality sample QA, the Director materializes the actual paired
review media. If the source has no independently verified caption layer and
caption delivery is not disabled, `sample_caption_delivery.py` burns the same
current caption asset into the raw video-use baseline and raw HyperFrames
candidate. It writes both outputs to `work/director/review-media`, verifies a
full decode and duration alignment, and records exact inputs, outputs, caption
hash, and FFmpeg command in `sample-qa/sample-caption-delivery.json`. The raw
HyperFrames sample remains unchanged; derived MP4 files never enter the
renderer project manifest. Without a current receipt, `sample_qa` becomes
`action_required` unless external execution is explicitly enabled.

The caption asset is normally video-use `master.srt`. With explicit semantic
caption treatment, `caption_treatment.py` first proves `captions.json` exactly
matches the current `master.srt` text, segmentation, and millisecond timing,
then joins it to the current sample/full semantic brief, selects only exact
`approved_visible_copy` anchors, and
materializes deterministic ASS and a provenance plan under
`work/director/caption-treatment/{sample|full}`. Sample and final composition
use that ASS through the same FFmpeg subtitle path. Completion audit requires
the canonical full path, current config, measured media canvas and all three
current input hashes, then
deterministically rebuilds the ASS. Styling therefore cannot replace or rewrite
the spoken wording.

Platform geometry remains fail-closed. A semantic-priority product event may
soften exactly one face/hand zone for a bounded time and overlap only when it is
backed by the current semantic brief and Storyboard, points toward a nearby
product target, and proves a clean exit using actual post-exit geometry. The
semantic output window, rather than a renderer-declared duration, enforces the
time cap. Region IDs are counted independently, so left and right hands are two
regions. Product, captions and platform controls remain hard zones. This is
focus-directed composition, not a general permission to cover a person.

`derived_content` is default-off. Clip Factory emits candidates with source and
output times, word IDs, quotes, titles, independence scores, cut reasons, and
orientation decisions. Podcast requires a real verifiable clean PCM WAV and
chapter evidence. Localization can adopt a real authorized hashed provider result
after a prior cost reservation and keeps
word IDs/times, transcript/glossary request hashes, glossary decisions,
back-translation checks, TTS/lip-sync status,
and voice-clone authorization explicit. Missing providers or assets produce
`action_required` rather than fabricated media.

`director.py review` produces a static, local, read-only dashboard bound to the
current hashes. It summarizes stages, action packets, Production Contract,
visual dynamics, provider/cost evidence, correction ledger, Universal MP4,
covers, snapshots, and QA; it never edits the project or approves a gate.

Before render, `full_hyperframes_qa` blocks on a strict HyperFrames report with
lint, runtime, layout, motion-sidecar, and contrast checks plus at least four
existing snapshots reviewed for relevance, variety, overlap, overflow, protected
UI safety, and motion rhythm. It also requires `preview-render-parity.json` for
representative events. At matching Studio/render times, the report checks
position, size, visibility, animation phase, connector count/attachment,
clipping/cropping, and caption occlusion. Reported tolerances may not exceed the
versioned project configuration. Then `authorize-final-render` binds the full
Storyboard, visual-vocabulary audit, command manifest, and verified QA evidence
hashes. A changed artifact invalidates the authorization.

The Director itself records the strict-check and final-render subprocess
receipts. Each receipt binds the exact argv, working directory, exit status,
stdout/stderr logs, command manifest, toolchain, Storyboard, QA/authorization,
and produced bytes. A render file placed on disk without a matching current
receipt remains unverified and cannot satisfy completion audit.

Final technical and platform report reuse is conditional on the production
validators freshly repeating probe, decode, and loudness measurement. Existing
evidence images and current file hashes do not make self-declared measurements
authoritative.

## Schema-v11 execution plane

Schema v11 retains the v10 optional capabilities inside existing stages and does not
change the nineteen-stage order. `init-project`, `doctor`, and `preflight` are
front-door commands. Initialization probes display rotation, orientation,
streams, duration, and existing-edit evidence. Diagnostics are read-only.

Migration adds explicit `identity.mode`, a default-off `motion_quality` block,
and `delivery.required_assets`. The Production Contract binds the identity mode
and whether HongRun assets, personal intro/outro, and first-person brand
expression are allowed. Before `delivery_qa` continues, every required asset
must be complete at its configured deliverable readiness. A request or contract
sidecar may resume work but cannot masquerade as a finished required asset.
An audio plan becomes `asset_ready` only after it validates against the current
Storyboard and every materialized cue/BGM file is included in Director artifact
hashing. An enabled BGM route that produces no authorized asset is
`unavailable`, while an explicit opt-out is `disabled`. Cover validation is
conditional: a configured/produced cover is checked, an enabled release pack
requires one, and an otherwise absent optional cover does not block the single
universal MP4.

P2 remains an adapter plane, not a second automatic editor. OTIO packages bind
the authoritative EDL and report loss; returned human masters still undergo all
fresh delivery QA. Remotion is event-scoped and requires maintained component,
parity, and license files with current hashes. Explicitly enabled optional media
adapters stop at `action_required` until provider, rights, privacy, provenance,
budget, and human-review contracts are materialized. No OpenCut, Jianying, or
other NLE API is inferred.

Semantic confidence sits inside `semantic_brief`; it binds word IDs, times,
screen evidence, grounding, explanatory value, ASR confidence, duplication,
counterexamples, reasons, and rejection reasons. Low-confidence material falls
back to source/caption-only unless a meaning-changing choice requires action.

Interactive review extends the static dashboard. Its HTTP surface is
loopback-only, token/CSRF protected, path allowlisted, and limited to pending
proposals. A separate CLI validation writes the ledger, refreshes pending
preference candidates, and invalidates the owning event/stage. It cannot approve
likeness, sample, render, or publication.

The additive `motion_quality.portrait_brand` plane is default-off for every
migrated v1-v10 project and for non-HongRun, generic, third-party, and explicit
screen-tutorial configurations. WP0 adds only configuration and six-contract
validation: exact profile/energy/motion/sonic/Style-Reel inheritance, current
absolute file/hash references, non-card deterministic fallback, aligned A/B/C
comparison, and HongRun-only approval. Rendering remains owned by HyperFrames
and is not implied by the existence of these contracts.

When explicitly eligible, the Director compiles a source-bound portrait energy
map and additive PBM-01 through PBM-08 motion contracts. It materializes the
reusable portrait component JS/CSS inside each generated HyperFrames project
and binds their hashes in the renderer request. Current WP2 evidence is a
synthetic mechanical browser/CLI fixture: it can prove typed bindings, painted
DOM states, registered-timeline seeking, bounds, caption-lane protection, and
technical preview/render behavior. It does not prove brand taste, recipe value
on real speech, real-project integration, or user approval.

WP3 routes the same current portrait contracts into a separate sonic compiler,
then projects PBM-S01 through PBM-S05 decisions into the existing audio plan.
The local motif library and rights records are content/hash bound; gesture
landings use EDL-mapped output apex times, and missing assets or explicit SFX
disablement become per-event silence. Existing FFmpeg audition, full-band cue
identity, onset, dialogue-relative audibility, true-peak, and sample-mix receipt
validators remain the only production/mix authority. The Director revalidates
the library/registry/variant chain, decodes and remeasures reused off/on
auditions, requires the full cue-bearing sample mix even on non-executing
resume, and fingerprints every nested authority/evidence byte. Short synthetic MP4
evidence proves this integration mechanically, not HongRun brand taste.

WP4 adds an isolated Style Reel planning/review plane without changing the
normal sample stage or automatic master. `style-reel-plan.json` declares the
frozen A/B/C structures; `style-reel-authorities.json` retains the current paths
and hashes for source, video-use EDL, source/output transcripts, semantic brief,
captions, voice stem, audio policy, subject evidence, and profile. The exact
audio plan and portrait-sonic plan are also current hash-bound authorities for
each event audition. The off track must decode to the exact voice-stem event
window; the on track must preserve that voice window and correlate with the
event's authorized cue asset rather than merely differ in bytes.
window must be fully covered by the current EDL, and PBM-07 can enter only from
an independent typed boundary mapped into that window. Three request packets
name HyperFrames as owner while keeping command execution unset and full-video
authority false; an explicit current SHA-256-bound HongRun receipt is required before the
future real-project request can leave the window-confirmation block. After
fixture reels exist, each direction
contract binds the common comparison digest, exact event order, structural
fingerprint, and every entrance/mid/pre-exit/post-exit image. The validator
normalizes those images before measuring large-scale edge/layout structure,
requires material differences between directions, observable within-event
choreography changes, and a clean post-exit. This is a technical fixture gate,
not proof that rendered media is aesthetically good or that HongRun approves it.
fully decodes all A/B/C media, recomputes durations and file hashes, and requires
exactly one video plus one audio stream with the same signature. Synthetic
evidence writes a non-approvable `pending` review; it never writes
`awaiting_user`.

`director.py review` discovers a complete Style Reel package and links a
separate synchronized desktop-primary A/B/C page. The existing loopback review
server remains the only writable surface; its Bearer, CSRF, project-path and
hash checks still produce pending proposals only. The Style Reel page and
multimodal reviewer cannot approve taste or render a full video. The three real
Style Reels must first pass the WP6 runtime, caption-last, voice/mix and parity
gate; only then can an explicit HongRun receipt carrying all six explicit
answers become the first brand-aesthetic approval.

WP7 preserves the original pending review bytes and stores the selected answer
in a separate SHA-256 integrity receipt bound to the complete WP6 package. The
hash detects drift; it is not encryption or an identity-authentication claim.
`portrait_golden.py` then snapshots the selected profile, direction contract,
review media, four-phase evidence, HyperFrames technical refs, sonic/audio
identity, configuration, decision receipt, Git base, and current scripts/tests
tree into a project-local provisional Golden. A separate preference candidate
contains only the explicit direction and six answers; inferred preferences and
automatic application are forbidden. The shared profile is not rewritten, and
the first approval alone cannot change defaults. The second product-demo topic
supplies repeat-use evidence plus an explicit face/hand/product/caption review.
The exact opt-in `luminous_intelligence` route is therefore
`real_project_validated`; the semantic occlusion gate permits only one bounded
face-or-hand soft overlap in an approved product-first window and keeps
product/captions/platform UI hard protected. The shared proposed
profile remains unchanged and production default remains false until a separate
trusted promotion authority is designed and a new HongRun decision is bound to
the current profile, implementation, and retained real-project evidence. That
promotion is not implemented in this release.

The event cache accepts only HyperFrames-owned render/assembly commands with
explicit frame/audio/visual equivalence. Per-event fingerprints avoid binding
unrelated events to the entire Storyboard; final assembly binds ordered segment
hashes. Unsafe or absent contracts fall back to a complete HyperFrames render.

After `delivery_qa` validates one Universal MP4, optional audit/release packaging
may run. Portable diagnostics redact machine paths and secrets. Release packaging
fails closed until privacy, rights, copy, and publication evidence bind the exact
video/cover/copy. Later user-exported metrics bind to that release and remain
advisory; they cannot edit preferences.
