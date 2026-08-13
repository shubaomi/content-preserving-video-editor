# Migration and rollback

## Migration

- Additive config only; existing schema-v11 projects resolve package v2 as
  disabled in memory.
- Existing `manual_finish` v1 manifest behavior remains available for
  `package_version: 1` or absent version.
- `package_version: 2` requires `backend: other_nle` plus an explicit package
  profile/level. It does not enable native Jianying automation.
- Third-party identity excludes HongRun IP/outro assets unless separately
  authorized generic equivalents exist.
- Existing automatic masters, approvals, HyperFrames projects, EDLs, captions,
  and QA receipts are reused only while their current hashes remain valid.
- Enabling package v2 invalidates only manual handoff/package/delivery-return
  evidence, not upstream edit or render stages, unless a requested layer truly
  requires a missing derivative render.

## Rollback

- Disable `delivery.manual_finish` or set `package_version: 1`; the automatic
  universal MP4 remains deliverable under the existing workflow.
- Never delete the previous valid package during a failed rebuild. Build beside
  it and atomically replace only after validation.
- Preserve correction ledger and returned-final receipts; mark them stale when
  their package/input hashes drift.
- If alpha MOV fails the Jianying canary, retain event timing/metadata and use
  PNG sequences; do not silently flatten into opaque video.
- If package size exceeds the configured budget, omit optional full-duration
  overlay/per-event SFX/PNG fallback according to the package level and mark
  them unavailable with reason.
- If native draft research later proves unsafe or unstable, remove only that
  optional adapter; the editor-neutral package remains valid.

## Compatibility and versioning

- Every package is immutable and versioned by package receipt hash.
- Changing layer layout, alpha codec, timeline schema, or native editability
  semantics requires a new package schema/profile version.
- Jianying compatibility receipts include app version/platform/date; they expire
  on a configured major-version change or a failed re-canary.
- A newer package reader must validate v1/v2 explicitly rather than guessing.

