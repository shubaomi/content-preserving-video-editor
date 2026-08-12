# Content-Preserving Video Editor P0-P2 Implementation Goal

## Authority and recovery rule

The user explicitly approved `design-freeze-candidate.json` on
2026-08-11 with this message:

> 批准 design-freeze-candidate，按照实施计划进入下一阶段实现。

This file is the canonical objective for the implementation Goal. After every
task resume, context compaction, or model switch, fully read this file and
verify its SHA-256 before continuing. Then verify the approved candidate and all
design artifact hashes recorded in it. Do not replace this objective with a
summary.

Repository:
`E:\Projects\Skills\content-preserving-video-editor`

Approved candidate:
`E:\Projects\Skills\content-preserving-video-editor\references\p0-p2-design\design-freeze-candidate.json`

Original design objective:
`E:\Projects\Skills\content-preserving-video-editor\references\p0-p2-design\goal-objective.md`

## Objective

Implement the approved P0, P1, and P2 design in dependency order, using the
frozen documents and seven machine-contract schemas as the sole design facts.
Prevent implementation drift, preserve existing behavior when new capabilities
are disabled, and promote maturity only from exact evidence.

The implementation is not a license to bypass gates. P1 starts only after P0
contracts, tests, paired creative review, and both current real canaries pass.
P2 starts only after P1 regressions are stable and remains default off. A user
decision, real media, or expensive/long render that is required by the approved
acceptance matrix must remain an explicit gate.

## Authoritative design assets

Read completely before implementation and validate against the hashes stored in
the approved candidate:

1. `requirements-traceability.md`
2. `architecture-decisions.md`
3. `motion-quality-engine-v1.md`
4. `machine-contracts.md`
5. all seven files under `schemas/`
6. `p0-p2-implementation-plan.md`
7. `acceptance-matrix.md`
8. `risk-and-cost-ledger.md`
9. `design-review-report.md`

If these artifacts conflict, stop and report the exact conflict. Do not silently
choose a different product behavior. Any proposed design change must update the
traceability and candidate through explicit user review before implementation.

## Required implementation sequence

### P0

1. Add additive, in-memory project schema v10 migration, explicit identity mode,
   truthful readiness/maturity states, and downstream invalidation.
2. Separate semantic opportunities from selected rendered events; require a
   decision for every opportunity, exact semantic parent/copy/evidence binding,
   and no event/family quota or fixed cadence.
3. Implement stateful target binding with visible/lost observations,
   static/scene-bounded/keyframed modes, source-state signatures, active windows,
   geometry/connectors, adaptive landscape/portrait constraints, and safe
   fallback instead of guessed coordinates.
4. Implement the Director-owned Motion Quality Engine compiler, all seven
   contract validators, a versioned registry for the 16 approved recipes, and
   deterministic selection/fallback without random template rotation.
5. Integrate HyperFrames project requests with strict check, animation map,
   renderer-exported visible-text/geometry evidence, four-phase keyframe
   receipts, composite contrast, and Studio/final parity. Use
   `hyperframes-keyframes` when advanced recipes require it. Do not modify
   upstream HyperFrames without an independent minimal reproduction.
6. Implement the paired creative review surface with embedded baseline and
   candidate, event markers, four phases, semantic rationale, targets, SFX/BGM
   auditions, pending correction proposals, stale-hash invalidation, and secure
   loopback behavior. No agent may author user approval.
7. Make required captions/audio/cover/identity/delivery stages reach real
   readiness; contract-only artifacts cannot satisfy final delivery. Preserve
   caption-last composition and one universal MP4.
8. Run two current real 30–90 second canaries under the same implementation:
   authorized landscape screen/product footage and a separate authorized
   portrait talking-head clip. Do not substitute fixtures or old reports. Stop
   for the required user review and any missing portrait-source input.

### P1

Only after P0 and both real canaries pass:

1. Implement perceptual motion-audio decisions, fingerprints, onset/masking and
   delivered-mix evidence. Use 100 percent decision coverage and adaptive
   audible cues, not sound on every event.
2. Close punctuation-led word-timed caption segmentation and final sync proof.
3. Add the evidence-bound editorial-intent/promise ledger shared by hook, title,
   cover, description, CTA, and motion claims.
