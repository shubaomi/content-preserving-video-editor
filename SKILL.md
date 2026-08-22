---
name: content-preserving-video-editor
description: Orchestrate preservation-first editing or nondestructive polishing of talking-head, screen-recording, tutorial, interview, product-demo, and already-published videos. Use when the user asks to intelligently edit while keeping most source content, add accurate natural captions, enrich footage with relevant HyperFrames motion/IP visuals/SFX/BGM, create a personal cinematic cover and publish package, or run a reusable one-shot workflow that defaults to one universal video for Douyin and WeChat Channels. This Skill owns policy, orchestration, personal IP, cover, platform adaptation, QA, and delivery; it must delegate transcription/edit timing to video-use and creative motion design/rendering to HyperFrames.
---

# Content-Preserving Video Director

Act as the total director, not as a monolithic editor. Protect source meaning,
route each professional task to its owner, block weak artifacts, and deliver one
auditable pre-publish package.

## Non-negotiable roles

- Let this Skill own preservation policy, orchestration, personal IP/Profile,
  cover and publishing assets, platform adaptation, QA, and delivery.
- Load `/video-use` for media analysis, word transcription, EDL, edit timeline,
  cut/audio boundaries, output-timeline subtitle mapping, and edit correctness.
- Load `/hyperframes`, `/hyperframes-core`, `/hyperframes-creative`,
  `/hyperframes-animation`, and `/hyperframes-cli` for creative direction,
  design tokens, motion storyboard, distinct visual structures, Studio editing,
  checks, snapshots, and actual motion rendering.
- Use FFmpeg only for final composition, audio mix, encoding, full decode, and
  genuinely simple visually equivalent primitives.
- Treat OpenCut or another NLE only as an optional human-facing finishing surface.
  Do not require it, automate it, or claim MCP, Editor API, CLI, or headless
  rendering capabilities. Keep the automatic master immutable during handoff.
- Never use PIL static text cards plus FFmpeg translation as a substitute for
  HyperFrames. Never call a HyperFrames preview the final motion render.
- Never let a project script hardcode the full video's captions or motion-event
  list. Store semantic decisions in evidence-backed JSON artifacts.

Read [director-architecture.md](references/director-architecture.md) before
execution. Read [config-schema.md](references/config-schema.md) when resolving
configuration and [quality-gates.md](references/quality-gates.md) before QA.

## Start with one guided intake

Do not require the user to remember a long invocation prompt. When a user says
they have a video to edit, reuse every answer already present in the request or
current project, then ask once for only the missing items in one compact batch:

1. absolute source-video path;
2. identity and rights declaration: `self`, `third_party`, or `generic`, plus
   separate confirmation of editing authorization and, when a publishable
   delivery is requested, publication authorization;
3. desired execution point: analyze only, create a sample first, or resume a
   full render that already has a current sample approval;
4. for eligible HongRun self-recorded portrait footage, whether to opt in to
   the current HongRun Profile/portrait-brand direction;
5. whether the expanded layered manual-NLE package is also needed. The normal
   automatic delivery already includes the standard editor-neutral repair kit;
   do not ask the user to opt in to SRT/ASS/caption-free-candidate delivery.

Default title, `video_id`, publishing copy, cover copy, content-type detection,
platform target, and technical settings to automatic generation unless the
user overrides them. Do not ask the user to classify the video as talking head,
product demo, screen tutorial, interview, or mixed footage. Treat any supplied
type as a hint only; determine the effective input mode and content format from
media, transcript, scene, subject, UI, product/action, and existing-edit
evidence after inspection. Report the evidence-backed classification before
creative planning, and pause only when evidence conflicts with the identity or
rights declaration or cannot support a safe route.

For a new or changed source, `sample_first` is the safe default and the only
route to a new full render. A request for direct full rendering is valid only
when the project already has a current, hash-bound sample approval and explicit
final-render authorization. Never reinterpret a preference for convenience as
permission to bypass the sample, aesthetic, likeness, rights, or publication
gates.

After the one-batch intake is complete, show a short intake summary with the
resolved source, identity/rights, requested execution point, automatic fields,
Profile choice, and delivery choice. Then proceed autonomously until the next
real user gate. Do not repeat answered questions after resume or context
compression. Read [guided-intake.md](references/guided-intake.md) for the exact
question and defaulting protocol.

## Resolve the project

Resolve configuration in this order:

1. Explicit project/profile paths in the request.
2. `project.yaml` beside or above the supplied video.
3. `.video-profile.yaml` in the project.
4. `PERSONAL_IP_PROFILE`.
5. Ask only if discovery still fails.

Keep one isolated directory per video. Keep reusable identity assets under the
profile `shared/` tree and video-specific assets inside that video's project.
Read [project-layout.md](references/project-layout.md) when initializing or
moving projects.

Load legacy project YAML through the versioned in-memory migrator. Never rewrite
an existing `project.yaml` merely to add defaults. New projects use project
schema version 11; migrated v1-v10 projects receive disabled optional adapters,
disabled manual finishing, disabled HongRun portrait-brand v2, and the current
preview/render parity tolerances in memory.

## Use the single entry

Run the director from the Skill root:

```powershell
python scripts/director.py init-project --root <videos-root> --video-id <id> --source <video> --preset auto
python scripts/director.py doctor --out <doctor.json>
python scripts/director.py preflight --project <project.yaml> --out <preflight.json>
python scripts/director.py run --project <project.yaml> --until sample_qa
python scripts/director.py resume --project <project.yaml>
python scripts/director.py status --project <project.yaml>
python scripts/director.py next --project <project.yaml>
python scripts/director.py review --project <project.yaml>
python scripts/director.py review --project <project.yaml> --interactive
python scripts/director.py apply-correction --project <project.yaml> --proposal <pending.json> --approved-by <name>
python scripts/director.py open-preview --project <project.yaml>
python scripts/director.py open-studio --project <project.yaml>
python scripts/director.py approve-sample --project <project.yaml> --approved-by <name> --publish-willingness yes|no|unsure --preference baseline|candidate|tie --review-reason <reason>
python scripts/director.py authorize-final-render --project <project.yaml> --authorized-by <name>
python scripts/director.py deliver --project <project.yaml>
python scripts/director.py import-metrics --project <project.yaml> --input <user-export.json>
```

`init-project` never overwrites an existing project. `doctor` and `preflight`
are read-only and never install tools, expose environment-variable values, or
approve a gate. Interactive review is default-off and loopback-only. When it is
explicitly enabled, Director generates short-lived in-memory session nonces;
users do not create, configure, type, or retain a key. The browser writes only
pending hash-bound proposals. A `file://` page may reach only
the explicitly enabled loopback proposal endpoint; CORS preflight never bypasses
Bearer, CSRF, project-path, or SHA-256 checks. Only `apply-correction` may append an
explicitly approved correction ledger entry.

