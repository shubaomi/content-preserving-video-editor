# Quality Gates

Complete a video only when applicable gates pass.

## Source integrity

- Preserve the original source.
- Validate EDL source paths.
- Reject negative or source-out-of-bounds EDL ranges.
- Explain semantic removals.
- Review every omitted source interval of 15 seconds or longer; silence alone is not permission to delete it.
- Pass or explicitly waive tail coverage.

## Evidence coverage and semantic inheritance

- Sample evidence across the complete source duration using a bounded policy;
  record frame timestamps, coverage intervals, hashes, and whether a hard cap
  enlarged the interval.
- When a managed target frame has coverage metadata, require its interval to
  overlap the semantic event's source interval and its actual capture timestamp
  to be no more than 15 seconds from that interval. Every cited frame must pass;
  one relevant frame cannot excuse additional unrelated frames. If a capped
  long-video sample is farther away, block semantic approval until an
  event-specific supplemental frame is supplied. The built-in sampler does not
  yet perform this supplemental capture automatically.
- Fail managed acquisition when extracted frame count or timestamps differ from
  the request. Partial extraction cannot claim full-duration coverage.
- When motion quality is enabled, require one decision and rationale for every
  ordered semantic opportunity. Require the sample/full Storyboard semantic-ID
  sequence to equal exactly the `render`-decision subset; non-render decisions
  must remain outside the Storyboard. Legacy schema-v1/v2 briefs retain their
  one-to-one compatibility behavior.
- Require each rendered event to inherit the approved identity, word IDs,
  anchor, source/output timing, target-frame evidence, relevance rationale,
  visual mechanism, viewer takeaway, and approved visible-copy list. Require an
  exact derived `visible_copy_manifest` and
  treat all other event strings as either explicitly allowed metadata or
  approved copy. Reject nested authority fields, arbitrary render props,
  missing/reordered mappings, and extra copy. Continue to inspect final DOM/OCR
  during visual review; JSON validation alone does not prove rendered pixels.
- Never accept Storyboard-authored semantics as a fallback when an approved brief
  exists.

## Production contract and providers

- Require a current hash-bound Production Contract before creative planning and
  revalidate it at sample, full, and delivery gates.
- Reject a provider decision that lacks configured availability, authorization,
  quota, evidence timestamp, selection score, rejected reasons, or task binding.
- Treat estimated/reserved cost separately from reconciled actual cost. A failed
  provider call must release or reconcile its reservation; a budget-cap breach
  is `action_required`, not a silently degraded paid call.
- Reject missing governance artifacts, unselected task providers, unknown ledger
  states, task/provider mismatches, and success rows without result/cost evidence.
  Refresh the mutable ledger's stage receipt only through its controlled writer.
- Infer paid governance from any positive incremental monetary cost, even if the
  candidate omitted its paid flag. Recompute estimate/basis/runtime/actual from the
  selected provider and require a current result receipt with a complete output-file
  inventory. Never automatically retry a still-reserved external call after resume.
- Require paid candidates to carry current user-plan/contract pricing and quota
  evidence plus an actual-cost reconciliation strategy. Reject unresolved
  reservations at delivery.
- Do not download a local semantic model or asset corpus implicitly. Require
  absolute paths, hashes, rights/authorization, embedding model/version/cache
  key, event purpose, semantic score, and motion score for every selected asset.

## Captions

- Use complete natural phrases.
- Let sentence-ending punctuation close the current phrase before applying
  pause or connector-tail rebalancing; reject captions that begin with a
  punctuation-bearing tail such as `的。` from the previous sentence.
- Use punctuation for segmentation even when the display style hides it. The
  default spoken display hides commas, full stops, semicolons, and colons while
  retaining question/exclamation tone.
- Derive caption boundaries from word timestamps. Preserve spoken wording and
  allow only audited spelling, punctuation, and terminology corrections;
  summaries or paraphrases must never be published as subtitles.
- Avoid sustained one-character flashing.
- Check technical terms.
- Avoid faces and critical UI.
- Treat captions, platform controls, and the current semantic subject as hard
  protected regions. During an approved product-emphasis explanation, allow at
  most one bounded face/hand soft overlap only when the overlay is near the
  product, remains under the overlap and semantic-window duration caps, and its
  actual post-exit geometry is clean. Bind the approval to the current semantic
  brief and Storyboard; renderer self-declarations are not authority.
- Apply captions after the output edit is final and verify output-timeline remapping.
- For any work, including `polish_existing`, without an independently verified
  existing caption layer,
  require `final-compose-command.json.caption_delivery.mode=burned_in_last`, the
  current video-use `master.srt` text-authority hash, the current delivered SRT
  or semantic-emphasis ASS hash, and an FFmpeg subtitles filter. A sidecar alone
  is not delivered caption evidence.
