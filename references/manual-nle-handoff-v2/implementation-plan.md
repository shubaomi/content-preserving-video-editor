# Dependency-ordered implementation plan

No item in this plan is authorized until the design candidate is explicitly
approved.

## WP0 — Contracts, schemas, configuration, and truthfulness

- Add schema-v12 additive config/migration for package version/profile/level.
- Implement package/layer/timeline/compatibility/return validators first with
  malformed, NaN, path, Junction, stale, extra-file, and unavailable tests.
- Extend capability inventory with maturity `documented`; no promotion.
- Update Skill/config/architecture/quality docs without changing defaults.

Exit: disabled path is byte-for-byte behaviorally unchanged; validators are
fail-closed; no media rendering required.

## WP1 — Clean base, captions, and audio stems

- Reuse current video-use EDL and final timeline to materialize clean A-roll.
- Export dialogue/BGM/grouped SFX and optional per-event SFX from current plans.
- Package current SRT, deterministic ASS reference, emphasis plan/style guide.
- Add negative checks proving clean base has no newly baked overlay/captions and
  audio recomposition retains alignment.

Exit: short fixture recomposes within frozen audio/picture tolerances.

## WP2 — Motion, personal-IP, and modular outro layers

- Add HyperFrames alpha render contract for event-local motion.
- Add optional full-duration sparse-alpha assembly from the same event cache.
- Copy only current rights-bound IP source assets and render references.
- Compile modular CTA outro into text-free overlay, icons, copy/timing, stems,
  and reference composite.
- Prove alpha on black/white/busy backgrounds and reject opaque/empty outputs.

Exit: each layer is independently removable and hash/time bound.

## WP3 — Package assembler, timeline, and import guide

- Build the complete package in staging and atomically publish it.
- Extend OTIO with parallel tracks/markers while keeping video-use EDL authority.
- Generate a deterministic Jianying Desktop import order and relink guide.
- Add package size estimate/budget and `balanced`/`max_editable` selection.

Exit: fixture package validates from disk and rebuilds deterministically.

## WP4 — Director/resume/return integration

- Integrate package generation into `manual_finish_handoff` after final compose.
- Track every nested artifact so deletion/drift reopens the stage.
- Keep stage `action_required` until a returned manual final exists.
- Extend return receipt/correction ledger and run all existing final QA on exact
  returned bytes.

Exit: resume, drift, interrupted package, and return revalidation tests pass.

## WP5 — Real short canary and Jianying Desktop usability gate

- Reuse the current 45–60 second HongRun portrait product sample and all valid
  upstream evidence; render only missing layer derivatives.
- Import the package manually into the user's current Jianying Desktop.
- Execute the five human edit tasks and record compatibility/usability receipt.
- Export the adjusted sample and revalidate it.

Exit: explicit HongRun decision on usefulness and preferred package level.

## WP6 — Optional future native draft adapter research

- Separate design freeze required.
- Verify official/stable API or sanctioned format before implementation.
- Never reverse-engineer or mutate private drafts as part of the stable path.
- The editor-neutral package remains the fallback and source of truth.

## Verification and delivery discipline

- Tests first for each WP; run focused tests, then full zero-skip suite, Current
  Golden, retained fixtures, compile/diff checks, and independent code/security
  review.
- Do not render a full video until the short canary and user gate pass.
- Stage only scoped files; commit/push only after implementation completion and
  current receipts, not during this design-freeze candidate phase.