The state lives at `<project>/work/director/director-state.json`. Resume with the
same `run` command. Do not manually assemble the legacy script collection.

When `action-required.json` appears, execute exactly the capability owner named
there, create the expected artifact, and resume. Do not bypass a stage by marking
it complete. A failed stage must retain its exact error and artifacts.

`inspect` must write `capability-inventory.json` and
`toolchain-compatibility.json`. Each capability records its owner, version,
dependencies, inputs, outputs, optionality, cache key, failure fallback,
configuration route, and actual maturity. Use only `documented`,
`director_integrated`, `fixture_validated`, `real_project_validated`, and
`production_default`. Never describe `documented` work as part of the one-shot
workflow, jump maturity levels, or promote fixture evidence as real-project
evidence. Do not silently
install or update video-use, HyperFrames, media-use, OpenCut, or Remotion.
The compatibility report must resolve all five required HyperFrames Skills
individually; one base `hyperframes` directory is not evidence that core,
creative, animation, and CLI contracts are present.

Do not pass `--approve-final-render` or `--execute-external` until the 60–90
second sample and its aesthetic QA have passed and the user has approved full
rendering. When the user pauses rendering, keep all render stages disabled.
Record approval only through `approve-sample`; it binds the exact Storyboard,
aesthetic review, gate report, and, in Motion Quality mode, paired creative
review hash. The approving person must provide publish willingness and a
baseline/candidate/tie preference; agent and multimodal identities cannot author
that decision, and the approval needs a non-empty review reason. Any later sample or bound evidence change invalidates the
approval and requires another explicit review.

For P0 real-canary promotion, materialize each authorized 30–90 second canary
with `scripts/build_real_project_validation.py`. The builder derives media
metadata and every SHA-256 from files on disk, binds the current project config,
Git commit, and scripts/tests source-tree hash, and refuses to write a receipt
when any automated, multimodal, or named-user gate is incomplete or stale.
Landscape and portrait receipts remain separate; one passing orientation never
promotes the workflow by itself.

## Preserve content and select mode

Let the director detect `preserve` versus `polish_existing` from the project and
source evidence.

An explicit source declaration wins. Without one, do not silently default to
`preserve`: run the conservative existing-edit analyzer, cache
`input-mode-evidence.json` against source size, mtime, and SHA-256, and select
`polish_existing` only from strong evidence such as an embedded subtitle stream
or independently verified burned captions. Pixel-density heuristics may create a
review candidate, but must never suppress captions or select polish mode by
themselves because document, dashboard, and diagram text can look identical.
Select `preserve` when no verified marker is found. A changed source invalidates
the cached decision.

- `preserve`: remove only setup footage, true silence, and exact repetition by
  default. Require confirmation for semantic deletion longer than 5 seconds or
  continuous removal longer than 15 seconds.
- `polish_existing`: preserve the established picture and audio timeline. Add
  improvements incrementally; do not stack a second BGM or duplicate burned-in
  captions.

Silence, low motion, or missing subtitles are evidence, never deletion
permission. Preserve the source tail unless an explicit, reviewed EDL explains
its removal. Read [existing-edit-polish-mode.md](references/existing-edit-polish-mode.md)
for already-edited material and [editing-backend-policy.md](references/editing-backend-policy.md)
for cut rules.

## Enforce video-use captions and timeline

Require a video-use-compatible top-level `words` transcript. A cached local word
transcript may be adopted only as a schema conversion that changes neither text
nor timing and records hashes. Never adopt summary captions or broad ASR segment
text as the word transcript.

The director must not author an EDL and label it as video-use work. When an EDL
is missing, write an evidence-backed preservation request and hand the stage to
video-use. Then validate video-use ownership, source/range bounds, word-boundary
padding, audio fades, tail coverage, and deletion approval before continuing.

Require `media-analysis.json` with ffprobe inventory and at least three actual
video-use timeline views, plus `edit-correctness-preflight.json` bound to the EDL
and transcript hashes. After final composition, require a separate
`final-edit-correctness.json` bound to the universal MP4 hash, expected/actual
duration, every real cut boundary, and first/midpoint/final timeline views.

Map every retained word to the output timeline using the owning EDL. Preserve
spoken wording; allow only audited spelling or terminology corrections with
evidence. Never publish a summary or rewritten sentence as a subtitle. Group
mapped words into natural phrases instead of one-character flashes.

Sentence punctuation wins over pause-based incomplete-tail heuristics: a token
ending in `。！？.!?` closes that sentence even when its last spoken character is
`的`, `和`, or another connector. Use punctuation internally for segmentation.
Default the displayed style to `spoken_clean`: hide commas, full stops,
semicolons, and colons while retaining question/exclamation tone. Use `source`
or `none` only when the project explicitly asks for it.

Require `caption-sync-report.json` to pass sampled lead/tail timing and overlap
checks. Use 30–100 ms cut context and about 30 ms fades at new audio boundaries.
Keep transcripts cached and subtitles last in the edit stack. For source-first
or preservation work without a verified existing caption layer, `final_compose`
must burn the current video-use `master.srt` after the HyperFrames picture. Its
path and SHA-256 are part of the compose signature. A generated SRT sitting on
disk is not proof that captions reached the Universal MP4.

## Author meaning before motion

Before semantic planning, run `evidence_acquisition`. Bind its bundle to the
exact source and word-transcript hashes. Record display rotation/aspect,
representative frames, scenes, subject/face/UI/caption regions, OCR when
enabled, design tokens, and existing edit/audio/caption/cover evidence.
Default frame evidence must use bounded full-duration coverage rather than five
fixed percentage samples. Record every frame's timestamp, owned coverage window,
hash, and sampling policy so an event cannot cite an unrelated part of a long
video. Fail closed if a managed extraction returns fewer frames or different
timestamps than requested, and require every timestamped target frame cited by
an event to have overlapping ownership coverage and an actual capture timestamp
no more than 15 seconds from that event. A capped long-video sample that cannot
meet that distance is blocked until an event-specific supplemental frame is
supplied; the built-in sampler does not yet capture that frame automatically and
must never widen fictional ownership. Keep expensive scene, tracking, and OCR
adapters optional.
PySceneDetect, MediaPipe, and PaddleOCR are optional command adapters and remain
disabled for legacy projects unless explicitly enabled.

