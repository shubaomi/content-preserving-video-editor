# Capability Roadmap

This file is the implementation source of truth for advanced automation. A written policy is not an implemented capability.

## Status vocabulary

- `policy-only`: behavioral guidance exists, but no deterministic implementation.
- `partial`: some workflow support exists, but the acceptance gate is not complete.
- `implemented`: code exists and representative tests pass.
- `validated`: implemented and forward-tested on both landscape screen recording and portrait talking-head footage.

Never describe `policy-only` or `partial` work as automatic. Update this file only after evidence passes the stated gate.

## 2026-07-21 Director integration checkpoint

All capability rows now have a versioned adapter contract and are at least
`director_integrated`; the authoritative machine-readable matrix is generated
as `capability-inventory.json`. This means every listed ability has a Director
route, configuration/migration behavior, cache/failure contract, and tests. It
does not mean every optional third-party backend is installed or that every
capability has been validated on a new real project.

New integration evidence includes:

- hash-bound evidence acquisition and semantic-plan binding;
- routed ASR, OTIO, HyperFrames task families, selected-event Remotion, and
  evidence-backed media-use/Catalog requests passed through a hash-bound request
  manifest with per-decision provenance and rights checks;
- real audio/IP/cover production stages, BGM provider-to-final-mix continuity,
  and optional two-pass final normalization;
- render-cache execution, technical QA, platform occlusion, same-file platform
  validation, preferences, publishing copy, manual NLE handoff, and metrics import;
- six structured short-fixture contracts with 66 shared checks plus seeded
  negative cases, source/evaluator hashes, unique-type/ID enforcement, and
  per-scenario evidence hashes, stored at
  `references/validation/six-fixture-acceptance.json`.
- six retained real short-media fixtures with decode/probe/audio/frame evidence,
  Director-generated HyperFrames execution receipts, deep toolchain/Skill hash
  verification, and a source-bound zero-skip full-test receipt.

The six-fixture result is `fixture_validated` evidence for routing and shared
contract gates only. Human aesthetics, generated-person likeness, and live
Douyin/WeChat Channels behavior remain manual or real-project gates.

## 2026-08-01 OpenMontage-method enhancement (P0/P1/P2)

Current status: `implemented`; validation remains limited to deterministic tests,
the retained six fixtures, and six real short-media technical fixtures. No
OpenMontage source code, runtime dependency, or automated editor integration is
included.

P0 delivers a schema-v8 Production Contract, preservation-aware Visual Dynamics
QA, deterministic provider selection with adapter-bound cost reservation/
reconciliation, controlled mutable-ledger stage receipts, and an optional
rights-aware local semantic corpus with a real
no-download precomputed-embedding route. P1 delivers
a compiled Brand & Motion Playbook, Golden Editorial Regression with approved
correction-ledger exceptions, and a hash-bound read-only review dashboard. P2
delivers default-off evidence-bound Clip Factory, Podcast, and Localization
modules plus a neutral human OpenMontage handoff that reuses the existing manual
finish and returned-media revalidation contracts.

True limitations remain explicit: unavailable CLIP/local models are not
downloaded; paid/local providers are not assumed from their names; podcast
production requires a real clean PCM WAV; localization production adopts only
an authorized provider result bound to the current transcript and glossary after
reservation; TTS/lip-sync/voice
cloning are not claimed;
OpenMontage is not invoked; and human aesthetics, likeness, editorial taste, and
live platform performance remain release gates.

## Phase 0 — Current foundation

Status: `implemented`, with real TabOut validation.

- source orientation and rotation inspection;
- preserve-mode EDL and coverage audit;
- sentence captions;
- chapter-level visual opportunity audit;
- semantic deduplication and integrated IP visual modes;
- editable HyperFrames preview;
- SFX/BGM planning;
- horizontal video plus native vertical platform cover;
- pre-publish decode and metadata checks.

Known limitation: advanced items below are not automated merely because their policies exist.

## Phase 0.5 — Existing-edit polish automation

