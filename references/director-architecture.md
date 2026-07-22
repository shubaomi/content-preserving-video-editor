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
| Cover/IP/publishing assets | director | evidence-backed cover and provenance |
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
failure boundaries. Optional adapters are disabled by schema-v6 migration and
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
2. `video_use_timeline`
3. `semantic_brief`
4. `hyperframes_storyboard`
5. `audio`
6. `cover`
7. `sample_qa`
8. `preview_approval`
9. `full_hyperframes_storyboard`
10. `full_hyperframes_qa`
11. `final_render`
12. `final_compose`
13. `manual_finish_handoff`
14. `delivery_qa`

Each stage is `pending`, `running`, `action_required`, `failed`, or `complete`.
State writes are atomic. A completed stage is skipped on resume. Resetting one
stage invalidates every downstream stage.

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
`other_nle` creates a human-facing action packet only after `final_compose`; it
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

## HyperFrames contract

Require `renderer=hyperframes`, all five HyperFrames capability Skills, and
`motion_output=hyperframes_render`. Every event's five-field signature must be
unique when it claims to be a distinct variant.

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

Director state schema v5 binds the exact project and source bytes plus every
completed stage artifact. Resume always re-hashes these inputs, including when
file size and modification time are unchanged, and invalidates the earliest
affected stage and all downstream stages when bytes drift.
Legacy state that lacks contemporaneous v5 fingerprints is invalidated from
`inspect`; it is never upgraded by hashing today's files and preserving an old
`complete` flag. A returned manual-finish file is likewise re-hashed on every
resume, so same-size and same-mtime byte changes reopen manual finishing and
delivery QA.

Run `scripts/completion_audit.py` to obtain an honest thirteen-item acceptance
report. A paused full render remains `pending`; it must never be reported as
complete merely because code tests and sample snapshots pass. The audit
independently revalidates full HyperFrames checks, snapshots, preview/render
parity, render authorization, final aesthetics, cover, full decode, video-use
correctness, platform bindings, delivery contract, state artifact records, and
input fingerprints.

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