Have the LLM read the raw word transcript and necessary evidence frames. First
identify chapters, claims, causal links, contrasts, steps, numbers/results,
demonstration actions, and emotion. Then write `semantic-brief.json` with direct
transcript word IDs, quoted evidence, source times, frame evidence, a relevance
rationale, and the intended viewer takeaway. When `motion_quality.enabled=true`,
use semantic schema v3 and `opportunity_model=decision_complete_v1`. Record every
meaningful opportunity in source/output order with exactly one of `render`,
`annotation`, `caption_only`, `reuse_source`, `quiet_source`, or
`action_required`, plus a non-empty decision rationale. `action_required` must
pause the stage; it is not a synthetic decision.

When `cover.editorial.enabled=true`, also write an evidence-backed
`cover_direction` with a short headline, one to three highlight terms, eyebrow,
optional subtitle, tone, visual concept, subject side, visual route, and existing
semantic event IDs. Do not invent a cover claim from generic keywords. Read
[generative-cover-workflow.md](references/generative-cover-workflow.md) before
producing an enhanced cover.

After a semantic brief is approved, treat it as an immutable meaning contract.
With the decision-complete model, the Storyboard contains exactly the ordered
subset whose decision is `render`; non-render opportunities stay in the brief
and must not be serialized as motion. Each rendered event inherits its semantic
ID, anchor, transcript word IDs, source/output window, frame evidence, rationale,
viewer takeaway, and approved visible-copy list. Legacy schema-v1/v2 briefs keep
their existing one-to-one compatibility behavior. A renderer may change layout and animation;
it must derive an explicit `visible_copy_manifest` exactly from that approved
copy. All other strings must be approved copy or an explicitly allowed metadata
path; nested authority fields and arbitrary render props are rejected. Missing,
reordered, unrelated, or extra-copy mappings block HyperFrames QA. Final
rendered DOM/OCR comparison remains a separate HyperFrames visual-review gate;
the JSON contract does not claim to inspect pixels by itself.

With Motion Quality enabled, evidence acquisition also writes
`adaptive-layout-constraints.json`. Portrait talking-head footage protects
verified face, hand, and caption regions; landscape screen footage protects
verified critical UI and captions. Missing required region evidence produces a
`caption_only`/`action_required` fallback and never an invented safe zone.
Each Storyboard render event must explicitly set `target_binding_required` and
`target_binding_ids`. Targetless recipes use `false` plus an empty list;
source-bound focus/highlight/callout/connector recipes require resolved,
schema-valid binding files in the sample or full target-binding directory.
Bindings are checked against the semantic event, source/output windows,
visible/lost observations, state signatures, evidence hashes, and active
windows. Scene, route, modal, scroll, zoom, layout, visibility, and rotation
changes invalidate static geometry. A lost target exits, uses an explicitly
declared fallback, or pauses for action; it never holds a stale box.

The Director-owned Motion Quality Engine compiles the complete decision set to
`motion-design-contract.json` before HyperFrames authoring. It validates the
seven frozen contract schemas and selects only from the versioned
`references/motion-recipes-v1.json` registry. Selection uses the approved
semantic role and structured form, never transcript keywords, a time cadence,
an event/family quota, random template rotation, or SFX availability. Every
recipe declares entrance/explain/hold/exit poses, runtime, orientation layout,
proof requirements, cost, and a deterministic fallback. Unmet target, identity,
layout, state, evidence, or advanced-runtime preconditions follow that fallback
chain or become `action_required`; they never create guessed geometry.
HyperFrames receives `hyperframes-choreography.json` and may implement only the
compiled recipe/copy/windows/bindings. A Storyboard that changes the recipe,
choreography fingerprint, semantic parent, or target bindings fails before QA.
Sample and full scopes keep separate motion contracts and choreography files.

Content format is a first-class motion input. Screen/product footage may use
target-relative focus boxes, connectors, comparison panels, and process rails.
Portrait talking-head footage uses a separate expressive grammar built from
face-safe kinetic typography, rhythmic word emphasis, side rails, depth/light
accents, semantic cutaways, and chapter energy changes; it must not fall back to
floating dashboard cards merely because those templates exist. The generic
content-format grammar remains `fixture_validated`. The exact opt-in HongRun v2
`luminous_intelligence` route is `real_project_validated` for two materially
different, explicitly reviewed portrait topics. The second review permits one
bounded face-or-hand soft overlap only during an independently approved
product-first explanation window; product, captions, platform UI, and every
other event remain hard protected. This is not a promise of
CapCut/Jianying-equivalent taste and does not make the route a production
default. A technically publishable sample may still fail the user's brand-taste
gate; record that reservation and do not promote it away.

Record a separate opening-hook decision for every video. Select a duplicated
2–6 second cold open only when a transcript- and frame-backed excerpt is
self-contained, immediately specific, and has clean word/visual boundaries.
Otherwise record `not_selected` with evidence. In `preserve` or
`polish_existing`, a hook proposal stays separate from the approved EDL until
its duplication/reorder is explicitly approved; never treat retention scoring
as permission to alter chronology.

Use deterministic rules only to reject:

- low-information anchors such as `打开`, `点击`, `添加`, or `然后` alone;
- repeated anchors inside cooldown;
- subtitle repetition, overlap, overflow, collision, or filler;
- unsupported long quiet gaps without stored source-activity frames.

Do not use keyword scoring, fixed cadence, minimum event counts, or family
quotas as semantic authors. Density follows the recorded opportunity decisions;
an evidenced quiet/source/caption decision is complete coverage, not a missing
effect.

## Require real HyperFrames variety

Route the task through `talking-head-recut`, `embedded-captions`,
`general-video`, or `motion-graphics` from content evidence. HyperFrames remains
the composition owner. An explicitly configured media-use/Registry/Catalog
adapter may resolve evidence-backed `asset_request` entries; missing commands
must be reported as unavailable, never represented as downloaded assets.
Pass requests through the generated, hash-bound
`work/director/media-catalog-requests/<request-set-sha256>.json`; each request
set has an immutable manifest so concurrent jobs cannot overwrite one another.
Require the adapter command to accept its
`{request_manifest}` placeholder and require every decision to echo the request
hash, query, purpose, asset hash, provenance, and rights basis. Never allow an
asset request to override its canonical semantic event ID.
Remotion may render only named events backed by existing, absolute, hash-bound
React component files plus current hash-bound parity and license records. The
Director recomputes decodable reference/render image differences and requires
the component manifest to bind `visual_only` plus `audio_policy: forbidden`, or
matching bound audio bytes. Legacy path
strings, arbitrary attachment bytes, self-declared deltas, and boolean parity
are not execution evidence. It
must not replace HyperFrames or cause a second full-video render.

Have HyperFrames translate the approved brief into `frame.md`, `storyboard.json`,
and `index.html`. Each declared variant must differ in all five dimensions:

- DOM/component structure;
- information hierarchy;
- layout archetype;
- animation choreography;
- content use case.

