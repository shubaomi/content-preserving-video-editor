# Architecture and tool boundaries

## Decision

Adopt a three-output architecture from one canonical edit graph:

```text
video-use EDL + captions + layer-timeline + current asset hashes
                         |
              canonical handoff graph
          /--------------+----------------\
 automatic master   editor-neutral package   optional Jianying draft
```

The native draft is rebuildable and disposable. It may never become the source
of truth for cuts, captions, semantic events, rights, or final QA.

## Owners

| Concern | Owner | Adapter permission |
|---|---|---|
| Source cuts, gaps, timeline starts | video-use | Read current EDL; no changes |
| Semantic/render event selection | Director + HyperFrames | Read exact IDs/windows only |
| Motion implementation | HyperFrames | Import rendered alpha layers; no reinterpretation |
| Caption text/timing | video-use `master.srt` | Project one native caption per segment |
| Caption emphasis | caption treatment plan/ASS | Translate supported spans and report fidelity |
| Dialogue/BGM/SFX decisions | Director audio plan | Project current stems/gains/windows only |
| IP identity and rights | Profile/rights receipts | Copy only authorized current assets |
| Outro composition | HyperFrames/manual-NLE package | Project available modular roles only |
| Native draft serialization | versioned adapter | Write only a new isolated staging draft |
| Import/edit judgment | HongRun | Named-user canary only |
| Returned export QA | Director | Existing full return pipeline |

## Adapter selection

V1 defines `pyjianyingdraft_0_3` as the primary implementation candidate because
it is Jianying-specific and Apache-2.0. It is not approved merely by this design.
Implementation must pin an exact artifact hash and pass dependency/security
review. `capcut_cli_jianying_0_20` is research-only as an independent lint or
round-trip candidate; it must not write the same draft in v1. CapCut Mate is not
selected because its server/API surface is larger than the local deterministic
need.

No adapter may auto-open Jianying or export media. The current community
compatibility evidence explicitly shows automation limits on newer Jianying
versions. V1 materializes a local draft bundle and a separate install proposal.

## Profiles

- `repair_draft`: always uses the actual pre-caption full HyperFrames candidate.
  Captions are editable; baked motion/IP remain non-native and are labeled so.
- `layered_reconstruction`: requires a complete current `nle-package-v2`; uses
  clean A-roll plus event motion, IP, audio and outro layers. It is the preferred
  canary profile because it exposes more manual control.

The layered profile cannot silently fall back to repair mode. It becomes
`action_required` with missing-role details; the user may explicitly choose the
repair profile instead.

## State and maturity

Capability maturity starts `documented`. Fixture generation may promote only to
`fixture_validated`; a real short canary on the exact installed Jianying version
may promote that versioned compatibility profile to `real_project_validated`.
`production_default` is excluded from v1.

