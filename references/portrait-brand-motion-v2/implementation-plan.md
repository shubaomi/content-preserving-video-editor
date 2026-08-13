# Implementation Plan

Status: planned only. User approval of the design-freeze candidate is required
before any work package starts.

## 1. Global implementation rules

- On every resume, fully read `goal-objective.md` and the approved candidate.
- Use tests first for contracts, migrations, selectors, failures, and receipts.
- Preserve unrelated work and exact legacy behavior.
- Do not modify upstream video-use, HyperFrames, Remotion, OpenCut, or Jianying.
- Do not render a full video before Style Reel approval.
- Do not promote maturity from documentation or fixtures alone.
- At each package exit, run focused tests, compile/static checks available in the
  environment, exact diff review, and the applicable evidence validator.
- Code changes require the project's mandatory Python/code review before final
  Git delivery; design approval does not waive that gate.

## 2. Dependency order

```text
WP0 contracts and migration
  -> WP1 profile and energy compiler
  -> WP2 recipes and HyperFrames components
  -> WP3 sonic motifs and audio evidence
  -> WP4 Style Reel review surface
  -> WP5 fixture/synthetic validation
  -> WP6 first real Style Reel and user decision
  -> WP7 provisional Golden and preference capture
  -> WP8 second-topic validation
  -> WP9 documentation, maturity audit, commit/push
```

No work package may skip its predecessor's blocking exit.

## 3. WP0 — Contracts, configuration, and migration

Trace: PBM-RQ-003–006, 009–015, 017–018.

Tests first:

- validate all six schemas and cross-contract invariants;
- reject wrong identity, unknown fields, malformed paths/hashes, event-set drift,
  energy cadence/quota triggers, product-card fallback, and actor spoofing;
- migrate old configurations in memory to disabled portrait v2 without changing
  YAML bytes;
- ensure screen/product, mixed, generic, and third-party fixtures are unchanged.

Planned code areas:

- `scripts/project_config.py`;
- new or existing motion-contract validators;
- `scripts/director_contracts.py` and capability registry only where required;
- `tests/fixtures/legacy-projects/` plus focused contract/config tests;
- `references/config-schema.md` and quality/architecture docs after code passes.

Exit: contracts are deterministic, fail-closed, and default-off.

## 4. WP1 — Brand profile and energy compiler

Trace: PBM-RQ-001–005, 010, 014–015, 018.

Tests first:

- compile the same inputs identically;
- cover every semantic opportunity with quiet/micro/meso/macro and rationale;
- prove selection does not depend on elapsed cadence, quotas, random rotation,
  keywords, or SFX availability;
- bind chapter, word, speech-rate, gesture, face/hand/caption, and source evidence;
- reject macro without structural evidence and gesture treatment without a track.

Planned code areas:

- evolve `scripts/brand_motion_playbook.py` to compile profile v2 data rather
  than one global entrance/reveal/hold/exit token set;
- extend `scripts/motion_quality_engine.py` with a portrait-v2 eligibility and
  energy layer without changing existing recipe semantics;
- add focused profile/energy compiler tests.

Exit: the Director can explain every energy and fallback decision without
rendering pixels.

## 5. WP2 — Eight portrait recipes and HyperFrames implementation

Trace: PBM-RQ-001–008, 010, 015–016, 018.

Tests first:

- validate PBM-01–PBM-08 recipe contracts and deterministic choreography;
- prove distinct hierarchy/layout/camera/choreography/layer fingerprints;
- reject generic rounded-card shells for default portrait treatments;
- validate face/eyes/mouth/hand/caption/platform regions and attention layers;
- test reduced-motion variants, seek safety, fallback, source-state binding, and
  clean post-exit state;
- require current manifest, actual painted DOM/text, keyframes, snapshots, and
  Studio/render parity.

Planned code areas:

- additive portrait registry, preferably `references/portrait-motion-recipes-v2.json`;
- Director compiler/router integration;
- reusable HyperFrames portrait components in project-generated template assets,
  with no project-specific hardcoded captions/events;
- runtime capture, keyframe, contrast, geometry, and parity tests extended only
  where the new recipes introduce new observable properties.

Implementation sequence inside WP2:

1. PBM-01, PBM-04, PBM-08 — sufficient for the current canary;
2. PBM-02 and PBM-05 — subject/camera depth;
3. PBM-03 — hand/gesture evidence;
4. PBM-06 — semantic asset integration;
5. PBM-07 — chapter bridge.

Exit: synthetic short media proves all recipes; no Style Reel yet.

## 6. WP3 — Sonic motifs and perceptual audio

Trace: PBM-RQ-005, 009–010, 015, 018.

Tests first:

- validate five motif families and at least two real licensed variants for any
  family claiming production readiness;
- decode PCM, recompute identity/correlation, onset, duration, dialogue-relative
  audibility, and true peak from actual mixes;
