# Compatibility research snapshot

Research date: 2026-08-22. These are community projects, not Jianying/ByteDance
official APIs, and therefore cannot authorize stable compatibility by themselves.

## Primary implementation candidates

- `GuanYixuan/pyJianYingDraft`, Apache-2.0, release `0.3.0`:
  https://github.com/GuanYixuan/pyJianYingDraft
  - Jianying-specific draft generation.
  - Its current README marks some Jianying 10.8 behaviors partial, says newer
    `draft_content.json` may not be directly readable, and says automatic
    open/export support is unavailable on Jianying 7+.
- `renezander030/capcut-cli`, MIT, release `v0.20.0`:
  https://github.com/renezander030/capcut-cli
  - Direct CapCut/Jianying draft inspection and editing, including ASS range
    styling and a Jianying namespace.
  - Explicitly unofficial. Its README documents device-identifier leakage and
    command/path injection fixes in older releases; this justifies a strict
    minimum version plus independent security review.
- `Hommy-master/capcut-mate`, Apache-2.0, release `v8.0.76`:
  https://github.com/Hommy-master/capcut-mate
  - Provides a larger FastAPI draft automation surface.
  - Not selected for v1 because server/API scope is unnecessary for local
    deterministic materialization.

## Conclusion

No official, stable Jianying draft-generation API was verified in this design
research. V1 therefore remains an experimental, exact-version community adapter
with the editor-neutral package as the durable fallback. Any later official API
would require a new design comparison before changing the selected route.

