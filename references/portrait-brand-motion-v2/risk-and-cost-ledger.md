# Risk and Cost Ledger

Status: proposed design controls.

## 1. Risk ledger

| ID | Risk | Likelihood | Impact | Control | Stop/rollback trigger |
|---|---|---:|---:|---|---|
| PBM-R-001 | “Richer” becomes higher event count and visual noise | high | high | energy map, no cadence/quota, user expressive-not-noisy gate | user rejects noise or person primacy |
| PBM-R-002 | Existing product cards are renamed as portrait recipes | high | high | DOM/layout/fingerprint negative tests and forbidden default | generic card fallback appears |
| PBM-R-003 | Design overfits one low-light reflective clip | high | high | provisional Golden + second different topic | second-topic failure |
| PBM-R-004 | Camera/depth harms face or looks artificial | medium | high | subject/face/hand/crop/mask evidence and deterministic fallback | unverified mask/crop or user artifact rejection |
| PBM-R-005 | Gesture path follows the wrong hand/limb | medium | high | verified track, active window, anatomy/topology review | lost/ambiguous hand evidence |
| PBM-R-006 | Kinetic type repeats subtitles | medium | high | approved phrase authority and visible-text DOM/OCR gate | extra/unapproved text |
| PBM-R-007 | Advanced runtimes increase failures and render cost | medium | medium | base grammar must work in DOM/SVG/GSAP; advanced default off | no deterministic 2D fallback |
| PBM-R-008 | SFX masks speech or becomes repetitive | medium | high | decoded-PCM, onset, masking, family, actual-mix review | inaudible/distracting cue or unsafe peak |
| PBM-R-009 | Proprietary imitation or unlicensed assets | low | high | original components, provenance/license gate, forbidden imports | missing/unclear rights basis |
| PBM-R-010 | Subject media/face data leaks to cloud | low | high | local default; explicit provider/privacy/cost authorization | unapproved external upload |
| PBM-R-011 | Review asks too much of the user | medium | medium | one synchronized page, six focused questions, event proposals | correction/review time disproportionate |
| PBM-R-012 | New schema changes old projects | low | high | v11 additive in-memory migration, disabled default, byte preservation | legacy fixture/project diff |
| PBM-R-013 | Automated QA is mistaken for taste approval | medium | high | actor separation and named-user exact-byte gate | agent/multimodal approval field |
| PBM-R-014 | Three Style Reels compare different content | medium | high | common-basis contract and equality gate | any source/EDL/event/caption/audio drift |
| PBM-R-015 | Style assets inflate repo/project storage | medium | medium | reusable shared components, event cache, isolated review outputs | duplicate large assets without reuse |

## 2. Cost units

Every implementation stage records:

- local CPU/GPU time;
- HyperFrames/browser/render wall time;
- generated media bytes and reusable cache savings;
- paid provider request/reservation/actual cost when applicable;
- LLM/token use when available from the host;
- human review and correction minutes;
- number of affected events rerendered after a correction.

No cost estimate is a completion fact until measured.

## 3. Cost order

1. schema/static/fixture validation;
2. isolated component/browser snapshots;
3. synthetic short media;
4. three 30–45s real Style Reels;
5. one second-topic 30–90s candidate;
6. full video only after the brand direction and portability gates.

Failures at a cheaper stage block more expensive work.

## 4. Pseudo-needs rejected

- exact Jianying/CapCut visual equivalence;
- dozens of recipes before eight high-quality recipes are proven;
- an effect every fixed number of seconds;
- every effect carrying a different SFX;
- one automated aesthetic score;
- GPU/3D/generative assets as the standard path;
- three full finished videos instead of three short isolated Style Reels;
- promotion after only the `告别2025` clip.

## 5. Residual user decisions

- select, revise, or reject all Style Reel directions;
- decide whether the selected language feels personally recognizable;
- approve the sonic identity and acceptable intensity;
- approve repeat use after the second topic;
- separately authorize any paid/cloud provider, full-video render, publication,
  or manual NLE finishing.