Changing a label, icon, color, border, or entrance direction does not create a
new structure. Select meaning-appropriate treatments across keyword typography,
UI focus/cursor annotation, process paths, comparison panels, step rails,
numeric/result emphasis, chapter transitions, PiP/local zoom, integrated IP
assets, and intentional quiet source footage. Do not force every category into
every video.

Follow HyperFrames' design-spec, video-composition, timing, seek-safety, layout,
and direct-child media rules. Keep layout transforms separate from animation
transforms. Use `npx hyperframes check`, representative multi-phase snapshots,
and Studio preview. Final motion must come from `npx hyperframes render` after
approval; FFmpeg may then mix or encode it but may not replace its creative work.

When `motion_quality.enabled=true`, request and validate renderer evidence for
every compiled render event, not only representative events. After the editable
project sources are final, build `renderer-project-manifest.json` with
`scripts/renderer_project_manifest.py`; any later project-source edit or added
source file invalidates it. Runtime evidence directories and files are excluded
from that source inventory. The project runtime must export
`renderer-export.json` from the actual painted DOM and one hash-bound
`keyframe-receipts/<event-id>.json` at `entrance`, `mid`, `pre_exit`, and
`post_exit`. The snapshot plan calls its held phase `midpoint`; the frozen
keyframe receipt schema calls the same phase `mid`.

Execute the Director-provided
`scripts/capture_hyperframes_runtime_evidence.py` request to create the runtime
export. It opens the local project with Playwright, resolves the browser through
`npx hyperframes browser path`, verifies the media reached each exact requested
time, and records painted DOM/source-state evidence. Keep project runtime
dependencies local and pinned; the capture uses `file://` with explicit local
file access so a range-incompatible ad-hoc HTTP server cannot silently leave the
video at frame zero. Missing Playwright or browser binaries produce
`action_required`, never an authored export. The receipt's logical
`animation_map` field is backed by the real
`npx hyperframes keyframes <project> --json` operation; do not invent an
`animation-map` CLI command.
After Studio/render parity exists, execute the companion
`scripts/build_keyframe_receipts.py` request. It runs strict check and keyframe
diagnostics itself, proves each render event owns at least one real motion
interval whose HyperFrames target selector was observed inside that event's
painted DOM root, and writes schema-valid hash-bound receipts. A simultaneous
global or other-event tween does not count. Hand-authored tool JSON or a
keyframe dump that does not cover the event cannot satisfy the gate.

Each receipt binds the exact project manifest, motion-design contract, recipe,
source media, target bindings, strict-check result, animation-map result,
renderer export, snapshots, and preview/render parity. Recompute visible text,
geometry, target and connector observations, clipping, caption overlap, source
state, and source-composited contrast from these artifacts. Post-exit must leave
no overlay or target geometry. Request JSON, screenshot filenames, and authored
pass booleans are not renderer evidence. Missing, corrupt, stale, midpoint-only,
or non-parity evidence makes the owning stage `action_required`.

This is a project-side export contract; it does not claim a new upstream
HyperFrames CLI or modify upstream source. Load `hyperframes-keyframes` only
when a selected advanced recipe declares that Skill requirement. This path is
`fixture_validated` until both current real canaries and the required user
creative review pass.

Fix project-specific optical alignment, connector endpoints, crop focus, and
content density in the generated HyperFrames project. Review the held midpoint
at full frame size as well as entrance/exit phases; automated overflow checks do
not prove optical balance. Reduce a panel whose useful content occupies only a
minor part of its surface unless the empty region is an intentional, evidenced
quiet zone. For every generated human or personal-IP visual, also inspect the
full-size source and close crops of both hands before integration. Require the
intended limb count and continuous shoulder–elbow–wrist–hand topology; reject
extra, duplicated, fused, detached, or ambiguously connected limbs even when the
thumbnail looks acceptable. Do not modify the upstream HyperFrames Skill for one video's CSS or
SVG tuning. Escalate upstream only when the same defect reproduces in a minimal
composition and belongs to its renderer, Studio, lint, check, or snapshot
contract. Likewise, fix caption grouping in this Skill's video-use bridge;
change upstream video-use only when its owned transcript, EDL, mapping helper,
or cut renderer is demonstrably wrong outside the adapter.

Any visual that claims a route, branch, comparison, dependency, or flow must
declare a connector contract in the Storyboard: required relation count,
from/to semantic nodes, and the intended attachment edge. Require one held
full-frame snapshot per such event plus a per-event geometry review confirming
the observed count, attached endpoints, optical alignment, and absence of
clipped paths. Boolean pass claims are insufficient: require a hash-bound
`browser_dom_geometry_v1` receipt with node boxes, path endpoints, attachment
edges, canvas dimensions, and a maximum eight-pixel endpoint tolerance that the
Director recomputes. A single line that reaches only one of several declared
targets is incomplete even when HyperFrames reports zero overflow.

Any effect that claims to focus, highlight, call out, or overlay a region of the
source picture must also declare a `target_region_contract`. Bind target IDs,
the active render selector, active source/output window, minimum useful-content occupancy, tracking
mode, and hash-bound entrance/midpoint/pre-exit source-state frames. Do not let
an event's broad spoken interval force its geometry to appear before the target
UI state exists; motion snapshots use the narrower active geometry window.
Static or scene-bounded geometry that crosses a visible source-state change,
an empty highlight region, an orphan line, or a target with too little useful
content is blocking. Use a shorter scene-bounded window or explicit keyframed
tracking instead of leaving a stale box on screen.
The same geometry receipt must record each target's overlay box and useful
content box; the Director recomputes intersection occupancy instead of trusting
`minimum_observed_useful_content_ratio` or pass booleans.

For every non-quiet overlay, compare the held midpoint with the same source
state after the overlay exits. Store foreground color, panel color/alpha, and
overlay box in `composite_contrast`; recompute the worst representative
source-composited contrast and require at least 4.5:1. HyperFrames' internal DOM
contrast check does not prove readability over the underlying video.

Keep sample and full projects separate. The approved 60–90 second sample lives
at the configured sample project; the final composition must be authored in a
different full-duration project, cover at least 95% of the video-use EDL output
duration, and carry a ten-category `visual-vocabulary-audit.json`. Every category
must be selected with event evidence or rejected with a content-specific reason.

## Gate a sample before a full render

Create a 60–90 second sample covering the highest-risk selected structures and
representative quiet footage. Do not manufacture four events or structures when
the content does not justify them. With Motion Quality enabled, capture
entrance, midpoint, pre-exit, and post-exit evidence for every compiled render
event; legacy projects retain representative sampling.