- For semantic-emphasis ASS, require exact `captions.json` ↔ `master.srt` text,
  segmentation and millisecond timing, exact approved-copy anchors, current
  configuration, measured canvas, canonical project paths, and deterministic
  byte-for-byte ASS/plan reconstruction. Enabled styling cannot silently fall
  back to plain SRT, and default-off projects cannot self-enable styled output.
  External or self-signed ASS files are not delivery evidence.
- In Motion Quality sample review, apply the same current `master.srt` to the
  baseline and candidate before human comparison. Require aligned durations,
  distinct raw/derived paths, exact caption/input/output hashes, the recorded
  subtitles filter, and successful full decodes in
  `sample-caption-delivery.json`. Store these derived media outside the
  HyperFrames project so they cannot change its source manifest.
- Semantic emphasis captions must preserve exact phrase text, timing and
  segmentation; use only approved anchors that actually occur in the phrase;
  cap emphasis at two terms, 120% scale and the configured brand palette; and
  retain `master.srt` as plain-text authority. Reject random color rotation,
  every-word emphasis, per-character flashing and invented copy.
- Validate names, product terms, URLs, commands, and technical vocabulary against the project glossary and visible UI.
- A real-canary pass must be written by
  `scripts/build_real_project_validation.py`, not hand-authored. Require a real
  30–90 second authorized source, distinct decoded baseline/candidate media,
  RQ-001 through RQ-020 automated results, separate recommendation-only
  multimodal evidence, named-user sample/publishability decisions, measured
  correction/render/cost fields, and current config/code hashes. Missing or
  stale evidence blocks the write; one orientation cannot substitute for the
  other.

## Visuals

- Give every overlay a content purpose.
- Vary motion appropriately.
- Match confirmed IP anchors.
- Load intro and outro from configuration.
- Include a visual opportunity audit for every semantic chapter.
- Explain every generate, reuse, annotation, caption-only, or no-visual decision.
- Never use a character anchor, action sheet, or specification board as a finished topic visual.
- Confirm generated IP images express the current chapter and have content confirmation cards and provenance.
- Render topic IP visuals with complete semantic components inside explicit
  padding. Reject blind crops, clipped hands/faces/props/nodes/connectors,
  decorative frames that hide content, and reused action-sheet fragments whose
  meaning does not match the current transcript claim.
- Inspect every generated human/IP image at full source resolution plus close
  crops of both hands. Require the intended number of shoulders, arms, elbows,
  forearms, wrists, hands, and fingers, with continuous anatomical connections.
  Reject extra, duplicated, fused, detached, or ambiguously connected limbs;
  passing a reduced video-frame thumbnail is not sufficient anatomy evidence.
- Record separate mid-video and outro IP decisions. A stable branded outro may
  use a topic-specific pose/prop/background variant; lack of a pre-generated
  topic image alone is not a valid `not_applicable` reason.
- Confirm source rotation and effective display ratio were detected before layout.
- Confirm every generated visual matches the chosen canvas rather than relying on blind cropping.
- Sample portrait, landscape, or square safe zones for face, pointer, UI, and caption collisions.
- Confirm every selected render beat has one primary explanatory visual; an
  evidenced non-render decision does not require an overlay.
- Reject anchors that are only discourse/UI verbs, repeat an exact anchor more than twice, recur inside the configured cooldown, or reproduce a subtitle-length clause.
- Reject duplicated viewer takeaways across IP images, callout cards, captions, and annotations.
- Reject long full-canvas topic images inside continuous demonstrations unless marked as a chapter bridge.
- Confirm topic visuals use a declared integration mode and match stored design tokens.
- Confirm each visual beat has no more than one redundant entrance SFX.
- Require collision and redundancy statuses to be resolved with evidence. Treat missing or `pending` statuses and unresolved safe zones as blocking.
- Review optical alignment, connector attachment, and useful-content occupancy
  at held midpoints. Large unexplained empty regions and visibly off-center
  geometry fail aesthetic QA even when technical overflow is zero.
- For every declared connector contract, match observed relation count to the
  Storyboard and verify every path terminates on its intended node edge. A
  central line that visually reaches only one of several targets is a failure.
- Reject connector or target reviews that provide only pass booleans. Recompute
  connector endpoint distances from path points and node boxes with no more than
  8 px tolerance; recompute target useful-content occupancy from measured
  overlay/content box intersection.
- For every source-bound focus/highlight/callout/overlay, require a target-region
  contract and per-event review. Match observed target count, reject empty or
  orphan regions, require the declared useful-content ratio, and verify that
  the effect's active window coincides with the visible source state.