Current status: `validated`; deterministic detectors, planning, incremental audio preservation, and verification are implemented, tested, and included in the final cross-orientation gate.

Deliver:

- hard-caption and subtitle-stream detection;
- existing BGM/SFX presence analysis without destructive source separation;
- visual-monotony and chapter candidate analysis;
- baseline-versus-polish comparison plan;
- incremental render path that touches only new overlays/audio when possible;
- enhancement-budget report before generation.

Acceptance gate:

- correctly avoids a second subtitle layer on a burned-caption fixture;
- correctly avoids adding a second BGM bed;
- preserves duration and source audio unless a documented repair changes them;
- produces 3–5 justified enhancement beats from a 3–10 minute existing edit;
- creates a verified polish variant while retaining the untouched baseline;
- validated on one Jianying/CapCut export that was previously published.

Implementation evidence:

- `scripts/analyze_existing_edit.py` detects subtitle streams, likely burned captions, conservative BGM state, transient SFX candidates, visual repetition, chapter candidates, and a 3–5 beat budget;
- `scripts/build_enhancement_plan.py` anchors the budget to complete transcript segments;
- `scripts/finalize_incremental_variant.py` reuses the immutable baseline audio stream after visual rendering;
- `scripts/verify_polish_variant.py` checks duration, audio identity/presence, and first/last-frame decoding;
- portrait Jianying/CapCut export validation: `talk-with-gpt-live/edit/reports/existing-edit-analysis.json` and `polish-variant-verification-audio-preserved.json` pass, while the untouched baseline remains in `source/her.mp4`.

## Phase 1 — Deterministic visual integration

Implement these together because they share frame sampling, masks, design tokens, and visual QA.

### 1.1 Design-token extractor

Current status: `validated`; deterministic multi-frame extraction, explicit low-confidence fallbacks, CSS evidence, and comparison sheets pass the final landscape/portrait gate.

Deliver:

- `scripts/extract_design_tokens.py`;
- input: source video, representative timestamps, optional existing HyperFrames project;
- output: `edit/design-tokens.json` with palette, color temperature, surface color, border/radius/shadow estimates, typography hints, line weight, safe zones, and confidence/evidence frames;
- never infer brand identity from a single anomalous frame.

Acceptance gate:

- deterministic JSON schema;
- representative tests for dark UI recording, light UI recording, and portrait talking head;
- generated card using extracted tokens visually matches source better than the generic default in a side-by-side contact sheet;
- low-confidence fields fall back explicitly instead of inventing certainty.

Implementation evidence:

- `scripts/extract_design_tokens.py` outputs the schema, representative evidence frames, and source/generic/extracted contact sheet;
- synthetic dark UI, light UI, and portrait tests pass;
- real landscape TabOut and portrait `talk-with-gpt-live` reports are stored as each project's `edit/design-tokens.json`.

### 1.2 Transparent and componentized IP asset pipeline

Current status: `implemented`; native alpha, connected matte removal, edge decontamination, fallback cards, QA evidence, and component manifests are available.

Deliver:

- generation contract for transparent character cutout, diagram foreground, labels, arrows, and optional background as separate assets;
- chroma-key removal or native-alpha path with edge validation;
- `asset-components.json` recording dimensions, anchors, role, model, prompt, references, and transparency QA;
- scene-matched card fallback when clean transparency is not possible.

Acceptance gate:

- transparent corners and alpha channel verified;
- no visible key-color fringe at 100% and 200%;
- character identity passes anchor review;
- components can be independently animated in HyperFrames;
- no raw white canvas is used unless declared as a matching design surface.

Implementation evidence:

- `scripts/prepare_ip_components.py` outputs independently animatable PNG components plus `asset-components.json`;
- TabOut's three topic visuals pass transparent-corner and key-color-fringe checks, with 100%/200% evidence sheets and no raw white canvas.

### 1.3 Three-phase motion snapshot QA