Run technical QA and a separate blocking aesthetic review. Tests do not count as
aesthetic approval. Require direct relevance, additional explanatory value,
correct keyword focus, layout variety, speech-synchronous motion, no caption or
platform-UI occlusion, no unjustified face/hand/product occlusion, integrated IP
visuals, fitting SFX, natural energetic cover identity, and no unexplained long
visual stagnation. In an evidence-bound `product_emphasis` window, one face or
hand region may be soft-protected instead of absolutely forbidden, but only
within the configured overlap/time limits, near the hard-protected product,
with a clean exit proven by post-exit geometry. The current semantic brief and
Storyboard must resolve the focus ID and output window; a renderer's own
`approved`, duration, or clean-exit fields are not authority. Count distinct
region IDs, so two hands are never collapsed into one exception. Captions and
the current primary product remain hard
protected; outside that window faces and hands remain hard protected.

Snapshot, connector, and generated-human anatomy evidence must be a real,
decodable image at reviewable resolution. File existence or placeholder bytes
never constitute visual evidence; hash-bound evidence records are preferred.
General review frames must be at least 320x180 (in either orientation). Anatomy
review requires three unique images for `full_frame`, `left_hand`, and
`right_hand`; structured records must declare the role and hash.

Motion Quality sample approval additionally requires
`sample-qa/creative-review.json` and `review/creative-review.html`. The review
binds distinct aligned 60–90 second baseline/candidate media, the exact compiler
contract and Storyboard, every event's four-phase receipts, passing automated
gates, SFX-off/on and optional BGM-off/on auditions. It starts pending. Hash
drift marks it stale and clears any prior decision. The page can submit only
pending correction proposals; it cannot approve the sample or mutate artifacts.

When the sample audio plan contains `cue` decisions, the Director must first
mix every current, hash-bound SFX asset into the complete HyperFrames candidate
under `work/director/review-media` and write
`work/director/sample-qa/sample-review-mix.json`. The receipt
binds the raw render, audio plan, ordered event/asset inventory, FFmpeg command,
mixed output, and full decode. Missing, reordered, replaced, or stale cue bytes
invalidate the review candidate. An `intentionally_silent`-only plan keeps the
raw HyperFrames candidate and does not create a fictional mix.

When captions are required and no existing caption layer is independently
verified, do not review the raw HyperFrames `sample-preview.mp4`. Apply the same
hash-bound caption asset to both baseline and candidate, write the two
captioned review files under `work/director/review-media`, fully decode them,
and bind the exact FFmpeg subtitle filters in
`sample-qa/sample-caption-delivery.json`. Never write derived review media into
the HyperFrames project because it would invalidate renderer-source receipts.
Changing the caption track or either review file invalidates paired approval.
The candidate input to this caption-last step is the verified full-sample SFX
mix when cue decisions exist; captions must never be burned before that mix.
The default caption asset remains video-use `master.srt`. An explicitly enabled
`editing.caption_treatment.mode=semantic_emphasis` compiles current captions and
the current semantic brief into a deterministic `master.ass` plus
`caption-emphasis-plan.json`. It may emphasize at most two source-matching
semantic anchors per phrase with bounded brand colors, weight, and 105–120%
scale. For narrow portrait canvases it may add deterministic display-only ASS
line breaks for long phrases; the authoritative text and timing do not change.
For a sample beginning later than the source, the Director first derives a
hash-bound, source-faithful rebased `captions.sample.json` and `master.sample.srt`;
it must never burn the full-source SRT directly onto the shorter review media.
An explicitly enabled semantic treatment requires caption-last delivery for the
sample even when optional motion-quality gates remain disabled.
Each anchor must be an exact `approved_visible_copy`. Before rendering,
`captions.json` must match `master.srt` text, segmentation, and millisecond
timing; completion rebuilds the canonical ASS and plan byte-for-byte from
current project inputs, measured canvas, and config. Enabled styling cannot
silently fall back to plain SRT, and default-off projects cannot self-enable it.
It may not paraphrase, add a claim, highlight a non-matching word, animate
character-by-character, or change timing/segmentation. `master.srt` remains the
hash-bound text authority and legacy projects remain `plain`.

Only after the sample passes and the user approves may the director render the
full HyperFrames motion and final universal media.

The full chain after approval is `full_hyperframes_storyboard` →
`full_hyperframes_qa` → `final_render` → `final_compose` →
`derived_content` → `manual_finish_handoff` → `delivery_qa`. The derived-content
stage is a no-op unless an evidence-bound clip, podcast, or localization module
is enabled. The manual stage is a no-op unless
`delivery.manual_finish.enabled=true` with backend `opencut` or `other_nle`, so
the default one-shot workflow is unchanged. `full_hyperframes_qa` requires
strict HyperFrames checks, reviewed snapshots, and Studio/render parity at
matching times. Motion Quality projects require all compiled events and all four
phases; legacy projects retain representative parity. The report compares
geometry, visibility, animation phase, connectors, clipping/cropping, caption
occlusion, and the exact receipt-bound image hashes within the project's
configured tolerances. Failure blocks render authorization and final delivery.
Authorize rendering only through `authorize-final-render`; the authorization is
bound to the exact full Storyboard, vocabulary audit, commands, and QA evidence,
and expires when any of them changes. The final stage requires the actual cover and
identity review, final audio plan and provenance, final aesthetic snapshots, a
full decode report, and two platform reports that validate the same universal
file hash.

Schema v11 migrates v1–v10 projects in memory without rewriting user YAML. It
requires explicit `identity.mode`, keeps `motion_quality` and advanced runtimes
off for migrated projects, and records `delivery.required_assets`. Before
`delivery_qa`, reject any required stage that is only `contract_ready`.
`third_party` identity forbids HongRun face/IP assets, personal intro/outro, and
first-person brand expression. `caption_delivery: none` is the only caption
asset opt-out and must remain an explicit evidenced `not_applicable` decision.
`polish_existing` is not proof that captions already exist: when analysis has
not independently verified a subtitle stream or burned-caption layer, burn the
current hash-bound video-use `master.srt` last. An audio plan is `asset_ready`
only after it validates against the Storyboard and its materialized cue/BGM
files are hash-bound. Record unavailable optional BGM separately from an
explicit disabled choice. A cover is blocking only when configured/produced or
required by an enabled publish package; otherwise its absence remains truthful
and does not create a second video deliverable.