- Compare hash-bound entrance, midpoint, and pre-exit source-state evidence.
  Static or scene-bounded geometry that spans a page/modal/layout transition is
  blocking; shorten the window or use reviewed keyframed tracking.
- With Motion Quality enabled, require every render event to explicitly declare
  whether target binding is required. Targetless recipes must carry no binding
  IDs. Source-bound recipes must resolve every declared binding file and match
  its semantic event plus source/output window. Reject stale evidence hashes,
  out-of-canvas boxes, low-confidence visible observations, invented boxes for
  lost targets, uncovered state changes, or active windows that continue past a
  state boundary/loss.
- Require adaptive layout to distinguish verified landscape critical-UI lanes
  from portrait face/hand/caption protection. When required protected-region
  evidence is absent, allow only the recorded `caption_only` fallback or
  `action_required`; a low-occupancy guess is not approval.
- Recompute target boxes and connector endpoints at entrance, mid-hold,
  pre-exit, and post-exit. The post-exit observation must contain no remaining
  target or connector. A report whose findings or status differ from recomputed
  geometry is invalid.
- With Motion Quality enabled, require every semantic opportunity in the
  `motion-design-contract` and require `selected_event_ids` to equal the ordered
  render subset. Validate the exact source and semantic/production/evidence/
  brand hashes, all 16 versioned recipe records, four phase ratios/poses,
  orientation variants, runtime/seek-safety flags, and declared fallback chain.
  Reject keyword-, cadence-, quota-, random-template-, random-family-, or
  SFX-driven selection. Require each HyperFrames Storyboard event to preserve
  the compiled contract ID, recipe ID, choreography fingerprint, semantic ID,
  approved copy, windows, and target binding IDs.
- Snapshot, connector, and generated-human anatomy evidence must be a decodable
  image of reviewable size. Placeholder bytes, corrupt images, stale hashes, or
  a path-existence-only assertion do not pass aesthetic QA.
- General review frames must be at least 320x180 in either orientation. Anatomy
  evidence must use three unique role-specific views: `full_frame`, `left_hand`,
  and `right_hand`; structured evidence records declare role and SHA-256.
- For every non-quiet overlay, bind midpoint and post-exit/source evidence and
  recompute source-composited foreground/panel contrast. Require at least 4.5:1;
  internal component contrast does not replace this check.

## Cut boundaries

- Cut spoken material on word boundaries where possible.
- Retain roughly 30–200 ms of context unless a measured exception is documented.
- Use short audio fades, normally about 30 ms, at newly joined boundaries.
- Review waveform continuity and adjacent frames at every new boundary.

## Opening hook

- Require a `selected` or `not_selected` cold-open decision with transcript and
  frame evidence.
- Select only a self-contained 2–6 second payoff, question, or result with clean
  boundaries; do not add one merely because the video is long.
- Keep hook duplication/reordering outside the preservation EDL until approved.

## HyperFrames

- Pass `npx hyperframes check` without errors.
- Include base picture and sound in Studio preview.
- Exclude base media from transparent overlay source.
- Review representative snapshots.
- Confirm Studio movement persists after playback and timeline seeking.
- Confirm generated source has no accidental long manual keyframes or global class-wide transforms.
- Reject `data-layout-allow-overflow`, `data-layout-allow-occlusion`, unsupported motion variants, generic IP placeholders, and any declared variant without distinct renderer behavior.
- With Motion Quality enabled, require a current
  `renderer-project-manifest.json` that inventories every editable project
  source. Reject any later source edit or addition. Runtime evidence outputs are
  excluded from this source inventory.
- Require `renderer-export.json` from the actual painted project runtime and one
  schema-valid keyframe receipt for every compiled render event. Each receipt
  must contain exactly `entrance`, `mid`, `pre_exit`, and `post_exit`, bind the
  exact project/contract/recipe/source/targets/check/animation-map/export, and
  cite real decodable phase images. Request metadata or a midpoint screenshot is
  not proof.
- Produce the runtime export with the Director-provided capture request. Require
  Playwright to use the browser returned by `npx hyperframes browser path`,
  verify the media `currentTime` at every phase, and fail closed when the browser,
  local dependency, seek, or painted DOM is unavailable. A source frame-zero
  screenshot at a requested later time is invalid evidence.
- Back the receipt's logical `animation_map` artifact with the installed
  `npx hyperframes keyframes <project> --json` operation. Do not accept a
  fabricated `animation-map` command.
