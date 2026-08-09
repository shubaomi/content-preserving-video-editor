# Workflow optimization review — 2026-08-08

## Decision

The need is real, but the highest-value response is not another automatic editor
or a larger motion quota. The Director already has 19 stages and broad technical
gates. Its present risk is that a structurally complete artifact can still be
semantically wrong, aesthetically unreviewable, or described as complete before
the actual media asset exists.

This review therefore prioritizes truthful state, evidence coverage, semantic
inheritance, verifiable visual review, and a low-friction next-action surface.
It rejects fixed motion cadence, mandatory unique SFX for every event, an
automatic aesthetic score, and duplicate platform masters as Goodhart-prone
substitutes for editorial judgment.

## Five-angle audit

| Angle | Current strength | Material gap | Direction |
|---|---|---|---|
| Commercial | one universal delivery, release evidence, optional metrics import | no first-class audience, single promise, proof, CTA, or cross-video learning contract | add an evidence-bound editorial-intent ledger only after the P0 production loop is proven on real projects |
| Creative | LLM semantic brief, visual vocabulary, IP/B-roll/cover routes | Storyboard could previously restate unrelated semantics and still satisfy structural checks | bind every rendered event to its approved semantic event and forbid self-authored fallback |
| Aesthetic | four-phase snapshots, geometry, parity, cover and identity review | file-existence checks could accept placeholder image bytes; current dashboard is evidence-heavy but comparison-poor | require decodable review imagery now; design a paired creative review surface before changing the UI |
| Practical | preservation-first EDL, cache, resumable stages, optional adapters | five fixed evidence frames were insufficient for a multi-minute tutorial | use bounded full-duration evidence sampling; keep heavy models event-scoped and optional |
| Ease of use | `run`, `resume`, `review`, explicit action packets | raw `status` and a completed contract stage can look like finished production | expose stage readiness and a concise `next` command |

Automated checks may approve hashes, timing, geometry, decode, clipping,
occlusion, caption alignment, and measured audio. A multimodal reviewer may
reject or recommend semantic and aesthetic choices. Only the user can approve
overall publishability, personal-brand taste, real-person likeness, and whether
a hook or cover is genuinely compelling.

## Open-source methods considered

These are method sources, not dependencies automatically installed by the
Director.

Repository metadata was rechecked through GitHub on 2026-08-08. The candidates
below were not archived at that time. License boundaries are explicit where they
affect reuse: OpenChatCut and OpenMontage are AGPL-3.0 method references;
OpenTimelineIO, WhisperX, PySceneDetect, OpenCut, FunClip, VideoLingo, Kinocut,
ClippyMe, MediaPipe, SAM 2, and Revideo reported permissive licenses. Model,
checkpoint, media, font, and downstream adapter terms still require separate
verification before production use.

