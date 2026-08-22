# Requirements traceability

| ID | Requirement | Owner | Frozen acceptance evidence |
|---|---|---|---|
| JYD-RQ-001 | Preserve the automatic master as immutable visual reference | Director | Current path/hash is present; adapter never writes it |
| JYD-RQ-002 | Keep video-use EDL and layer timeline authoritative | video-use + NLE package | Draft round-trip inventory exactly matches canonical frame placements |
| JYD-RQ-003 | Generate only a new isolated draft | Adapter | Target did not exist; no existing draft path is accepted |
| JYD-RQ-004 | Remain disabled by default | Config migrator | Legacy/current disabled routes produce no draft files or editor-store writes |
| JYD-RQ-005 | Provide a repair profile from the pre-caption candidate | Director | Caption text/timing editable; baked motion is truthfully marked non-native |
| JYD-RQ-006 | Provide a layered reconstruction profile only from a complete validated NLE package | Adapter | Clean base plus layer inventory recomposes within frozen tolerances |
| JYD-RQ-007 | Convert every current SRT segment into one editable native caption segment | Caption adapter | Exact text, order, start/end frame and unique segment ID round-trip |
| JYD-RQ-008 | Preserve semantic emphasis without silently flattening | Caption adapter | Fidelity is `full`, `degraded`, or `unavailable`; fallback ASS remains attached |
| JYD-RQ-009 | Make motion removable at event granularity | HyperFrames + Adapter | One current alpha layer per render event with exact output window and event ID |
| JYD-RQ-010 | Keep deep motion edits in HyperFrames | Director | Native layer is labeled rendered overlay; source project path/hash retained |
| JYD-RQ-011 | Make authorized IP imagery independently movable | Profile + Adapter | PNG layer plus rights/provenance and output window; no baked-only claim |
| JYD-RQ-012 | Keep dialogue/BGM/SFX separable when real stems exist | Audio owner + Adapter | Exact stem hashes, 48 kHz decode, gain/start/duration round-trip |
| JYD-RQ-013 | Keep modular outro elements separable | HyperFrames + Adapter | Background/overlay/icons/native copy/SFX roles remain individually addressable |
| JYD-RQ-014 | Avoid proprietary built-in effect/resource IDs in v1 | Adapter | No draft record depends on harvested transition/effect/template identifiers |
| JYD-RQ-015 | Pin adapter and target editor compatibility | Director | Exact adapter package/version/hash, editor version, draft signature and canary status |
| JYD-RQ-016 | Fail closed on unknown/new Jianying layout | Compatibility probe | No generation/install when editor or draft signature lacks an approved profile |
| JYD-RQ-017 | Never require cloud sync, login, token, or encryption key | Director | Local-only configuration and secret scan; no network execution dependency |
| JYD-RQ-018 | Prevent path escape, Junction/symlink redirection, and partial publication | Adapter | Lexical authorized root, reparse-point tests, staged build, atomic directory promotion |
| JYD-RQ-019 | Protect personal/device metadata | Adapter | Fresh draft only; no cloning user draft; manifest scan rejects identifiers and home-path leakage |
| JYD-RQ-020 | Preserve the editor-neutral fallback | Director | Standard repair kit and `nle-package-v2` remain current even if native generation fails |
| JYD-RQ-021 | Treat actual Jianying usability as a named-user gate | HongRun | Current installed-version canary completes five edit tasks and records explicit judgment |
| JYD-RQ-022 | Revalidate a manually exported result | Director | Exact returned bytes pass full decode, captions, audio, visual, edit-correctness and platform QA |
| JYD-RQ-023 | Bound storage and generation cost | Director | Linked/portable mode estimate; configured budget; no duplicate full render |
| JYD-RQ-024 | Make unsupported assets explicit | Adapter | Every missing/incompatible layer has typed status/reason; no fabricated native editability |

## Non-goals

- Controlling Jianying UI, clicking export, or publishing.
- Modifying, merging into, or reading content from an existing user draft.
- Reverse-engineering new private formats inside the stable Skill.
- Reproducing Jianying proprietary effects, transitions, filters, stickers, or
  templates as native v1 objects.
- Turning HyperFrames DOM/tween internals into Jianying effect parameters.
- Claiming cross-version compatibility before an exact-version canary.
- Making the adapter production-default in v1.