- Use the Director-provided receipt builder after parity exists. Require at
  least one positive-duration HyperFrames tween to overlap every compiled
  render event's approved output window; unrelated global keyframes do not
  prove that event's animation.
- Recompute approved visible copy, DOM geometry, source state, targets,
  connectors, clipping, caption overlap, and composite contrast from the export
  and receipts. Require zero post-exit remnant. Any missing, corrupt, stale, or
  contradictory evidence becomes `action_required`.
- Require `preview-render-parity.json` for representative semantic events before
  final render authorization. Motion Quality mode instead requires every
  compiled event and all four phases. Compare Studio and short-render evidence
  at the same declared time within project tolerances; do not use a full long
  render to create this gate.
- For each sampled event, compare selector geometry and size, visibility,
  animation phase, connector count/attachment, clipping/cropping, and caption
  occlusion. A failed or relaxed parity report blocks final delivery.
- Do not reject a decision-complete plan because it falls below a numerical
  event/family floor or exceeds a fixed gap. Reject incomplete decisions,
  ungrounded quiet/source reuse, or rendered filler instead. Legacy density
  profiles remain compatibility checks only while schema-v1/v2 is in use.
- Before Motion Quality preview approval, require a distinct, aligned 60–90
  second baseline/candidate pair; exact compiler, Storyboard, audio-plan, gate,
  media and receipt hashes; every selected event's entrance/mid/pre-exit/
  post-exit images; SFX-off/on and optional BGM-off/on auditions. The review
  defaults pending, drift makes it stale, and only a named human may approve it
  with publish willingness, a paired preference, and a reason. UI proposals stay pending.
- If the sample audio plan contains cues, require the complete paired-review
  candidate to bind and audibly contain every ordered cue before caption-last
  delivery. Recompute the raw candidate, audio-plan, cue asset, mixed-output,
  and receipt hashes; reject missing/reordered cues, a stale asset, an invalid
  mix command, or a failed full audio/video decode. Do not require a mix when all
  decisions are explicitly `intentionally_silent`.
- Require sample/full visual-dynamics reports to bind the current Production
  Contract, Storyboard/timeline, captions, design tokens, and reviewed evidence.
  More events do not compensate for weak anchors, clipped geometry, ungrounded
  non-render decisions, or redundant visuals.
- When Golden Editorial Regression is enabled, compare the full structure to the
  approved sample baseline. Allow drift only through a current approved
  correction-ledger entry whose related hashes still match.
- Bind the Golden baseline into preview approval and revalidate its source,
  preview-stage artifact receipt, implementation, integrity, target, and
  before-value guards. Removed events and
  quiet/IP/connector/SFX/BGM/cover/rejection drift are blocking structural changes.
- For Golden schema v2, require hash-current renderer export, four-phase
  receipts, normalized DOM/motion/geometry fingerprints, and representative
  overlay-crop perceptual hashes. Do not use whole-frame pixel equality, and do
  not reuse sample audio decisions as full-timeline audio evidence.
- Snapshot mutable cover evidence at sample approval. Correction-ledger targets and
  related-file hashes must cover the actual owning Storyboard, semantic brief,
  audio plan, or cover artifact; an unrelated current file is not approval evidence.

## Audio

- Keep original speech clearly dominant.
- Sync SFX landings to their visual events and keep most captions silent.
- For multi-phase motion under narration, prefer one restrained 0.6–2.2 second
  layered or multi-note motif aligned to reveal, relation, and settle phases.
  Reject a mix that depends only on sub-250 ms ticks which become inaudible
  under speech, while also rejecting redundant note clutter.
- Make BGM optional, enabled by default only when an asset is ready, and easy to disable.
- Preview BGM near `0.08–0.12` for speech video; keep SFX around `0.2–0.35` unless measured context requires less.
- Duck BGM under narration for final export.
- Check for clipping, abrupt music seams, duplicate audio nodes, and missing assets.
- Verify audio with BGM on and off.
- Require a `cue` or evidenced `intentionally_silent` decision for every
  non-quiet event. Enforce the configured coverage and unique-asset ratios,
  treating 100% as decision coverage while audible cue coverage follows the
  configured perceptual corridor. Validate the authorized cue identity in the
  actual full-band mixed window, not by filename, nominal volume, or a sampled
  waveform susceptible to aliasing. Also enforce same-file cooldown, cue
  duration, and the post-gain audibility range.
- When at least two cues are selected, enforce `maximum_family_ratio` (default
  0.5) so unique filenames and simple pitch changes cannot make one repeated
  sonic motif look diverse.
