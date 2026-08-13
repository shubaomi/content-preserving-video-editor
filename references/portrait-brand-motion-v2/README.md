# HongRun Portrait Brand Motion v2 — Design Freeze

Status: `candidate_in_progress`

This directory is the sole writable scope for the design-freeze phase. It
defines an additive, personal-talking-head expression layer on top of the
existing Content-Preserving Video Director and Motion Quality Engine (MQE).
It does not authorize production code, long rendering, upstream edits, Git
commit, or push.

## Authority order

1. [`goal-objective.md`](goal-objective.md) — exact user objective and recovery rule.
2. [`requirements-traceability.md`](requirements-traceability.md) — needs, non-goals, and trace IDs.
3. [`brand-aesthetic-spec.md`](brand-aesthetic-spec.md) — subjective direction and forbidden language.
4. [`motion-language-v2.md`](motion-language-v2.md) and
   [`sonic-language-v2.md`](sonic-language-v2.md) — visual and audio grammar.
5. [`architecture-and-tool-boundaries.md`](architecture-and-tool-boundaries.md) — ownership and ADRs.
6. [`machine-contracts.md`](machine-contracts.md) plus `schemas/` — draft implementation contracts.
7. [`style-reel-plan.md`](style-reel-plan.md) — three-way isolated comparison.
8. [`acceptance-matrix.md`](acceptance-matrix.md) — automated, multimodal, and user gates.
9. [`migration-and-rollback.md`](migration-and-rollback.md) and
   [`implementation-plan.md`](implementation-plan.md) — safe delivery sequence.
10. [`design-freeze-candidate.json`](design-freeze-candidate.json) — generated candidate manifest.

## Frozen compatibility rule

- The Director remains the system of record.
- video-use remains the word/EDL/output-timeline owner.
- HyperFrames remains the full-composition motion owner.
- FFmpeg remains the final media mechanics and audio-mix owner.
- Remotion remains an optional named-event renderer and never becomes a second
  full-video backend.
- Existing screen/product grammars and legacy projects keep their current
  behavior unless the new portrait feature is explicitly enabled.

## Evidence boundary

The current portrait canary is technically publishable and preferred over its
baseline, but the named user's `brand_taste` decision is rejected. This design
must preserve that evidence; documentation cannot promote the current output to
brand approval.
