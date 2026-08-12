# Landscape canary captioned-review gate — 2026-08-11

## Canonical objective

- Objective: `E:\Projects\Skills\content-preserving-video-editor\references\p0-p2-design\implementation-goal-objective.md`
- Objective SHA-256: `a5fd4c50c668080663e7d8c0ba868e1033a3856906438266df622c0bd5531d82`
- Approved design candidate SHA-256: `8b3e3c13ad68c449c31a47e20a304b23efc08fd0af136fb88e36a67bf646f3aa`

## State

- P0 landscape visual/motion/audio direction was user-approved on the earlier
  raw candidate, but formal validation discovered that the reviewed MP4 did not
  contain the required captions.
- The workflow now burns the same video-use `master.srt` into baseline and
  candidate before Motion Quality paired review.
- Derived review media live under `work/director/review-media`, outside the
  HyperFrames renderer project.
- `sample_qa=complete` and `preview_approval=action_required` for the new exact
  media hashes. The previous user decision was archived and was not copied to
  the changed candidate.
- P1 remains prohibited. The separate portrait canary source is still missing.

## Current exact evidence

- Captioned baseline SHA-256: `91f13b3511435348156270681f259848e12e1cc4a82dc267ce6ed162e1e64c3a`
- Captioned candidate SHA-256: `a97a28d6c5a89d83e3d3c6c0dddd94c9f7ddc5a955315aee16d4e93ce1ef7817`
- Caption delivery receipt SHA-256: `e5da6d70456b0b76d69fcc3248ef7d36c7ec9e50bacfc9be8c49c1273eb09049`
- Pending creative review SHA-256: `fe43c8cd0a0f2e309ea2aea19366a094b84752cc88fff7853a52bfec7b5fa5b0`
- Review dashboard SHA-256: `5f89db7f69785ec01af0331b69f6b66f349ba93e5a7ff3c8b58e7e944ef05799`
- Both captioned media fully decode and are duration-aligned at 75.008 and
  75.000 seconds.

## Implementation and verification

- Added `scripts/sample_caption_delivery.py` with hash, filter, alignment, and
  full-decode receipt validation.
- Integrated captioned paired review into `sample_qa` when Motion Quality is
  enabled and no existing caption layer is independently verified.
- Added/updated unit coverage in `tests/test_sample_caption_delivery.py` and
  `tests/test_director.py`.
- Targeted Director regression: 92 tests passed, zero failures.
- `python -m compileall -q scripts tests`: passed.
- `git diff --check`: passed; only existing line-ending warnings were printed.

## Required next input

1. Human reviews the exact captioned baseline/candidate pair and records
   publish willingness, preference, and reason through `approve-sample`.
2. After the landscape receipt is complete, provide one authorized 30–90 second
   portrait talking-head source for the independent R-P canary.
3. Do not start P1 until both canaries pass under the same implementation and
   compatible schema-v10 configuration.