- For portrait-brand v2, require the exact PBM-S01 through PBM-S05 registry,
  current local rights evidence, two non-pitch-only variants for any family
  claiming technical readiness, and exact semantic-event coverage. Recompute
  PCM identity and the actual short-media mix. Word cues must land within 80 ms,
  EDL-mapped gesture peaks within 120 ms, and chapter leads within 180 ms.
  Revalidate the sonic plan against the current library, frozen registry,
  selected variant, rights record, PCM, phase, and duration. Reused audition
  evidence must be decoded and remeasured; a self-signed metric is not evidence.
  Allow speech-protection attenuation only when its starting gain, adjusted gain,
  post-gain relation, and current off/on measurement all agree. Cue-bearing
  portrait samples require the current complete sample mix and receipt on both
  execution and resume paths, and nested evidence files participate in stage
  invalidation.
  Missing authorization and explicit SFX disablement must produce reasoned
  silence rather than alternate motion or fabricated assets. Technical passage
  does not approve the sonic taste.
- Do not infer embedded BGM from the presence of an audio stream or a project
  declaration. Require measured presence evidence; otherwise use an authorized
  asset when enabled by default, with speech-driven sidechain ducking.
- When two-pass normalization is enabled, require
  `audio-normalization-report.json` to bind the intermediate and universal MP4
  hashes and include first-pass and post-normalization measurements. Recompute
  target tolerance checks; reject missing, stale, target-mismatched, or merely
  self-declared reports. A provider-generated BGM selected by the full audio
  plan must be the same hashed asset used by final composition.
- Distinguish an explicit `disabled` BGM choice from `unavailable` after the
  configured authorized provider chain produced no asset. Both require a reason;
  `unavailable` also retains the attempted provider outcomes.
- Require `final-compose-command.json` to bind the motion hash, BGM/audio-plan
  hashes, exact command/settings, and current intermediate hash. Never reuse a
  pre-normalized file merely because that path exists.

## Export

- Verify duration, dimensions, frame rate, video, and audio with FFprobe.
- Complete a full FFmpeg decode.
- Sample first, middle, and final segments.
- Report duration and content coverage.
- Never claim completeness when unexplained content is missing.
- Default to one universal final media file. Validate it separately for each
  target platform; create multiple MP4 files only when actual media transforms
  differ, never when the bytes would be identical.

## Optional manual finish

- Before delivery QA, require a current standard editable-delivery manifest for
  every completed normal full render. Revalidate the automatic master, distinct
  pre-caption full HyperFrames candidate, copied SRT/ASS/style plan, Chinese
  guide, and retained HyperFrames project inventory by exact path/hash.
- Require plain projects to receive a deterministic ASS style reference derived
  from current SRT with no unapproved emphasis. Never label source-burned
  captions removable, the automatic master text-editable, or the repair kit a
  native Jianying/ChatCut project.
- Building the standard kit must reuse existing render bytes and must not trigger
  another full-video render. Missing or drifted nested assets reopen
  `final_compose`.

- Keep `manual_finish_handoff` disabled by default. OpenCut and other NLEs are
  human-facing finishing surfaces, not automated director backends or required
  dependencies.
- Preserve source and automatic master bytes. List only real assets in the
  handoff manifest with absolute paths and SHA-256; mark missing optional files
  `unavailable` without a synthetic hash.
- Record every approved manual change in `correction-ledger.json`; require event
  ID, target file or selector, property, before/after value, reason, approver,
  approval time, and current related-file hashes. Reject replay when the
  before-value or related-file hash has drifted.
- Treat a pending human edit as `action_required`, never complete. A returned
  file invalidates previous delivery QA and must pass a fresh full decode,
  caption sampling, loudness/true-peak audio QA, representative visual QA,
  final aesthetic review, video-use final-edit-correctness, and platform checks
  tied to the exact returned file hash.
- Reopen manual finishing and delivery QA when the returned file disappears or
  its bytes, size, or modification time change.
- Treat `delivery.openmontage_handoff` as the same human-only boundary. Generate
  a neutral manifest and `action_required`; never claim OpenMontage automation,
  API, MCP, CLI, or headless rendering.
- Keep layered NLE package v2 default-off. Validate its complete on-disk
  inventory, current authority hashes, EDL/OTIO timeline, unavailable rows,
  path containment, and deterministic import guide before exposing it to a
  human editor. Standard H.264 MP4 must never be labeled as alpha; unverified
  alpha formats remain pending until the current Jianying Desktop canary.
- Generate the Jianying import guide in Chinese, copy the current blank-project
  screenshots into the package, and hash them in the complete inventory. The
  guide must distinguish zero-origin full stems from event-local SFX placement,
  explain that SRT does not preserve ASS per-word styling, and route deep motion
  edits back to the retained HyperFrames project.