Schema v11 adds `motion_quality.portrait_brand` as an explicit, default-off
HongRun/self talking-head capability. It requires grammar version 2, one frozen
Style Reel direction, a configured profile path, and the named-user brand gate.
It rejects third-party/generic/screen-tutorial enablement, fixed-cadence fields,
unknown portrait options, altered A/B/C direction sets, and attempts to disable
user approval. Its six additive portrait schemas and cross-contract rules are
validated by contract fixtures with absolute current file/hash references,
exact semantic/render event inheritance, deterministic non-card fallbacks,
sonic decision coverage, aligned Style Reel inputs, and HongRun-only approval.
Style Reel audition evidence is event-specific: bind the current audio/sonic
plans and authorized cue, decode PCM, prove the off track is the exact voice
window, prove the on track retains it plus an audible matching cue, reject any
unplanned residual energy outside that cue window, and display only those
receipt-bound tracks. The lexical project `assets/sfx` root and every child must
remain inside the project and may not be replaced by a Junction or symlink.
Synthetic phase-image comparison must match the frozen deterministic geometry
for its named direction and reject direction-set rotation, palette-only,
tiny-marker-only, static-phase, or non-clean-exit evidence;
it remains technical fixture evidence, never brand-aesthetic approval.
WP0 is therefore a default-off contract/migration foundation, not evidence that
all six contracts are already consumed by the Director. WP1/WP2 consume the
profile, energy map, and motion contracts. WP3 additionally compiles the exact
PBM-S01 through PBM-S05 sonic decisions into the existing audio plan, copies
only current rights-bound local motif assets, binds every decision back through
the current sonic-library manifest and frozen registry, and leaves FFmpeg/audio
QA as the sole mix owner. Audibility may attenuate the compiled starting gain,
but only a freshly decoded and remeasured off/on audition may authorize that
change. Cue-bearing portrait samples always require the current full-sample mix
and receipt, including on resume; all nested library, rights, audition, and mix
bytes are stage inputs. Its short-media evidence proves technical identity,
timing, audibility, and receipt validation only. WP4 adds a deterministic Style
Reel planner and a separate `portrait-style-review.html`: one current authority
manifest transitively binds source, validation EDL, source/output word
transcripts, semantic brief, captions, voice stem, audio policy, subject
evidence, profile, and ordered event set. The exact 30–45 second window must be
covered by the current video-use EDL; PBM-07 requires a typed independent
in-window chapter boundary. Three isolated HyperFrames-owned render requests
remain blocked until a current explicit HongRun window-confirmation receipt,
bound by SHA-256 to the reviewed files, exists. Completed fixture reels must have the same duration, exactly
one video and one audio stream with matching geometry, distinct current bytes,
exact direction contracts, and four decodable event-phase images per event.
Every event exposes current voice/SFX-off and SFX-on auditions. The review page
synchronizes baseline plus A/B/C, exposes semantic rationale and audio
auditions, and can submit only pending correction proposals protected by
Director-generated short-lived local session nonces. Synthetic fixtures remain
`pending` and cannot record brand approval
or authorize renders. A real-project `awaiting_user` review additionally needs
the later WP6 HyperFrames runtime, caption-last, voice/mix, and parity evidence
gate. The first named-user taste approval, second-topic repeat-use answer, and
explicit second-topic face/hand/product/caption review are retained. The exact
opt-in route is therefore `real_project_validated`. Production-default maturity remains a separate explicit
promotion that is not implemented in this release. Repeat-use willingness is
not sufficient, and a future promotion must first define a separately trusted,
current-evidence-bound HongRun approval authority.

For the first real portrait Style Reel, keep the reviewed `pending` JSON
immutable and let `wp6-review-package.json` carry the `awaiting_user` state.
`record_style_reel_user_decision` may accept that pair only after it freshly
revalidates the entire WP6 package and writes a separate explicit-decision
receipt whose SHA-256 detects later file drift. This is an integrity record, not
encryption or identity authentication. A selected direction creates a project-local provisional
portrait Golden plus a pending preference candidate. The Golden binds the
exact profile snapshot, selected contract/media/phases, HyperFrames technical
evidence, audio identity, project configuration, decision receipt, current Git
base, and scripts/tests source-tree hash. It records one of two required real
validations, keeps `production_default=false`, and never treats the user's
general approval reason as permission to infer additional taste preferences.
Any source-tree or bound-artifact drift invalidates it. A second materially
different HongRun portrait topic and another named-user repeat-use approval are
required for `real_project_validated`; promotion from that state to
`production_default` is deliberately unavailable in this release. It requires
a separately designed trusted approval authority, current implementation and
real-project evidence bindings, and a new explicit HongRun decision.

Before creative planning, require the schema-v8 governance chain:
`provider_governance` chooses only configured providers and writes a scored
decision plus a hash-bound cost ledger; reserve only immediately before an
actual adapter call, reconcile success and failure from configured actual-cost
evidence, reject calls without a currently selected task provider, preserve the
ledger across resume as a controlled mutable artifact whose stage receipt is
atomically refreshed after every legal transition, and block delivery while any
reservation remains unresolved. Treat any positive incremental monetary cost as
paid and require current user-plan evidence. Every successful call must produce a
hash-bound result receipt with a recomputed output-file inventory; an in-flight
reservation requires explicit reconciliation and must never be called again on resume.
`production_contract`
binds the approved preservation, visual-density, audio, cover, provider, and
derived-output promises; and `brand_motion_playbook` compiles profile and design
tokens into deterministic JSON, CSS, and `DESIGN.md`. Missing paid authorization,
quota, rights, or a real provider must become `unavailable` or
`action_required`, never synthetic success.

Run `visual-dynamics-qa.json` at sample and full-project gates. For legacy briefs
it retains the existing cadence and family checks. For decision-complete briefs
it reports event/family counts only as context and gates semantic decision
coverage and exact render-subset binding instead of numerical density. It also measures
evidence-backed quiet intervals,
IP integration, connectors, audio decisions, caption/face/UI protection, and
canvas bounds without rewarding random density. When Golden Editorial Regression
is enabled, sample approval creates the baseline and full QA blocks structural
drift unless an approved correction-ledger entry explains it.

Treat `quiet_source` as an editorial decision, not as a rendered motion beat.
Keep it in semantic evidence, but exclude it from HyperFrames motion
selectors, motion-sidecar assertions, SFX requirements, and four-phase motion
snapshot plans.

The approved Golden baseline is part of `preview-approval.json` by absolute path
and SHA-256 and is itself a hashed preview-approval stage artifact. Validate its
source inputs and integrity before comparing anchors. Snapshot mutable approved
cover evidence before baseline creation, and route corrections to the artifact
that actually owns each decision (Storyboard, semantic brief, audio, or cover).
Compare anchors, families, removed events, quiet/IP decisions, connectors, SFX,
BGM, cover route, and rejected-event structure. Apply an exception only when the correction ledger
still passes its target, before-value, approver, and related-file hash guards.

## Audio, cover, and delivery

