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

## State machine

Before the state machine leaves `inspect`, resolve input mode from explicit
project evidence or a cached `input-mode-evidence.json`. When neither exists,
run the conservative existing-edit analyzer. Bind the decision to source size,
mtime, and SHA-256 so a replaced source cannot inherit an old mode. Strong
existing-edit markers select `polish_existing`; absent strong evidence selects
`preserve`.

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

When a semantic brief is supplied, Storyboard events must map one-to-one in
approved order. The mapping binds semantic event ID, anchor, transcript word
IDs, source/output timing, viewer takeaway, and any approved visible copy.
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

Use HyperFrames Core and Creative rules before HTML. Run HyperFrames check and
multi-phase snapshots. Studio is the editable review surface. An actual
sample command set remains stored in `hyperframes-commands.json`. After approval,
create a different full-duration project and store its render authority in
`full-hyperframes-commands.json`. The final command must execute with that
project as `cwd`; the 60–90 second sample can never become the final render by
path reuse.

Every sample and full storyboard must include `visual-vocabulary-audit.json`.
It must explicitly select or reject, with evidence, keyword typography, UI
focus, process, comparison, steps, numeric/result, chapter, PiP/zoom, IP assets,
and quiet source footage. A full-video audit additionally records a decision for
every semantic chapter. This is a relevance gate, not a quota.

Never call project-local scripts that generate a full card/event array. Never
use PIL or FFmpeg translation to impersonate the approved storyboard.

## Aesthetic gate

`scripts/aesthetic_qa.py` requires every criterion to have `status=pass` and
evidence. It also requires HyperFrames check, caption sync, overlap, overflow,
and decode results plus four phase snapshots for every reviewed visual event.

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
If enabled, only the revalidated human return becomes the effective universal
output. `delivery_qa` then blocks on the final aesthetic review, speech-dominant audio plan with
provenance, topic/identity/expression-approved cover, and Douyin plus WeChat
Channels reports that reference the exact same file hash.
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
event evidence, cadence without density gaming, family/structure diversity,
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

## Schema-v9 P0/P1/P2 execution plane

The v9 additions are optional capabilities inside existing stages and do not
change the nineteen-stage order. `init-project`, `doctor`, and `preflight` are
front-door commands. Initialization probes display rotation, orientation,
streams, duration, and existing-edit evidence. Diagnostics are read-only.

Semantic confidence sits inside `semantic_brief`; it binds word IDs, times,
screen evidence, grounding, explanatory value, ASR confidence, duplication,
counterexamples, reasons, and rejection reasons. Low-confidence material falls
back to source/caption-only unless a meaning-changing choice requires action.

Interactive review extends the static dashboard. Its HTTP surface is
loopback-only, token/CSRF protected, path allowlisted, and limited to pending
proposals. A separate CLI validation writes the ledger, refreshes pending
preference candidates, and invalidates the owning event/stage. It cannot approve
likeness, sample, render, or publication.

The event cache accepts only HyperFrames-owned render/assembly commands with
explicit frame/audio/visual equivalence. Per-event fingerprints avoid binding
unrelated events to the entire Storyboard; final assembly binds ordered segment
hashes. Unsafe or absent contracts fall back to a complete HyperFrames render.

After `delivery_qa` validates one Universal MP4, optional audit/release packaging
may run. Portable diagnostics redact machine paths and secrets. Release packaging
fails closed until privacy, rights, copy, and publication evidence bind the exact
video/cover/copy. Later user-exported metrics bind to that release and remain
advisory; they cannot edit preferences.