- A technical package pass does not prove editability. Require HongRun to import
  the short canary and complete the five caption/motion/SFX/IP/outro edits before
  promoting the named compatibility profile. Native draft/API/CLI/headless
  capabilities remain false.
- Keep `jianying_native_draft` default-off. When explicitly enabled, require a
  current valid NLE package, exact EDL/SRT/layer-timeline and asset hashes, a
  deterministic rational-frame plan, Chinese guide and target-free install
  proposal. Disabled execution creates no native-adapter directory.
- WP0–WP3 may validate only isolated synthetic contract fixtures. Every fixture
  must state `synthetic_fixture_only=true`, claim no real Jianying compatibility,
  contain no proprietary effect/resource IDs or privacy metadata, rebuild to the
  same canonical hash, and refuse traversal, symlink/Junction and existing
  targets. Never install it into Jianying.
- Require layered base clips to equal EDL output ranges and require the native
  projection to derive conformed clean-A-roll source-in from each output start.
  Permit one motion clip and its paired SFX to share a semantic/render binding,
  but reject duplicates within the same role.
- Re-parse the source plan, standard editable and NLE fallbacks, projected
  native plan, adapter report and every package JSON. Reject absolute
  home/cache paths, URLs, secret-bearing fields, source-plan drift and package
  size overrun even when hashes were recomputed after tampering.
- Native-plan or adapter failure must not remove or invalidate the automatic
  master or `nle-package-v2`. Real draft generation/install and the five-task
  short-video canary remain unresolved until separately authorized WP4/WP5.

## Optional derived outputs

- Clip candidates must cite existing word IDs, source/output times, exact quote,
  evidence hashes, independence score, cut reason, and orientation decision.
- Podcast output must be an actually materialized, decodable clean PCM WAV with
  duration/sample-rate/channel/RMS/peak measurements and chapter evidence.
- Localization requires an actual provider result bound to the current transcript
  and glossary hashes. Preserve word IDs/times, terminology/glossary choices,
  and back-translation QA; do not fake TTS,
  lip-sync, or voice-clone authorization.
- Missing optional providers or assets are honest `unavailable` or
  `action_required` outcomes and must not block the default universal MP4 when
  the module is disabled.

## Pre-publish package

- Evaluate `delivery.required_assets` before final delivery. Required stages
  must be complete at `ready` or `asset_ready` as configured; explicit
  `contract_ready` never passes. An asset is `not_applicable` only through a
  non-empty evidence-backed reason, such as explicit caption delivery `none`.
- Require the Production Contract to bind `identity.mode`. In `third_party`
  mode, reject HongRun identity assets, personal intro/outro, and first-person
  brand expression before creative generation or delivery.
- Always include the final video and applicable QA/provenance. Include a cover
  only when it was produced or the configured publish/release package requires
  one; never fabricate a cover or crop preview for an optional absent cover.
- Verify the cover uses an authorized identity reference and matches the actual topic.
- When enhanced editorial production is enabled, require a hash-bound
  `cover-editorial-plan.json`, valid semantic event IDs, and one to three
  headline highlight terms that occur exactly in the local title.
- Gate cover identity and topic-specific scene coherence before aesthetics. For the default path, require multi-photo reference-guided generation and reject pasted-cutout or generic-gradient results. Record references, prompt, generator, and typography method.
- Inspect full-size face likeness, expression, eye contact, warmth/energy,
  hands, age, hairline, body proportions, scene/prop relevance, and thumbnail
  crop separately. Keep final user identity approval distinct from automated
  or agent review.
- Check face consistency, hook accuracy, native 9:16 thumbnail readability for Douyin/WeChat Channels, center-safe cropping, and absence of unsupported claims.
- Require each candidate `cover-*-qa.json` to bind the exact plan, manifest, and
  candidate hashes. Block out-of-safe-area geometry, subject/title collision,
  more than the configured headline lines, type smaller than 10 px at a
  180-pixel-wide thumbnail, or available supporting assets without purpose,
  rights basis, and SHA-256.
- In autonomous mode, complete up to two targeted repair passes before escalating.
- Scan source and final frames for visual/audio privacy leaks, including sub-second appearances around cuts.
- Confirm cover hooks and product claims do not exceed the demonstrated content.
- Require provenance or an explicit authorization basis for music, SFX, fonts, photos, screenshots, and generated assets.

## Workflow implementation acceptance

- Require `capability-inventory.json` and `toolchain-compatibility.json`; every
  claimed one-shot capability must be `director_integrated` or higher, declare a
  configuration route, and keep required core capabilities enabled. Resolve all
  five required HyperFrames Skill roots separately.