Keep speech dominant. Make BGM optional and enabled by default only when an
authorized asset exists; duck it under narration and provide an off switch.
Control how many motion events exist through semantic and pacing gates, then
give every selected non-quiet event one treatment-specific SFX motif unless a
per-event review records why silence is safer. For multi-phase motion
under continuous narration, prefer a restrained 0.6–2.2 second layered or
multi-note motif whose attack, internal notes, and tail follow reveal, relation,
and settle phases; do not rely only on sub-250 ms ticks that can disappear under
speech. Use one primary motif per visual beat and confirm the actual mixed
preview remains clear rather than increasing loudness blindly.

Require an explicit audio decision for every non-quiet visual event: `cue` or
`intentionally_silent` with an event-specific reason. Let the project choose an
adaptive coverage target; a richer personal profile may request 100% coverage
without making that the global default. For every cue record the event id,
asset, family, landing time, duration, volume, and measured post-gain level.
Apply a same-file cooldown and a minimum unique-asset ratio, then verify a real
mixed preview. When at least two cues are selected, cap one SFX family's share
(default 0.5) so transposed copies of the same motif cannot masquerade as
variety. Do not accept a nominal volume value as proof that a cue survives
continuous speech.

For an explicitly enabled HongRun portrait-brand v2 project, compile only the
versioned PBM-S01 crystal pulse, PBM-S02 orbit sweep, PBM-S03 contrast dyad,
PBM-S04 chapter lift, and PBM-S05 warm resolve families. Each technically ready
family needs at least two current, rights-bound, perceptually distinct variants;
pitch-only copies do not count. Map word landings within 80 ms, gesture peaks
within 120 ms after source-to-output EDL mapping, and chapter leads within
180 ms. A missing or stale authorized variant becomes event-specific
`intentionally_silent`; it must not select a different visual recipe. Explicit
SFX disablement also produces complete silent decisions. Do not call these
motifs brand-approved or production-ready until the real Style Reel and named
user gates pass.

Do not treat `has_existing_bgm: true` or an audio stream as proof of audible
background music. Require measured source-presence evidence; long near-silent
gaps make the declaration unverified. When source music is not measurably
present and an authorized project asset exists, use that asset at the configured
preview level and let FFmpeg apply speech-driven sidechain ducking in final
composition. Record both BGM-on and BGM-off review evidence even when only the
default-on universal file is delivered.

Measure loudness and true peak from the exact post-AAC delivery bytes, not from
the pre-encode mix. Treat unsafe true peak as blocking. Leave encoding headroom
(the reference final-compose target is -1.5 dBTP) and require the delivered file
to remeasure at or below -1 dBTP before platform approval.

When `audio.normalization.enabled=true`, compose to a private intermediate,
perform two-pass EBU R128 normalization, copy the video stream into the final
universal MP4, and bind pre/post measurements plus source/output hashes in
`audio-normalization-report.json`. A successful BGM provider result in the full
`audio-plan.json` must flow automatically into final composition; do not require
the user to copy its path back into `project.yaml`.
Bind the pre-normalized composition to the current motion render, selected BGM,
full audio plan, exact FFmpeg arguments, schema, and Director version. Reuse it
only when both that signature and its output hash match. Validate first-pass and
post-normalization measurements plus target tolerances; a nominal `pass` field
alone is insufficient.

For a real-person cinematic cover, use multiple authorized photos as identity
references to regenerate a topic-specific scene, pose, wardrobe, expression,
lighting, and depth. Do not paste a cutout onto a generic gradient. Prefer
natural eye contact, a credible slight smile, open posture, and visible energy.
Default social covers to 9:16 even for a horizontal video.

Let the enhanced cover planner choose among `reference_regenerated`,
`authentic_frame_editorial`, and `real_person_ip_hybrid` from explicit semantic
direction and available authorized assets. Keep regeneration as the normal
personal-cinematic route; use an authentic frame only when it is deliberately
selected, and use personal IP only when it adds topic meaning. Generate
`cover-editorial-plan.json`, two structurally different template candidates,
local exact typography, thumbnail previews, and per-candidate `cover-*-qa.json`.
Block promotion on missing evidence, unsafe boxes, subject/title collision,
unreadable thumbnail type, or missing supporting-asset provenance.

Agent review may pass topic relevance, composition, expression, energy, and
multi-photo reference provenance, but it must not approve personal likeness on
the user's behalf. Record an unconfirmed likeness as a resumable
`action_required` delivery state, not a workflow failure. Complete cover QA only
after the user explicitly approves the regenerated identity.
For an authorized generic/editorial cover with no depicted identity, record
`identity_applicable: false`; topic relevance and visual energy remain blocking,
but do not invent identity references or request a meaningless likeness approval.

Produce one universal MP4 by default and validate that same file for Douyin and
WeChat Channels. Create multiple MP4s only when a real transform, codec, aspect,
or layout difference is necessary; never duplicate byte-identical videos under
platform names.

Deliver the universal video, cover, editable HyperFrames project, director state,
EDL/transcript/caption artifacts, semantic brief, storyboard, audio plan,
provenance, video-use final edit-correctness evidence, technical QA, aesthetic
QA, and honest remaining limitations.

Every completed normal full render must also create
`work/director/editable-delivery/editable-delivery-manifest.json`. This standard
repair kit is not the optional layered NLE package. It must bind the immutable
automatic master, the actual full HyperFrames render before Director applies its
new caption layer, a copied UTF-8 `master.srt`, a deterministic styled
`master.ass`, the caption style plan, a current HyperFrames project inventory,
and a Chinese usage guide. If semantic caption treatment is disabled, derive the
ASS from the current SRT with the configured base typography and no invented
highlight. Track every nested file and authority hash so drift reopens
`final_compose`; do not perform a second video render merely to build the kit.
“Caption-free” means free of the new Director caption layer—it cannot remove
captions already burned into the source.

Treat SRT as editable text/timing authority and ASS as a style-preserving
reference. Do not claim that Jianying, ChatCut, or another editor supports ASS,
can import the retained HyperFrames project, or has received a native draft
unless that exact capability has separate current evidence. The burned automatic
master remains a reference; its pixels are not editable text.

When optional manual finishing is enabled, create `handoff-manifest.json` from
files that actually exist: immutable source, automatic master, optional clean
A-roll, output-timeline captions, optional transparent motion layer, BGM/SFX
stems, cover, and the requested modification list. Every available file must use
an absolute path and current SHA-256 plus type, purpose, and provenance. Mark a
missing optional asset `unavailable`; never invent a file or hash. Continue to
deliver only one universal MP4.