Current status: `implemented`; per-beat four-phase snapshots, motion sidecars, contact sheets, pixel review candidates, and authoritative HyperFrames checks are enforced.

Deliver:

- `scripts/build_motion_snapshot_plan.py`;
- derive entrance, held midpoint, pre-exit, and post-exit timestamps from `motion-plan.json` or storyboard;
- run HyperFrames snapshots and create a labeled contact sheet plus `motion-snapshot-qa.json`;
- detect abrupt geometry jumps, missing elements, lingering overlays, caption collisions, and source discontinuity.

Acceptance gate:

- every nontrivial visual beat receives at least entrance/mid/exit coverage;
- intentional full-screen chapter bridges are distinguishable from accidental occlusion;
- failed frames identify selector, timestamp, and repair dimension;
- pass on TabOut's split-panel, picture-in-picture, and masked-reveal examples.

Implementation evidence:

- `scripts/build_motion_snapshot_plan.py` derives entrance, midpoint, pre-exit, and post-exit timestamps, executes HyperFrames snapshots, creates a labeled contact sheet, emits `index.motion.json`, and merges `hyperframes check` status;
- TabOut's eight callout/topic beats pass runtime, layout, motion, and contrast gates; pixel-only source discontinuities remain non-gating review findings rather than false geometry claims.

## Phase 2 — Identity-faithful generative covers and portrait reframing

### 2.1 Reference-guided real-person cinematic cover pipeline

Current status: `validated`; multi-reference clean-base generation is the default contract, deterministic local typography and generative A/B validation are implemented, and both real projects pass agent identity/topic/anatomy review. Final user likeness approval remains an explicit external release gate, not an automated claim.

Deliver:

- one frontal plus up to two complementary authorized identity references;
- generate a new topic-specific person, pose, wardrobe, environment, props, lighting, and camera composition from those references;
- generate a clean 9:16 base with intentional title negative space and no model-rendered text;
- add exact title, product label, and platform-safe crop deterministically with `scripts/compose_generated_cover.py`;
- store reference paths, prompt, generator, topic evidence, clean base, typography method, and separate agent/user identity-review states;
- keep `scripts/build_cinematic_cover.py` only as a literal-photo-pixel fallback.

Acceptance gate:

- the regenerated person is recognizably the authorized creator across face shape, eyes, nose, mouth, jaw, age, skin tone, hairline, and proportions;
- pose, scene, wardrobe, lighting, and topic props are newly staged and coherent rather than a cutout on a generic background;
- hands and body anatomy pass visual review;
- native 9:16 output plus center-safe crop preview;
- identity QA passes before poster-style QA;
- model-rendered text is absent from the clean base and exact local typography is readable at thumbnail size;
- cover manifest records all references, prompt/generator, clean base, topic evidence, typography, and pending/final user review.

Implementation evidence:

- `references/generative-cover-workflow.md` defines multi-reference roles, clean-base generation, identity/topic review order, deterministic typography, and fallback boundaries;
- `scripts/compose_generated_cover.py` produces native 9:16 exact typography without overwriting prior candidates and records reference-guided provenance;
- `scripts/build_cinematic_cover.py` remains available but is explicitly labeled a literal-photo fallback rather than the default movie-poster workflow;
- TabOut and `talk-with-gpt-live` each contain two reference-guided strategies, comparison evidence, and an editorially promoted recommendation under `covers/generative-v2`; user likeness approval remains recorded separately rather than fabricated.

### 2.2 Portrait face tracking and smart reframing

Current status: `implemented`; sampled local face tracking, primary-subject continuity, smoothing, lost-track fallback, multi-person review gates, and normalized crop paths are available.

Deliver:

- `scripts/analyze_subject_track.py`;
- time-series face/person boxes with confidence and smoothing;
- reframing plan for portrait talking head, multiple speakers, temporary screen insert, and lost-track fallback;
- safe caption and overlay regions derived per interval;
- never auto-crop a critical demonstration or second speaker.

Acceptance gate:

- stable crop without visible jitter;
- face remains inside declared safe region;
- lost tracking degrades to a stable wider crop;
- multi-person intervals are flagged rather than arbitrarily selecting a subject;
- validated on portrait walking/talking footage and stationary talking-head footage.

Implementation evidence:

- `scripts/analyze_subject_track.py` emits face boxes, smoothed centers, crop boxes, lost spans, multi-person state, and explicit center fallback;
- moving one-person and two-person portrait fixtures pass; the actual `talk-with-gpt-live` screen recording correctly reports insufficient faces and chooses center fallback instead of inventing a subject track.

## Phase 3 — Platform delivery and resilient rendering

### 3.1 Platform export presets

Current status: `implemented`; dated evidence-aware presets and deterministic media, loudness, decode, safe-zone, and cover validation are available.

Deliver:

- versioned presets for Douyin and WeChat Channels;
- video dimensions, frame rate, codec, bitrate/quality range, loudness target, true-peak ceiling, caption safe zone, cover ratio, center-crop preview, file-size warning, and metadata package;
- verify current platform requirements from primary sources before changing presets.

Acceptance gate:

- one source produces independently validated platform outputs;
- FFprobe, loudness measurement, decode, safe-zone snapshot, and cover-crop preview pass;
- preset version and verification date appear in the QA report;
- no unsupported platform claim is hard-coded without a source date.

Implementation evidence:

- `references/platform-presets.json` separates official Douyin claims from engineering recommendations and marks unavailable public WeChat Channels limits explicitly;
- `scripts/validate_platform_export.py` and `scripts/normalize_social_audio.py` produce dated QA and documented audio repair;
- `talk-with-gpt-live-social-normalized.mp4` passes both platform reports at about -14.46 LUFS and -1.65 dBTP with no recommendation warnings.

### 3.2 Resumable render cache

Current status: `implemented`; dependency signatures, output hashes, stage markers, atomic status/finalization, partial cleanup, and resume behavior are available.

Deliver:

- `scripts/render_with_cache.py`;
- content hashes for source media, composition, fonts, images, audio, variables, render version, and quality settings;
- stage markers for extraction, graphics render, video encode, audio mix, mux, and verification;
- reuse only hash-compatible stages;
- atomic finalization and cleanup policy;
- status JSON readable without attaching to the process.

Acceptance gate:

- intentional interruption after frame extraction resumes without re-extraction;
- a changed caption invalidates only dependent stages;
- a changed source video invalidates all derived frames;
- corrupted partial outputs are rejected;
- two identical runs produce equivalent verified outputs.

Implementation evidence:

- `scripts/render_with_cache.py` implements all six named stages and validates cached output hashes before reuse;
- unit tests prove caption-only invalidation, source invalidation, corruption rejection, and stable reruns;
- the real `talk-with-gpt-live` integration intentionally stops after extraction, resumes with extraction marked `reused`, and completes the remaining five stages in `edit/reports/render-cache-status.json`.

### 3.3 Platform-UI-aware occlusion detector

Current status: `implemented`; optional versioned templates, semantic element boxes, opaque-layer checks, annotated evidence, and explicit missing-template warnings are available.

Deliver:

- platform-specific UI exclusion templates separate from composition safe zones;
- detect captions, picture-in-picture, faces, and important source UI under platform buttons and descriptions;
- produce annotated snapshots and repair suggestions;
- keep templates versioned and optional because platform UI changes.

Acceptance gate:

- catches seeded collisions in portrait and landscape fixtures;
- no false pass when an overlay is hidden beneath another opaque layer;
- platform template version is recorded;
- absence of a current template produces a warning, not fabricated safety.

Implementation evidence:

- `references/platform-ui-templates.json` and `scripts/detect_platform_occlusion.py` cover portrait and landscape UI zones without claiming platform guarantees;
- seeded tests catch platform UI collisions and lower-z elements hidden by opaque layers;
- portrait `talk-with-gpt-live` and landscape TabOut reports identify real caption/PIP risk regions and provide annotated repair evidence.