- Run `scripts/fixture_acceptance.py` against all six required fixture types and
  retain `references/validation/six-fixture-acceptance.json`.
- A seeded semantic, repetition, geometry, audio, parity, or preservation defect
  must fail closed. Missing fixture types are a failed completion gate.
- Recompute the fixture-source and evaluator SHA-256 values and require six
  unique scenario IDs/types with nonempty passing checks and per-scenario
  evidence hashes. Also bind the evaluator's routing and contract dependencies,
  and require the retained report to exactly match a fresh evaluation. Do not
  accept a detached, shortened, or self-reported pass JSON.
- Generate one real short MP4 for each of the six required video types and pass
  full decode, ffprobe, audio measurement, and representative-frame extraction.
- Retain `references/validation/six-media-acceptance.json` with current media,
  technical-report, sampled-frame, and implementation dependency hashes. A
  missing or edited evidence file invalidates the suite.
- Require a source-bound, zero-skip full-test receipt. Recompute the scripts and
  tests tree hash, runner hash, test log hash, count, exit status, skipped count,
  and required regression IDs rather than trusting a standalone green label.
- Require Director-generated HyperFrames strict-check and render receipts that
  bind argv, working directory, logs, toolchain, approvals, QA evidence, and
  output bytes. A manually copied render without a receipt is not accepted.
- Require completed Director stages to retain current SHA-256 artifact records,
  and require current project/source input fingerprints. A status flag without
  these byte bindings is not completion evidence.
- Require the completion audit's OpenMontage-method enhancement criterion to
  independently verify Production Contract, provider/cost, brand playbook,
  sample/full visual dynamics, enabled Golden regression/derived outputs,
  stage artifact bindings, full-QA bindings, and delivery bindings.
- Require final aesthetic, cover, platform, full-decode, video-use correctness,
  and delivery-contract evidence to bind the exact universal MP4 and cover
  bytes. Recompute all bindings, technical measurements, safe-zone/crop evidence,
  capability inventory, toolchain discovery, and HyperFrames Skill hashes during
  completion audit.
- Technical and platform validators must freshly rerun probe, decode, and audio
  measurement against the exact delivery bytes; matching hashes and self-declared
  check fields alone are insufficient.
- Fixture success does not replace full-size aesthetic review, user likeness
  approval, real-source review, or real-platform verification.

## P0/P1/P2 blocking gates

- Route screen/product and portrait talking-head sources through different
  format grammars. For portrait, reject product-dashboard cards and require
  face-safe expressive treatments; technical pass and publish willingness do
  not substitute for the user's separate brand-taste decision.
- For schema-v11 portrait-brand projects, require all six portrait contract
  schemas plus cross-file validation. Recompute every referenced file hash,
  require absolute paths, exact semantic/render event order and approved copy,
  complete sonic decisions, distinct aligned A/B/C Style Reel fingerprints,
  and HongRun-only approval. Reject fixed cadence, minimum quotas, random
  rotation, product-card fallback, changed comparison inputs, and stale review
  bytes. Contract success is not rendered-style or brand-taste approval.
- For a Style Reel fixture gate, revalidate the transitive authority manifest,
  require a 30–45 second isolated plan and the frozen A/B/C order, and derive
  each structural fingerprint from hierarchy, layout, camera, choreography and
  sonic pattern rather than a label or color token. Require the selected window
  to be covered by the current video-use EDL and any macro event to bind an
  independent typed in-window chapter boundary. Fully decode all three
  direction reels; require equal durations, exactly one video and one audio
  stream, and matching complete stream signatures,
  distinct media hashes, exact event order, current direction contracts, and
  one 320x180-or-larger decodable image for every event at entrance, mid,
  pre-exit and post-exit. Require a separate current baseline with the same
  signature and duration before synchronized review.
- Recompute palette-normalized phase geometry at review creation and replay:
  for a synthetic fixture require the frozen deterministic geometry for the
  named direction, and reject rotated direction sets, solid images, palette-only
  changes, tiny-marker-only differences, static event phases, and phases without
  a clean post-exit. This proves
  observable fixture structure only; HyperFrames runtime/parity and user taste
  remain separate WP6 gates.
- A real WP6 selection must bind the immutable pending review and the current
  `awaiting_user` package in one explicit SHA-256-bound decision receipt. Revalidate the
  package's window confirmation, technical evidence, review/context/dashboard,
  selected media, and all three contracts before accepting the decision.
- The first selected direction may create only a provisional portrait Golden.
  Require current refs for the profile snapshot, selected contract/media/phases,
  HyperFrames check/render, audio/sonic plans, SFX auditions, project config,
  decision receipt, Git base, and scripts/tests tree. Require exactly one of two
  real validations and `production_default=false`. Preference capture must have
  `auto_apply=false` and an empty inferred-preference list.