4. Add content-addressed event regression/cache/cost accounting and preference
   learning from explicitly approved correction-ledger entries only.

### P2

Only after P1 regressions remain stable:

1. Add default-off, typed, audited OTIO/NLE handoff adapters with capability/loss
   reports and full returned-master revalidation. Do not claim unavailable
   OpenCut/OpenChatCut/Jianying APIs.
2. Keep Remotion limited to named events backed by maintained React components;
   HyperFrames remains full-composition owner.
3. Add default-off advanced HyperFrames runtimes only with seek-safe proof,
   deterministic 2D fallback, parity, device, license, and cost evidence.
4. Add optional perception/generative adapters only through provider, rights,
   privacy, provenance, budget, and human-review contracts.

## Engineering constraints

- Use tests first for every bug, contract, migration, or feature.
- Preserve unrelated and pre-existing work. Stage exact files only; never use
  `git add -A`, destructive reset, or force push.
- Do not hardcode project captions, semantic events, targets, motion lists, or
  approval fields into production code.
- Do not weaken current preservation, EDL, caption-last, Current Golden,
  geometry, contrast, audio, provider-governance, manual-finish, completion, or
  release gates.
- JSON Schema validates structure; implement explicit cross-contract validators
  for ID sets/order, time ranges, actor authorization, file/media/hash evidence,
  and state transitions.
- A missing optional runtime/provider is `unavailable` or `action_required`, not
  synthetic success.
- Advanced features and all P2 adapters are disabled by default and cannot
  change legacy/new one-click behavior before promotion.
- Do not copy or modify OpenCut, OpenChatCut, OpenMontage, CapCut/Jianying,
  video-use, HyperFrames, or Remotion upstream source unless a minimal
  reproduction proves an upstream-owned defect and the user separately approves
  that scope.
- Do not render a long/full video until the exact sample, aesthetic evidence,
  user sample approval, full-project QA, and final-render authorization exist.
- Automated fixtures or multimodal review cannot approve aesthetics, likeness,
  click appeal, publishability, or production default.

## Verification and maturity

For each implementation package:

1. write and demonstrate failing tests;
2. implement the smallest design-complete change;
3. run targeted tests and adjacent regression tests;
4. run Python compile/static checks available in the workspace;
5. refresh only evidence invalidated by the exact source-tree change;
6. run the complete zero-skip suite before any completion claim;
7. verify Current Golden, six-media fixtures, receipts, full-suite report, and
   global Skill mirror against current hashes;
8. use the approved maturity vocabulary exactly:
   `documented`, `director_integrated`, `fixture_validated`,
   `real_project_validated`, `production_default`.

No capability may be labelled `real_project_validated` until both current real
canaries and required user evidence pass. `production_default` needs a separate
explicit promotion decision.

## Git and global Skill delivery

The source repository is authoritative. The current global Skill directory is
an independent physical copy rather than a Junction, even though its baseline
`SKILL.md` hash matches the source. Do not update the global copy during partial
or failing work. After the authorized implementation scope is complete and all
required verification passes:

1. confirm source/global topology and preserve any unrelated global changes;
2. synchronize the verified source Skill into the global location;
3. verify tracked file inventory and SHA-256 equality;
4. create one or more focused completion commits from exact task files;
5. non-force push the current branch to its configured upstream;
6. report commit(s), branch, remote state, tests, maturity, canary/user gates,
   and untouched changes.

If the Goal pauses at a required human/real-media gate, create an auditable
checkpoint but do not call the entire P0-P2 implementation complete or create a
completion commit merely to hide unfinished work.

## Completion conditions

The implementation Goal is complete only when:

- every implemented work item traces to RQ-001–RQ-020;
- all P0/P1/P2 dependencies and default-off boundaries are honored;
- legacy migration and one-click behavior pass;
- all targeted and complete tests pass with current receipts;
- both real canaries pass under the same implementation and user review;
- no unresolved BLOCKER/HIGH remains after architecture, Python, security,
  creative, aesthetic, practical, usability, and testability review;
- documentation states actual maturity without planned-as-implemented claims;
- verified source/global synchronization and authorized Git delivery complete.

Until those conditions hold, report the exact current milestone, evidence,
remaining gate, and next executable action instead of declaring success.
