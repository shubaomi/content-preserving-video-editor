# Acceptance matrix

| Gate | Automated evidence | Human evidence | Blocks |
|---|---|---|---|
| Canonical authority | EDL/layer timeline/SRT/Storyboard/audio hashes current; ordered inventories exact | — | Plan |
| Disabled behavior | No output/store access under default and migrated configs | — | Integration |
| Safe root | Traversal, symlink, Junction, target-exists and partial-build tests | — | Any write |
| Adapter provenance | Exact version/artifact hash/license/security policy | — | Generation |
| Editor compatibility | Exact detected version and approved tuple | Current-version canary | Install/promotion |
| Draft integrity | Complete no-extra-file inventory; deterministic rebuild | — | Package pass |
| Metadata privacy | No device/account/home/cache/cloud identifiers | — | Package pass |
| Timeline | Frame/tick round-trip <=0.5 frame; no extra/missing clips | Visual alignment check | Package pass |
| Captions | Exact SRT inventory; native text round-trip; typed style fidelity | Correct/split/style one cue | Caption editability |
| Base picture | Repair/layered mode truthfully identified; no duplicated pixels/audio | Compare reference | Draft fidelity |
| Motion | Current alpha/event/window binding; no H.264 alpha claim | Move/trim/hide one overlay | Motion editability |
| IP | Current role/rights/window and decodable PNG | Move/remove one image | IP editability |
| Audio | 48 kHz decode; start/duration/gain/cue identity | Mute one SFX | Audio editability |
| Outro | Available roles exact; copy contract current | Change copy/hide icon/SFX | Outro editability |
| Reconstruction | External reference composite within frozen tolerances | Jianying preview comparison | Canary |
| Existing drafts | Before/after store inventory proves zero changes outside new target | User confirms existing projects remain | Canary |
| Returned export | Full decode, caption/audio/visual/edit-correctness/platform QA | User confirms intended edits | Delivery |
| Usability | Task timings/relink/errors recorded | HongRun reuse decision | Real-project maturity |

## Required negative tests

- enabled false still invokes adapter or inspects draft store;
- existing target draft, merge flag, or caller-selected existing ID;
- output root or nested child replaced by Junction/symlink;
- unknown Jianying version or changed draft-layout signature;
- unpinned adapter or mismatched distribution hash/license;
- arbitrary command, URL, token, cookie, device ID, MAC or account field;
- source/home path outside approved asset roots;
- missing/extra/duplicate/reordered timeline item;
- NaN/Infinity/bool timing, gain, scale or opacity;
- VFR authority without a conformed output timeline;
- SRT text/timing drift or UTF-16 emphasis range drift;
- semantic ASS flattened while fidelity says `full`;
- H.264/opaque/empty media labeled alpha;
- duplicated base dialogue or duplicated baked motion;
- wrong event/IP/outro/audio rights or stale hash;
- proprietary effect/transition/template ID in v1;
- partial published directory after adapter failure;
- rollback attempted after installed draft drift;
- native draft failure removes or invalidates neutral fallback assets;
- fixture/agent review promoted as named-user compatibility.

