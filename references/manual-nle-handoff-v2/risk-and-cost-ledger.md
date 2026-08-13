# Risk and cost ledger

| ID | Risk | Severity | Mitigation / fallback |
|---|---|---|---|
| NLE-RK-001 | Jianying alpha codec support differs by version/device | high | Versioned manual canary; PNG-sequence fallback; never claim unverified compatibility |
| NLE-RK-002 | Package size explodes with full-duration alpha and PNG sequences | high | Package levels, size estimate/budget, event-local default, optional convenience layer |
| NLE-RK-003 | Text is baked inside motion and not editable | high | Text-free overlay plus copy/style JSON; label baked copy reference-only |
| NLE-RK-004 | SRT loses semantic emphasis styling | medium | Preserve SRT editability plus emphasis plan/ASS visual reference; manual styling guide |
| NLE-RK-005 | Clean A-roll is not actually clean | high | Negative-layer evidence, source/reference comparisons, human spot check |
| NLE-RK-006 | Layer offsets drift after import | high | One rational timeline, zero-based convenience layers, markers, frame/time parity canary |
| NLE-RK-007 | Audio stems do not recompose to reference | high | Exact plan/cue binding, PCM measurements, full-duration aligned stems, parity receipt |
| NLE-RK-008 | IP/font assets are redistributed without rights | high | Rights manifest, identity mode, no copy without explicit redistribution authority |
| NLE-RK-009 | Native draft adapter breaks after app update | high | Keep out of stable release; separate gated adapter; editor-neutral fallback |
| NLE-RK-010 | External/Junction path causes data escape | high | Lexical-root safe helpers, preflight, atomic staging, real Windows Junction tests |
| NLE-RK-011 | Partial package is mistaken for complete | high | Complete inventory, atomic publish, unavailable rows, nested artifact tracking |
| NLE-RK-012 | Human edits damage captions/audio/meaning | high | Immutable reference, correction summary, full returned-file revalidation |
| NLE-RK-013 | Generating every layer wastes time/tokens/render budget | medium | Reuse hash-current render cache; only derive requested package level; canary before full |
| NLE-RK-014 | User expects native effect controls from imported video layers | medium | Editability-class labels and guide; HyperFrames retained for deep internal edits |
| NLE-RK-015 | Outro/IP module becomes generic template clutter | medium | Profile/semantic binding and user review; optional removal remains easy |
| NLE-RK-016 | Compatibility docs become stale | medium | Record app version/date; expire claims on major-version change or failed canary |

## Cost model

- Low: SRT, JSON, OTIO, copy/style guides, manifests, existing source assets.
- Medium: clean A-roll and aligned audio stem derivation.
- High: alpha event renders, full-duration alpha composite, PNG sequences, and
  repeated Jianying import tests.

Recommended default is `balanced`. `max_editable` requires an estimated output
size and explicit acceptance when it exceeds the project budget.

