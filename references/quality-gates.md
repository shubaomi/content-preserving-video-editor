# Quality Gates

Complete a video only when applicable gates pass.

## Source integrity

- Preserve the original source.
- Validate EDL source paths.
- Reject negative or source-out-of-bounds EDL ranges.
- Explain semantic removals.
- Review every omitted source interval of 15 seconds or longer; silence alone is not permission to delete it.
- Pass or explicitly waive tail coverage.

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

## Pre-publish package

- Include a cover, final video, editable project, QA report, and asset provenance.
- Verify the cover uses an authorized identity reference and matches the actual topic.
- Gate cover identity and topic-specific scene coherence before aesthetics. For the default path, require multi-photo reference-guided generation and reject pasted-cutout or generic-gradient results. Record references, prompt, generator, and typography method.
- Inspect full-size face likeness, expression, eye contact, warmth/energy,
  hands, age, hairline, body proportions, scene/prop relevance, and thumbnail
  crop separately. Keep final user identity approval distinct from automated
  or agent review.
- Check face consistency, hook accuracy, native 9:16 thumbnail readability for Douyin/WeChat Channels, center-safe cropping, and absence of unsupported claims.
- In autonomous mode, complete up to two targeted repair passes before escalating.
- Scan source and final frames for visual/audio privacy leaks, including sub-second appearances around cuts.
- Confirm cover hooks and product claims do not exceed the demonstrated content.
- Require provenance or an explicit authorization basis for music, SFX, fonts, photos, screenshots, and generated assets.