## Phase 4 — Preference learning and publishing intelligence

These features must not block the core pre-publish pipeline.

### 4.1 Personal motion preference profile

Current status: `implemented`; approved-only scoped storage, provenance, inspection controls, and safety-aware application are deterministic and tested. Final cross-project validation is recorded below.

Deliver:

- store only user-approved final adjustments: position, scale, duration, easing, density, color, SFX family, caption treatment, and rejected patterns;
- keep global profile, content-type preset, and per-video override separate;
- never learn from temporary experiments or unapproved drafts.

Acceptance gate:

- two subsequent projects apply the preference without overriding content safety;
- user can inspect, disable, or reset learned preferences;
- provenance identifies which approved edit created each preference.

Implementation evidence:

- `scripts/motion_preferences.py` records only `--approved` values with required provenance and separate global, content-type, and per-video scopes;
- disable, enable, reset, show, inline JSON, and Windows-safe `--values-file` paths are available;
- the approved profile at `shared/brand/motion-presets/hongrun-approved.json` is applied to both TabOut and `talk-with-gpt-live`; TabOut's project safety file overrides an unsafe preferred position and records the repair.

### 4.2 Cover A/B variants

Current status: `validated`; independent reference-guided A/B bases, deterministic typography, duplicate rejection, comparison sheets, editorial promotion, and no-performance-claim reporting are tested and pass on both real projects.

Deliver:

- optionally generate two meaningfully different hooks/compositions, not cosmetic duplicates;
- keep the same identity-preserving subject pipeline;
- provide a thumbnail comparison sheet and rationale;
- default off when quota or time is constrained.

Acceptance gate:

- variants differ in communication strategy;
- both pass identity, topic-fit, text, crop, and rights gates;
- no automatic claim that one will perform better without platform evidence.

Implementation evidence:

- `scripts/compare_generated_covers.py` validates identity references, topic evidence, exact typography, native 9:16 output, rights basis, communication-strategy difference, and minimum visual difference;
- `scripts/promote_generated_cover.py` promotes only a passed editorial recommendation and preserves the explicit no-performance-claim statement;
- TabOut and `talk-with-gpt-live` each contain two independent reference-guided bases and passed comparison reports under `covers/generative-v2`.

### 4.3 Opening-hook and chapter-pacing audit

Current status: `implemented`; deterministic measurements, separated heuristic judgments, evidence-linked suggestions, and preserve-mode protection are implemented and tested on both orientations.

Deliver:

- score the opening on topic clarity, visible evidence, dead time, duplicate setup, and first-value timing;
- score chapter density and visual monotony without treating shorter as automatically better;
- propose edits separately from the preserve-mode EDL;
- never delete caveats, debugging, or conclusions solely for retention heuristics.

Acceptance gate:

- produces evidence-linked suggestions with timestamps;
- distinguishes factual measurement from heuristic judgment;
- preserve mode requires no new semantic deletion without the existing approval gate;
- validated against both a screen tutorial and a talking-head video.

Implementation evidence:

- `scripts/audit_hook_pacing.py` measures first speech/value, dead time, duplicate setup, chapter density, and visual-monotony evidence separately from heuristic scores;
- every suggestion carries a timestamp and evidence, while the report asserts that the preserve EDL is unchanged and forbids automatic deletion of caveats, debugging, or conclusions;
- real reports exist for landscape TabOut and portrait `talk-with-gpt-live` as each project's `edit/reports/hook-pacing-audit.json`.

### 4.4 Multi-platform publishing copy

Current status: `implemented`; evidence-linked, platform-adapted title, description, hashtag, pinned-comment, and alternative generation is deterministic and tested.

Deliver:

- multiple title, description, hashtag, and pinned-comment options per platform;
- distinguish factual claims, hooks, searchable terms, and calls to action;
- reuse the verified glossary and actual video content;
- never invent performance, product, or personal claims.

Acceptance gate:

