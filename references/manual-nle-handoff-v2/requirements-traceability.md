# Requirements traceability

| ID | Requirement | Owner | Frozen acceptance evidence |
|---|---|---|---|
| NLE-RQ-001 | Preserve the automatic universal MP4 as immutable reference/fallback | Director | Package manifest binds path/hash; no handoff step overwrites it |
| NLE-RQ-002 | Produce a clean edited A-roll without motion, captions, BGM, or SFX | video-use + Director/FFmpeg | Decode, duration/timeline, voice-presence, and negative-layer checks |
| NLE-RQ-003 | Provide UTF-8 SRT as editable caption authority | video-use | SRT equals current `master.srt` bytes/hash and output timeline |
| NLE-RQ-004 | Preserve semantic emphasis without pretending SRT carries rich style | Director caption treatment | ASS reference plus per-caption emphasis instructions bind word IDs, text, colors, weight, and scale |
| NLE-RQ-005 | Provide removable event-local motion overlays | HyperFrames + Director | One overlay per render event, exact event window, alpha proof, black/white composite tests |
| NLE-RQ-006 | Optionally provide a zero-based full-duration motion overlay for easy alignment | Director/FFmpeg | Same canvas/fps/duration; sparse-alpha and recomposition parity checks |
| NLE-RQ-007 | Provide separable dialogue, BGM, and SFX audio | Director audio owner | PCM/AAC decode, 48 kHz alignment, plan/hash binding, recomposition measurement |
| NLE-RQ-008 | Preserve personal-IP illustrations as editable reusable assets | Profile + HyperFrames | Source PNG/SVG/license/provenance plus rendered event overlay; no synthetic missing files |
| NLE-RQ-009 | Deliver modular follow/like/share outro | Director + HyperFrames | Text-free background/overlay, icons, copy JSON, timings, audio stems, reference composite |
| NLE-RQ-010 | Keep all layers aligned to one output timeline | video-use + Director | Timeline manifest uses one rational rate/timebase and exact output offsets |
| NLE-RQ-011 | Make the package usable without native Jianying draft generation | Director | Human import guide and ordered track map; native API flags remain false |
| NLE-RQ-012 | Support Jianying Desktop first while remaining editor-neutral | NLE adapter | `jianying_desktop_compatible_v1` profile is a compatibility profile, not a backend runtime claim |
| NLE-RQ-013 | Expose the editable HyperFrames project for deep motion changes | HyperFrames | Project manifest, source hashes, Studio instructions, renderer evidence |
| NLE-RQ-014 | Mark unavailable optional assets truthfully | Director | Typed status/reason with null hash; completion cannot infer availability |
| NLE-RQ-015 | Bind rights, font, identity, and asset provenance | Director/Profile | Rights manifest covers every distributable file; fonts copied only when redistribution is authorized |
| NLE-RQ-016 | Avoid unbounded storage and rendering cost | Director | Package levels and explicit size estimate/budget; full-duration alpha is optional |
| NLE-RQ-017 | Fail closed on path escape, Junction/symlink redirection, stale hashes, or partial packages | Director | Safe-root/atomic-package tests and full nested inventory validation |
| NLE-RQ-018 | Revalidate a returned manual edit against exact bytes | Director | Existing return receipt, full decode, caption/audio/visual/edit-correctness/platform QA |
| NLE-RQ-019 | Keep expanded layered/manual-return behavior default-off while making the minimum repair kit a normal delivery invariant | Director + Config migrator | Every completed full render binds master, pre-caption candidate, SRT, ASS/style plan and HyperFrames inventory; transparent layers/audio/IP/outro and human return remain opt-in |
| NLE-RQ-020 | Treat actual import/edit convenience as a human canary, not an automated claim | HongRun | Jianying Desktop canary records import result, relink friction, editability, and user judgment |
| NLE-RQ-021 | Preserve semantic/product soft-occlusion behavior in the reference, while making it removable | HyperFrames + Director | Overlay event carries semantic/window/protected-region evidence; removal leaves clean A-roll intact |
| NLE-RQ-022 | Do not require keys, encryption, cloud sync, or a Jianying login to build the package | Director | Local deterministic generation; no secret/env-token fields in schema |

## Non-goals

- Automatically editing inside Jianying or controlling its UI.
- Writing or reverse-engineering a private native Jianying/CapCut draft format in
  this release.
- Reproducing Jianying proprietary effects as editable native effect objects.
- Guaranteeing every alpha codec works in every Jianying version/device without
  a current import canary.
- Making baked text inside an overlay natively editable. Editable copy is
  provided separately; the text-free layer is the modification surface.
- Replacing the HyperFrames project as the deep-edit source of truth.