When schema-v13 `delivery.manual_finish.nle_package.enabled` is explicitly true,
also build the editor-neutral `nle-package-v2` from current, hash-bound assets.
At minimum `balanced` contains the immutable automatic reference, clean A-roll,
UTF-8 SRT, available semantic-caption references, layer timeline/OTIO, rights and
compatibility receipts, and a deterministic Chinese Jianying Desktop import
guide with current blank-project screenshots. The guide must include exact
project canvas/frame-rate values, folder-by-folder import order, event-local SFX
placement, SRT-versus-ASS styling limits, the HyperFrames deep-edit boundary,
and the five-task human canary.
Package motion, personal-IP, audio, cover, and modular text-free outro layers
only when their real current artifacts and rights evidence exist; otherwise mark
them unavailable. Never generate or claim a Jianying native draft, API, CLI,
MCP, or headless renderer. Technical package validation remains separate from
the five-task HongRun import/editability canary, and no long-video render is
required to build or validate this handoff.
For a HongRun `luminous_intelligence` modular outro, first compile a 3–6 second
preview-only HyperFrames source project. Package its rights-bound copy/timing
JSON, independent SVG action icons, and deterministic source-project ZIP while
keeping the text-free overlay and reference composite unavailable. HyperFrames
strict check and snapshots do not authorize rendering: set
`render_authorized=false` until HongRun approves the preview.
After explicit approval, record a drift-only approval receipt, render the exact
3–6 second source as (a) a text-free ProRes 4444 alpha layer and (b) a reference
composite, full-decode both, verify midpoint transparency and clean post-exit,
and require the reference bytes to match the approved appearance. Package the
alpha layer, native-copy instructions/icons, reference composite, and current
source archive separately; approval never implies Jianying compatibility.
When `motion_layers` is enabled, a current renderer payload exists, and external
execution is authorized, derive one zero-based transparent HyperFrames project
per approved event without mutating the retained source project. Render only
those event windows, require decoded alpha plus non-empty/non-opaque coverage,
clean exit, exact canvas/rate/duration, and black/white/busy-background proofs,
then package the ProRes 4444 candidates with exact timeline offsets and a
deterministic HyperFrames source-project ZIP. Keep Jianying alpha compatibility
pending until the named human canary; a verified codec is not an import claim.

When schema-v13 `delivery.manual_finish.jianying_native_draft.enabled` is also
explicitly true, require backend `other_nle` and the current layered NLE package.
Compile its EDL, SRT, layer timeline and available asset hashes into one
frame-exact `jianying-draft-plan.json`; emit `draft-status.json`, a Chinese guide
and a target-free install proposal. This WP0–WP3 route must remain default-off,
must not launch Jianying, inspect or write its draft store, install dependencies,
or claim a real native project. Isolated synthetic fixtures are test evidence
only. Preserve the automatic master and editor-neutral package on any native
adapter failure. Real materialization/install and exact-version short canary are
separate WP4/WP5 approvals.
In `layered_reconstruction`, project one base clip per EDL output range and
preserve gaps as empty timeline time. `clean_a_roll` is a conformed output-time
asset, so the native projection derives each base `source_start_frame` from its
output start; event-local media uses source frame zero. Bind event SFX to probed
48 kHz stream metadata and the current audio-plan gain. Re-parse the source
plan, all package JSON, fallbacks, inventories and size limit independently;
unknown programming errors must surface, while expected optional-adapter
failures write a tracked `unavailable` status without invalidating fallbacks.

Record every approved adjustment in `correction-ledger.json` with event ID,
file/selector target, property, before/after values, reason, approver, approval
time, and related file hashes. The ledger tooling must validate its before-value
guard and its regression suite must replay at least one representative structured
correction. Do not mutate an output silently outside the ledger.

If a human-finished file is absent, set `manual_finish_handoff` to
`action_required`; never mark it complete on the user's behalf. When it is
returned, bind the receipt to its exact hash, invalidate any prior delivery QA,
perform a full decode, and require fresh caption, audio, representative visual,
video-use final-edit-correctness, aesthetic, and platform checks against those
exact bytes. A missing, changed, or stale return reopens the manual stage and
`delivery_qa`.

Before declaring this Skill implementation complete, run the six-type fixture
suite in `tests/fixtures/acceptance-scenarios.json`. It covers landscape screen
tutorial, portrait talking head, published-edit polish, two-person interview,
noisy/hotword audio, and screen-plus-camera mixed footage. The suite checks
captions, preservation, semantics, repetition, geometry, SFX/BGM, parity, and
small-correction cost. It is an automated contract fixture, not evidence of
human aesthetic quality, personal likeness, or live platform performance.
The retained report must match the current fixture-source and evaluator hashes,
all evaluator dependency hashes, and the freshly recomputed complete eleven-check
contract. It must contain six unique fixture types and IDs and scenario evidence
hashes. A copied, truncated, or manually edited `status: pass` report is not
completion evidence. In addition, generate a real short MP4 for every required
type and run decode, probe, audio, and representative-frame technical QA.
Retain the six-media manifest with current media, report, sampled-frame, and
implementation hashes. Retain a zero-skip full-test receipt bound to the current
scripts/tests tree and required regressions. Completion audit must freshly
rebuild capability/toolchain discovery, verify all five HyperFrames Skill file
hashes, and validate Director-generated strict-check/render receipts; a copied
render or a standalone `pass` field is not execution evidence.

## Schema-v9 optional execution capabilities

Event-level rendering is default-off. When enabled, accept only explicit
HyperFrames event-window and assembly commands with frame, audio-sample,
visual-equivalence, and ordered-segment-hash evidence. If equivalence cannot be
proved, fall back to the complete HyperFrames render when configured; never
substitute PIL cards or FFmpeg motion.

Cover reference packs remain private local production artifacts. Require
authorization, role coverage, distinct content hashes, at least two identity
references, matching expression, deterministic selection, and two structurally
different candidates. User likeness approval remains a separate gate.

Preference learning writes pending candidates only from explicitly approved,
hash-current corrections; it never auto-applies them. Feedback accepts only
user-exported release-bound snapshots and never treats repeated observations of
one publication as independent videos. Portable audit and release packs are
default-off, sanitize/exclude sensitive material, require privacy/rights and
publication evidence, remain local, and never upload.
Their output directories must be project descendants. Audit replacement first
verifies the old bundle and builds/verifies the new bundle off-path; release
packing requires exact publication-scope rights coverage for the video, cover,
and publishing copy and revalidates every copied or reused byte.

## Legacy compatibility

Keep legacy scripts for old-project reproducibility, but do not call
`attention_planner.py`, `materialize_dynamic_artifacts.py`, or
`build_dynamic_hyperframes.py` from the director path. Migrate a legacy project
by creating professional owner artifacts and resuming `director.py`; do not copy
its old hardcoded captions or card list into the new chain.