- The second-topic gate requires a materially different current HongRun portrait
  candidate, the same profile version/direction, current candidate and QA bytes,
  passing decode/HyperFrames/phase/caption/audio/occlusion gates, and an exact
  HongRun `repeat_use_willingness=yes` plus `preference=candidate` decision. Its
  retained receipt may promote only to `real_project_validated`; it must keep
  `production_default=false`, `auto_apply=false`, and inferred preferences empty.
- `production_default` is a separate maturity transition. Two-topic repeat-use
  evidence is necessary but not sufficient. This release intentionally rejects
  the transition because it has no independently trusted HongRun approval
  authority. A later design must bind that authority to the current profile,
  implementation, retained real-project validation, and explicit default-use
  intent; never interpret a favorable reason as default-use authorization.
- Every displayed Style Reel SFX audition must bind the current audio and
  portrait-sonic plans, exact semantic event, voice-stem window, audio policy,
  and authorized cue asset. Freshly decode PCM and reject silence, arbitrary
  tones, stale display refs, project SFX roots redirected through links, an on
  track that does not preserve the voice window plus the authorized cue, or
  any unplanned residual energy before or after the cue window.
- A synthetic fixture review must remain `pending`, even with a current passing
  automated report; it cannot authorize a render or user taste decision. The
  page must escape authored text, keep desktop as the
  primary taste surface, provide usable mobile stacking, synchronize all four
  players and markers, bind semantic rationale exactly to the current brief,
  expose voice/SFX-off and SFX-on auditions, and use
  the existing loopback Bearer/CSRF/path/hash protections for pending proposals.
  It may not approve taste. Real-project render requests need an explicit
  HongRun exact-window receipt; `awaiting_user` additionally requires the WP6
  runtime, caption-last, voice/mix and parity gate. Any bound hash drift rejects
  a prior decision; only an explicit HongRun receipt answering all six
  applicable questions can later authorize a selected direction.
- PBM-01 through PBM-08 fixture promotion requires a registered GSAP timeline,
  strict HyperFrames runtime/layout/motion/contrast checks, actual discovered
  per-event keyframes, all five component phases, clean post-exit state, a
  decodable short render, and same-time preview/render comparison. Synthetic
  silhouettes and placeholder phrases may prove mechanics only; they cannot
  pass HongRun's brand-taste gate.
- Advanced runtime recipes require current seek-safety, deterministic fallback,
  parity, device, license, and cost evidence. Otherwise require deterministic
  2D fallback.
- Remotion requires hash-bound maintained components, parseable parity, and
  license files. Parity recomputes the decodable reference/render image delta
  and requires either a component-bound `visual_only`/`audio_policy: forbidden`
  contract or bound audio bytes;
  legacy strings and boolean pass flags fail. Explicitly enabled optional media
  adapters without real reviewed output become `action_required`.
- Editorial promise closure must jointly bind hook, title, description, CTA,
  proof motion copy, and applicable cover to current proof IDs and reject
  prohibited claims or mechanical repetition.
- Reproduce the current golden report from fixture, policy, six-media evidence,
  Director/schema version, and implementation hashes. Tamper, missing, expiry,
  semantic mismatch, layout drift, or caption drift must fail.
- Event cache reuse requires current input/output hashes and explicit
  frame/audio/visual equivalence. Otherwise use the complete HyperFrames render.
- Semantic candidates cover every non-quiet event and retain grounding,
  counterexamples, duplication, reasons, and rejection reasons. Low-information
  words alone never become anchors.
- Interactive proposals stay pending until separate approval. Stale hashes,
  path traversal, non-loopback hosts, bad origin/auth/CSRF, arbitrary targets,
  and direct output edits fail.
- Cover packs require authorization, role/expression coverage, distinct images,
  structurally different A/B candidates, anatomy checks, and separate user
  likeness approval.
- Preference candidates remain pending and ineligible below configured samples;
  stale/sensitive/conflicting or unapproved cross-scope evidence fails.
- Audit bundles verify after relocation and contain no secrets or machine paths.
  Audit outputs stay inside the project and replace a previously verified bundle
  only through a rollback-safe directory exchange. Release packs require rights
  rows for the exact video, cover, and publishing-copy hashes; they revalidate
  copied bytes, privacy, rights, publication authorization, every manifest entry,
  and reused-pack integrity, and record `upload_performed: false`.
- Feedback is user-supplied, source-hash deduplicated, release/video/cover/copy/
  motion/version bound, and advisory only. One video's repeated observations
  cannot create a durable preference.
