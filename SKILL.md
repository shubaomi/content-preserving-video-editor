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
schema version 3; migrated legacy projects receive disabled manual finishing and
the current preview/render parity tolerances in memory.

## Use the single entry

Run the director from the Skill root:

```powershell
python scripts/director.py run --project <project.yaml> --until sample_qa
python scripts/director.py status --project <project.yaml>
python scripts/director.py approve-sample --project <project.yaml> --approved-by <name>
python scripts/director.py authorize-final-render --project <project.yaml> --authorized-by <name>
```

The state lives at `<project>/work/director/director-state.json`. Resume with the
same `run` command. Do not manually assemble the legacy script collection.

When `action-required.json` appears, execute exactly the capability owner named
there, create the expected artifact, and resume. Do not bypass a stage by marking
it complete. A failed stage must retain its exact error and artifacts.

Do not pass `--approve-final-render` or `--execute-external` until the 60–90
second sample and its aesthetic QA have passed and the user has approved full
rendering. When the user pauses rendering, keep all render stages disabled.
Record approval only through `approve-sample`; it binds the exact Storyboard,
aesthetic review, and gate report hashes. Any later sample change invalidates
the approval and requires another explicit review.

## Preserve content and select mode

Let the director detect `preserve` versus `polish_existing` from the project and
source evidence.

An explicit source declaration wins. Without one, do not silently default to
`preserve`: run the conservative existing-edit analyzer, cache
`input-mode-evidence.json` against source size, mtime, and SHA-256, and select
`polish_existing` only from strong evidence such as an embedded subtitle stream
or high-confidence burned captions. Select `preserve` when no strong marker is
found. A changed source invalidates the cached decision.

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
Keep transcripts cached and subtitles last in the edit stack.

## Author meaning before motion

Have the LLM read the raw word transcript and necessary evidence frames. First
identify chapters, claims, causal links, contrasts, steps, numbers/results,
demonstration actions, and emotion. Then write `semantic-brief.json` with direct
transcript word IDs, quoted evidence, source times, frame evidence, a relevance
rationale, and the intended viewer takeaway.

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

Do not use keyword scoring or event quotas as semantic authors. For a medium
3–10 minute tutorial, one meaningful attention event every 12–20 seconds is a
starting reference, not a quota.

## Require real HyperFrames variety

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
clipped paths. A single line that reaches only one of several declared targets
is incomplete even when HyperFrames reports zero overflow.

Keep sample and full projects separate. The approved 60–90 second sample lives
at the configured sample project; the final composition must be authored in a
different full-duration project, cover at least 95% of the video-use EDL output
duration, and carry a ten-category `visual-vocabulary-audit.json`. Every category
must be selected with event evidence or rejected with a content-specific reason.

## Gate a sample before a full render

Create a 60–90 second sample containing at least four genuinely different
visual structures and representative quiet footage. Capture entrance, midpoint,
pre-exit, and post-exit evidence for each nontrivial event.

Run technical QA and a separate blocking aesthetic review. Tests do not count as
aesthetic approval. Require direct relevance, additional explanatory value,
correct keyword focus, layout variety, speech-synchronous motion, no caption/
face/cursor/UI occlusion, integrated IP visuals, fitting SFX, natural energetic
cover identity, and no unexplained long visual stagnation.

Only after the sample passes and the user approves may the director render the
full HyperFrames motion and final universal media.

The full chain after approval is `full_hyperframes_storyboard` →
`full_hyperframes_qa` → `final_render` → `final_compose` →
`manual_finish_handoff` → `delivery_qa`. The manual stage is a no-op unless
`delivery.manual_finish.enabled=true` with backend `opencut` or `other_nle`, so
the default one-shot workflow is unchanged. `full_hyperframes_qa` requires
strict HyperFrames checks, reviewed snapshots, and representative Studio/render
parity at matching times. The parity report must compare geometry, visibility,
animation phase, connectors, clipping/cropping, and caption occlusion within the
project's configured tolerances; failure blocks render authorization and final
delivery.
Authorize rendering only through `authorize-final-render`; the authorization is
bound to the exact full Storyboard, vocabulary audit, commands, and QA evidence,
and expires when any of them changes. The final stage requires the actual cover and
identity review, final audio plan and provenance, final aesthetic snapshots, a
full decode report, and two platform reports that validate the same universal
file hash.

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
mixed preview. Do not accept a nominal volume value as proof that a cue survives
continuous speech.

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

For a real-person cinematic cover, use multiple authorized photos as identity
references to regenerate a topic-specific scene, pose, wardrobe, expression,
lighting, and depth. Do not paste a cutout onto a generic gradient. Prefer
natural eye contact, a credible slight smile, open posture, and visible energy.
Default social covers to 9:16 even for a horizontal video.

Agent review may pass topic relevance, composition, expression, energy, and
multi-photo reference provenance, but it must not approve personal likeness on
the user's behalf. Record an unconfirmed likeness as a resumable
`action_required` delivery state, not a workflow failure. Complete cover QA only
after the user explicitly approves the regenerated identity.

Produce one universal MP4 by default and validate that same file for Douyin and
WeChat Channels. Create multiple MP4s only when a real transform, codec, aspect,
or layout difference is necessary; never duplicate byte-identical videos under
platform names.

Deliver the universal video, cover, editable HyperFrames project, director state,
EDL/transcript/caption artifacts, semantic brief, storyboard, audio plan,
provenance, video-use final edit-correctness evidence, technical QA, aesthetic
QA, and honest remaining limitations.

When optional manual finishing is enabled, create `handoff-manifest.json` from
files that actually exist: immutable source, automatic master, optional clean
A-roll, output-timeline captions, optional transparent motion layer, BGM/SFX
stems, cover, and the requested modification list. Every available file must use
an absolute path and current SHA-256 plus type, purpose, and provenance. Mark a
missing optional asset `unavailable`; never invent a file or hash. Continue to
deliver only one universal MP4.

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

## Legacy compatibility

Keep legacy scripts for old-project reproducibility, but do not call
`attention_planner.py`, `materialize_dynamic_artifacts.py`, or
`build_dynamic_hyperframes.py` from the director path. Migrate a legacy project
by creating professional owner artifacts and resuming `director.py`; do not copy
its old hardcoded captions or card list into the new chain.
