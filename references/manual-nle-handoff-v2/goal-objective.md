# Canonical objective: Manual NLE Handoff v2

Design and freeze a default-off, editor-neutral manual finishing package for
`content-preserving-video-editor`. The package must make a completed automatic
edit materially easier to adjust in Jianying/CapCut Desktop or another NLE,
without claiming an unavailable Jianying API, native draft format, MCP, CLI, or
headless renderer.

The package must preserve one immutable automatic master and additionally expose
only real, hash-bound, rights-aware assets that a human editor can place,
remove, trim, restyle, or replace:

- clean edited A-roll with narration and without burned captions, motion, BGM,
  or SFX;
- editable SRT captions plus semantic-emphasis instructions and a styled ASS
  reference;
- per-event motion overlays and an optional full-duration convenience overlay;
- dialogue, BGM, grouped SFX, and optionally per-event SFX stems;
- personal-IP illustrations in reusable source and rendered forms;
- a modular follow/like/share outro with text-free visual layers, editable copy,
  icons, music/SFX, timing, and a reference composite;
- cover, transcript, EDL, semantic brief, Storyboard, HyperFrames project,
  contracts, provenance, and a typed timeline/import guide.

The design must define requirements traceability, ownership boundaries, package
layout, machine contracts and schemas, alpha and codec fallback policy, timing
and naming invariants, QA, import canaries, migration, rollback, cost controls,
human decisions, and an implementation plan.

Hard boundaries:

- This phase writes design artifacts only. It does not implement production
  code, render a long video, modify upstream video-use/HyperFrames/Jianying,
  submit a draft to Jianying, commit, or push.
- The automatic universal MP4 remains authoritative and immutable.
- The video-use EDL and output word timeline remain edit-time authorities.
- HyperFrames remains the motion-source owner. FFmpeg may derive mechanical
  layer/stem files but may not invent creative motion.
- Missing layers are `unavailable`, never fabricated.
- Native Jianying draft generation is a separately gated future adapter.
- No secret, key, encryption, cloud account, or authenticated Jianying session
  is required for normal package generation.
- A returned human-edited master must pass the existing full revalidation chain.

Success for this phase means a coherent, internally consistent
`design-freeze-candidate.json` with no unresolved blocker/high design findings,
status `pending_user_approval`, and an explicit approval phrase. After every
task recovery, context compaction, or model change, fully read this file and
verify its SHA-256 before continuing.

