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
- Require each sample and full Storyboard event to inherit the approved semantic
  event identity, word IDs, anchor, source/output timing, viewer takeaway, and
  approved visible copy. Require an exact derived `visible_copy_manifest` and
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
- Apply captions after the output edit is final and verify output-timeline remapping.
- Validate names, product terms, URLs, commands, and technical vocabulary against the project glossary and visible UI.

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
- Confirm every semantic beat has one primary explanatory visual.
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
- For every source-bound focus/highlight/callout/overlay, require a target-region
  contract and per-event review. Match observed target count, reject empty or
  orphan regions, require the declared useful-content ratio, and verify that
  the effect's active window coincides with the visible source state.
- Compare hash-bound entrance, midpoint, and pre-exit source-state evidence.
  Static or scene-bounded geometry that spans a page/modal/layout transition is
  blocking; shorten the window or use reviewed keyframed tracking.
- Snapshot, connector, and generated-human anatomy evidence must be a decodable
  image of reviewable size. Placeholder bytes, corrupt images, stale hashes, or
  a path-existence-only assertion do not pass aesthetic QA.
- General review frames must be at least 320x180 in either orientation. Anatomy
  evidence must use three unique role-specific views: `full_frame`, `left_hand`,
  and `right_hand`; structured evidence records declare role and SHA-256.

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
- Require `preview-render-parity.json` for representative semantic events before
  final render authorization. Compare Studio and short-render evidence at the
  same declared time within project tolerances; do not use a full long render to
  create this gate.
- For each sampled event, compare selector geometry and size, visibility,
  animation phase, connector count/attachment, clipping/cropping, and caption
  occlusion. A failed or relaxed parity report blocks final delivery.
- Reject a motion plan below its selected profile floor unless an explicit
  user-approved sparse override includes evidence. Reject long quiet gaps that
  have only a generic prose justification without verified source-frame samples.
- Require sample/full visual-dynamics reports to bind the current Production
  Contract, Storyboard/timeline, captions, design tokens, and reviewed evidence.
  More events do not compensate for weak anchors, repeated layout families,
  clipped geometry, long unexplained quiet gaps, or redundant visuals.
- When Golden Editorial Regression is enabled, compare the full structure to the
  approved sample baseline. Allow drift only through a current approved
  correction-ledger entry whose related hashes still match.
- Bind the Golden baseline into preview approval and revalidate its source,
  preview-stage artifact receipt, implementation, integrity, target, and
  before-value guards. Removed events and
  quiet/IP/connector/SFX/BGM/cover/rejection drift are blocking structural changes.
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
  same-file cooldown, cue duration, and post-gain audibility range.
- Do not infer embedded BGM from the presence of an audio stream or a project
  declaration. Require measured presence evidence; otherwise use an authorized
  asset when enabled by default, with speech-driven sidechain ducking.
- When two-pass normalization is enabled, require
  `audio-normalization-report.json` to bind the intermediate and universal MP4
  hashes and include first-pass and post-normalization measurements. Recompute
  target tolerance checks; reject missing, stale, target-mismatched, or merely
  self-declared reports. A provider-generated BGM selected by the full audio
  plan must be the same hashed asset used by final composition.
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

- Include a cover, final video, editable project, QA report, and asset provenance.
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