- reject malformed/wrong/stale/aliased cues and family dominance;
- verify intentionally-silent decisions and exact event coverage;
- bind word, gesture, and chapter timing tolerances.

Planned code areas:

- extend existing audio production/QA rather than introduce a second mixer;
- add authorized local motif assets and rights records only if available;
- reuse existing review-media and caption-last ordering.

Exit: short synthetic and real-sample audition evidence passes; missing assets
remain truthful and do not block visual-only design evaluation when declared.

## 7. WP4 — Style Reel planner and review surface

Trace: PBM-RQ-011–013, 017–018.

Tests first:

- enforce identical comparison basis and three structurally different directions;
- reject source/event/caption/duration/audio-policy drift;
- produce synchronized A/B/C playback, event markers, contact sheets, semantic
  rationale, and audio toggles;
- keep review pending, loopback/auth/CSRF/path/XSS protections, and pending-only
  correction proposals;
- invalidate approval on any bound hash drift;
- test desktop and mobile layouts, while desktop remains the primary taste gate.

Planned code areas:

- Style Reel planner and isolated render requests;
- evolution of existing creative review page/service/contracts;
- correction ledger integration.

Exit: the UI can compare fixture/synthetic reels honestly; no user approval yet.

## 8. WP5 — Regression and fixture closure

Trace: all requirements.

- Run focused tests for WP0–WP4.
- Extend acceptance fixtures without removing existing six-type coverage.
- Prove existing portrait-v1, landscape/product, third-party, migrated, manual
  finish, universal delivery, caption, and audio paths remain unchanged when v2
  is disabled.
- Generate only short synthetic/fixture media needed for technical evidence.
- Refresh source-bound test receipts only after all code/test changes finish.
- Run mandatory code/Python/security review and close BLOCKER/HIGH findings;
  document accepted lower-severity residuals.

Exit: `fixture_validated`; no real-project or aesthetic claim.

## 9. WP6 — First real Style Reel

Requires separate user confirmation of the proposed exact source window and
permission to run 30–45s short renders.

1. Use the current authorized `告别2025` evidence and recompute all hashes.
2. Materialize the isolated validation EDL; preserve original project artifacts.
3. Render source/baseline plus A/B/C through actual HyperFrames.
4. Mix real SFX evidence and apply captions last.
5. Run decode, preservation, caption, geometry, contrast, keyframe, parity,
   audio, and comparison-equality gates.
6. Run multimodal reject/recommend review.
7. Present one review page and wait for HongRun's exact decision.

Exit outcomes:

- select -> WP7;
- revise -> apply approved scoped corrections and rerun affected evidence;
- reject all -> stop and return to design;
- no response -> action_required, never approved.

## 10. WP7 — Provisional Golden and preference capture

- Snapshot selected profile, contracts, runtime fingerprints, representative
  images, audio identity, user decision, implementation commit, source tree, and
  configuration.
- Create a provisional portrait Golden only.
- Store explicit approved preferences as pending/profile-versioned inputs; do not
  infer preferences from automatic or multimodal feedback.
- Keep production default false.

Exit: one real-project validation with brand taste approved, maturity no higher
than `real_project_validated` for that one project.

## 11. WP8 — Second-topic validation

- Select a materially different authorized HongRun portrait talking-head clip;
  ideally bright, gesture-rich, and knowledge/explanatory rather than reflective.
- Use the same current implementation and profile version.
- Generate one 30–90s candidate, not three style directions unless regression
  evidence warrants a comparison.
- Run all applicable gates and named-user repeat-use approval.
- If it fails, revise the profile/recipes and invalidate the first Golden as
  required; do not lower thresholds.

Exit: two current real validation receipts or remain opt-in/provisional.

## 12. WP9 — Release closure

Only after WP8:

- update SKILL/architecture/config/quality docs with actual maturity;
- refresh full-suite zero-skip receipt, Current Golden, capability inventory,
  global Skill mirror, and completion audit;
- inspect exact diff and preserve unrelated changes;
- create one focused commit and non-force push under repository rules;
- report commit, branch, upstream, tests, real-user gates, and remaining limits.

No full user video, publication, deployment, Release, PR, or upstream edit is
implicitly authorized.

## 13. Estimated validation cost bands

| Band | Work | Cost shape |
|---|---|---|
| D0 | docs/schemas review | seconds/minutes; no media |
| I0 | schema/compiler tests | minutes; local CPU |
| I1 | synthetic recipe media and browser evidence | minutes to tens of minutes |
| I2 | three 30–45s real Style Reels | three short HyperFrames renders plus audio/caption review |
| I3 | second 30–90s real canary | one candidate render plus review |
| I4 | full-video use | only after production-default decision; duration dependent |

Actual wall time, token/provider cost, GPU use, and cache savings must be measured
during implementation; this document does not promise estimates as observed
facts.
