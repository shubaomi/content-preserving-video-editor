# Implementation objective: Manual NLE Handoff v2

Implement the approved `manual_nle_package_v2` design for
`content-preserving-video-editor` in dependency order, using the approved design
files in this directory as the sole requirements source.

Required implementation scope:

1. WP0: additive schema-v12 migration/configuration, fail-closed package/layer/
   timeline/compatibility/return contracts, capability truthfulness, and docs.
2. WP1: clean A-roll, current editable SRT/semantic caption references, and
   aligned dialogue/BGM/SFX stem packaging from current project evidence.
3. WP2: current event-local motion, personal-IP, and modular outro layer
   packaging with alpha/provenance/rights checks and truthful unavailable states.
4. WP3: atomic package assembly, parallel typed timeline/markers, OTIO/loss
   report, deterministic import guide, size budget, and complete nested manifest.
5. WP4: Director/resume/return integration and transitive artifact invalidation.
6. WP5: reuse the existing 45–60 second HongRun portrait product canary and all
   current evidence to generate only missing handoff derivatives; stop at the
   explicit Jianying Desktop human import/editability gate.

Hard boundaries:

- Do not render a full video, publish, deploy, upload, or invoke/control
  Jianying.
- Do not generate or reverse-engineer a native Jianying draft.
- Do not modify upstream video-use, HyperFrames, Remotion, or Jianying source.
- Keep the automatic master immutable and the default one-shot path unchanged.
- Use no user secret, encryption key, cloud account, or persistent auth token.
- Never fabricate missing layers, hashes, alpha, rights, or compatibility.
- Reuse hash-current analysis, transcript, EDL, semantic, HyperFrames, audio,
  caption, and QA artifacts; rebuild only affected derivatives.
- A returned human edit remains incomplete until every existing final QA gate
  validates its exact bytes.
- WP6 native-draft research is out of scope and requires a separate design
  approval.

Implementation discipline:

- Write failing tests before each production behavior.
- Preserve unrelated working-tree changes and stage exact task files only.
- Run focused tests after each WP, then the zero-skip full suite, retained
  receipts, Current Golden, compile/diff checks, and independent code/security
  review.
- After verified implementation, create a focused commit and non-force push to
  the configured upstream branch. If the manual Jianying canary remains pending,
  report it as `action_required`; do not mislabel implementation as production
  compatibility.

After every task recovery, context compaction, or model change, fully read this
file, the approved candidate, and the implementation plan before continuing.

