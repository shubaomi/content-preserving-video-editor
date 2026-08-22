# Dependency-ordered implementation plan

No item is authorized until HongRun explicitly approves the design candidate.

## WP0 — Schemas, config and dependency boundary

- Add default-off additive config/migration.
- Implement schemas and fail-closed validators first.
- Pin and audit the selected adapter in an isolated environment.
- Add exact editor-version read-only discovery; do not launch Jianying.
- Register maturity `documented` only.

Exit: malformed/security/version tests pass; disabled route has no side effects.

## WP1 — Canonical draft plan

- Compile EDL, layer timeline, captions, events, audio, IP and outro into one
  editor-neutral `jianying-draft-plan.json`.
- Implement rational-frame conversion and round-trip validator.
- Support `repair_draft` and strictly gated `layered_reconstruction` profiles.

Exit: deterministic fixture plan; exact inventories; no native files yet.

## WP2 — Isolated native materializer

- Implement primary adapter behind a narrow typed interface.
- Build only under project staging; no editor-store access.
- Create native base, caption, overlay, IP, audio and outro tracks.
- Re-parse all produced records, scan privacy fields and atomically publish.

Exit: synthetic native package validates twice to identical canonical manifest.

## WP3 — Director/resume/fallback integration

- Add a separate optional stage after current NLE package availability.
- Track every nested artifact and upstream authority hash.
- Preserve automatic/neutral delivery when native generation is unavailable.
- Generate Chinese open/relink/edit instructions and install proposal only.

Exit: drift/resume/failure tests prove no stable-path regression.

## WP4 — Installation boundary

- Separate approval required before implementing any draft-store write.
- If approved, create only a new nonexistent draft target with complete receipt.
- Add safe rollback for exact unchanged generated drafts.

Exit: Windows Junction/existing-draft/outside-side-effect tests pass.

## WP5 — Short real canary

- Reuse current 45–60 second authorized sample; no long render.
- Run exact installed-version import/open and five-task human canary.
- Revalidate returned short export and record HongRun decision.

Exit: exact tuple may become `real_project_validated`; default remains off.

## WP6 — Optional later compatibility profiles

Each new Jianying or adapter version requires a new exact compatibility tuple,
fixture regeneration and short canary. Built-in effects/transitions, existing
draft import/merge, UI automation and production-default each require a separate
design freeze.

## Verification discipline

Tests first; focused security/contract tests; full zero-skip suite; Current
Golden; retained receipts; compile/diff; independent Python/code/security
review. Do not render long video, install a draft, commit or push during this
design-freeze stage.