| Project | Useful method | Integration boundary |
|---|---|---|
| [OpenTimelineIO](https://github.com/AcademySoftwareFoundation/OpenTimelineIO) | neutral, non-destructive editorial timeline and adapter model | keep Director manifests authoritative; adapters are lossy and OTIO is not a renderer |
| [OpenChatCut](https://github.com/0xsline/OpenChatCut) | proposal → preview → apply/undo; editable timeline as source of truth | AGPL-3.0: borrow the interaction contract, do not copy implementation |
| [OpenMontage](https://github.com/calesthio/OpenMontage) | reference-video deconstruction, differentiated concepts, cost-before-render | AGPL-3.0: retain optional human handoff and method-level inspiration only |
| [Kinocut](https://github.com/KyaniteLabs/kinocut) | intent → dry run → validate → hashed receipt → inspect | experiment with a small typed-operation adapter only if a real gap remains |
| [FunClip](https://github.com/modelscope/FunClip) | Chinese hotwords, speaker evidence, transcript-selected candidates | candidate analysis only; verify each model license separately |
| [WhisperX](https://github.com/m-bain/whisperX) and [faster-whisper](https://github.com/SYSTRAN/faster-whisper) | low-confidence word alignment, VAD and diarization evidence | route only uncertain spans; never overwrite better human captions |
| [VideoLingo](https://github.com/Huanshere/VideoLingo) | syntax-aware caption segmentation and terminology consistency | borrow sentence-boundary fixtures and glossary propagation, not the full app |
| [PySceneDetect](https://github.com/Breakthrough/PySceneDetect) | cut/fade evidence and VFR-aware scene boundaries | optional evidence adapter; a visual boundary is not permission to cut |
| [ClippyMe](https://github.com/fralapo/clippyme) | scene-locked reframe, lost-subject fallback and staged composition | small personal project; borrow methods/tests, not product claims |
| [MediaPipe](https://github.com/google-ai-edge/mediapipe) / [SAM 2](https://github.com/facebookresearch/sam2) | tracked exclusion zones and event-scoped object masks | MediaPipe can be light; SAM 2 must never become a default full-video pass |
| [VMAF](https://github.com/Netflix/vmaf) | technical encode regression for unchanged A-roll | never use it to score motion aesthetics, cover appeal or identity likeness |
| [Revideo](https://github.com/midrender/revideo) / [Remotion](https://github.com/remotion-dev/remotion) | preview/render parity, code-defined named-event rendering | keep HyperFrames as full-motion owner; observe Remotion's commercial license |

Rejected as core backends: theme-to-stock-footage/TTS generators, viral-score
pipelines without calibrated release feedback, abandoned alignment projects,
and repositories without a usable license. OpenCut remains an optional human
finish destination; its Editor API, MCP and headless renderer must not be treated
as available until the upstream project actually ships them.

## This iteration

1. Storyboard events inherit approved semantic IDs, evidence words, time windows,
   viewer takeaway, anchors, and approved visible copy. An exact visible-copy
   manifest rejects added headline/text/component copy. Missing or unrelated
   mappings block both sample and full projects.
2. Representative evidence sampling covers the whole duration at a bounded
   interval and records timestamps plus coverage ownership for every frame;
   partial/misaligned extraction fails closed and every cited timestamped frame
   needs overlapping coverage plus an actual capture time within 15 seconds of
   its event. Long capped sources are currently blocked until a supplemental
   event-level capture is supplied; automatic supplemental capture remains a
   later adapter increment.
3. Aesthetic snapshot, connector, and anatomy evidence must be a decodable image
   of reviewable size; anatomy evidence is unique and role-specific, and
   hash-bound evidence records are accepted and included in stage invalidation.
4. Stage rows distinguish `contract_ready`, `asset_ready`, `not_applicable`, and
   full `ready` without pretending that a contract file is a produced asset.
5. `director.py next --project ...` reports one current owner, instruction,
   expected output and resume command instead of the entire internal state tree.

## Next evidence-gated increments

1. Run one current 60–90 second landscape canary and one portrait canary; record
   semantic accuracy, motion necessity, audio audibility, human adjustment time,
   and paired preference against the previous approved version. Only then promote
   capabilities to `real_project_validated`.
2. Define an editorial-intent contract (audience, viewer job, single promise,
   proof, CTA strength, tone, prohibited claims) shared by the hook, cover, title,
   first ten seconds and publishing copy. Missing commercial intent defaults to
   neutral education and no CTA; it must not be invented.
3. Design and approve a paired creative-review experience that embeds the sample,
   event timeline, four motion phases, original sentence, semantic rationale,
   SFX/BGM audition and cover A/B. It should only create pending correction
   proposals and must not bypass the ledger.
4. Separate 100% SFX *decision* coverage from adaptive audible-cue coverage, then
   measure real onset, duration, short-window dialogue masking and perceptual
   motif diversity rather than counting file names.
5. Add OTIO round-trip parity and scene/word/silence boundary snapping only after
   short fixtures demonstrate that the adapter preserves the Director timeline.

No external project, model, provider, platform publisher, or upstream Skill is a
new required dependency as a result of this review.