- every claim maps to transcript, visible evidence, or profile fact;
- platform versions are meaningfully adapted rather than copied;
- generated copy includes a concise recommended option plus alternatives;
- publishing remains a separate explicit external-action gate.

Implementation evidence:

- `scripts/generate_publishing_copy.py` ranks complete transcript-backed claims, records user-supplied title/search-term provenance, and does not invent performance, product, or personal claims;
- Douyin and WeChat Channels receive distinct hook/context and interaction treatments, a recommendation plus alternatives, and an explicit publish/upload gate;
- real outputs are `TabOut/variants/preserve-v2/publish-metadata-v2.json` and `talk-with-gpt-live/publish-metadata.json`.

## Implementation order used

1. Phase 0.5 existing-edit polish automation.
2. Phase 1.1 design-token extractor.
3. Phase 1.3 three-phase snapshot QA.
4. Phase 1.2 transparent/componentized IP assets.
5. Phase 2.1 reference-guided cinematic cover pipeline.
6. Phase 3.2 resumable render cache.
7. Phase 2.2 portrait tracking and reframing.
8. Phase 3.1 platform export presets.
9. Phase 3.3 platform-UI occlusion.
10. Phase 4 preference and publishing intelligence.

This order first improved visual consistency and caught failures cheaply, then protected identity and expensive renders, then expanded platform and personalization features.

## Cross-phase completion gate

Do not mark the roadmap complete until one landscape screen-recording project and one portrait talking-head project each produce:

- editable HyperFrames project;
- verified pre-publish video;
- integrated nonredundant topic visuals;
- platform cover with identity provenance;
- platform-specific export QA;
- interruption/resume evidence;
- final human review requiring only small corrections.

Status: `validated` on 2026-07-13.

Durable evidence: `references/validation/cross-project-validation-2026-07-13.json`, generated by `scripts/audit_cross_project_validation.py`.

The 2026-07-13 report passes all thirteen hard checks across the landscape TabOut screen tutorial and portrait `talk-with-gpt-live` existing edit. It includes the corrected reference-guided generative-cover policy, independent A/B evidence, platform-package validation, resumable-cache evidence, and explicit publishing boundaries. Final human likeness approval remains a release gate after delivery; it is not an unfinished implementation item or an automated claim.

Two conservative platform-UI-template findings remain visible as human-review warnings rather than being hidden: TabOut caption/facecam placement against the WeChat Channels template, and the portrait video's already burned captions against the Douyin template. These optional engineering templates are not official platform guarantees, so the workflow does not automatically shrink or reframe an otherwise approved video solely from those estimates. Annotated evidence and small repair suggestions are retained in each project.

## 2026-08-02 schema-v9 P0/P1/P2 implementation

Maturity is evidence based: `policy_only`, `utility_implemented`,
`director_integrated`, `fixture_validated`, or `real_project_validated`.

| Capability | Maturity | Evidence boundary |
|---|---|---|
| init-project and Doctor/Preflight | fixture_validated | probe/read-only tests; no install |
| current golden regression | fixture_validated | hash-bound structured/synthetic evidence; not aesthetics |
| dependency graph and event render cache | fixture_validated | explicit HyperFrames fixture commands and safe full fallback |
| semantic confidence and routed ASR QA | fixture_validated | keyword/duplicate/grounding/hotword/diarization/alignment fixtures |
| interactive review and correction ledger | fixture_validated | localhost/security/stale-hash/replay tests |
| private cover reference pack | fixture_validated | authorization/selection/A-B/anatomy/approval fixtures |
| pending preference learning | fixture_validated | scope/sample/conflict/revoke/privacy fixtures; no auto-apply |
| audit, CI, feedback, release pack | fixture_validated | clean-room/local/hash/privacy/rights/authorization fixtures; no upload |

Promotion to `real_project_validated` requires current landscape and portrait
30–90 second sample reports from the exact implementation plus human visual and
audio review. Provider unavailability is a tested governance boundary, not a
real provider result.
