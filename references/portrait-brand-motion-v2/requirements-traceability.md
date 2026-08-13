# Requirements Traceability

Status: design-freeze candidate

Canonical objective:
`E:\Projects\Skills\content-preserving-video-editor\references\portrait-brand-motion-v2\goal-objective.md`

Canonical objective SHA-256:
`593da5b11bc07c5188b24fd9e0a2e010472ec60c21677efb94c60a14674407d6`

## Product decision

This is a real requirement. The portrait canary proved that the workflow can
produce a technically valid, captioned, audible, source-preserving candidate
while still missing the creator's brand taste. The defect is not merely low
event count. The current talking-head route selected three generic MQE recipes
and rendered safe top-of-frame cards whose visual language resembles a product
demo. More cards or a fixed event cadence would intensify the mismatch.

Continue with a separate HongRun portrait expression layer. Do not replace the
stable Director, MQE, video-use, HyperFrames, caption, audio, or delivery gates.

## Definitions

- **Portrait talking head**: a person-first source whose face, gesture, voice,
  expression, and captions are the primary viewing subjects.
- **Brand language**: repeatable visual, temporal, and sonic decisions that a
  named user approves for reuse; it is not a color preset.
- **Expressive**: increases emotional or explanatory impact through hierarchy,
  rhythm, spatial depth, camera treatment, typography, light, or sound.
- **Cool / cinematic**: visually polished, layered, and intentional without
  copying proprietary templates, distracting from speech, or using random
  effects.
- **Quiet beat**: an evidence-backed decision to let the person and source carry
  the moment; it is not missing work.
- **Brand-taste pass**: an explicit named-user approval of exact review bytes.
  Automated or multimodal actors may reject or recommend but cannot approve it.

## Requirement matrix

| ID | Requirement | Observable outcome | Non-goal | Owner | Planned proof |
|---|---|---|---|---|---|
| PBM-RQ-001 | Preserve person-first hierarchy | Face, eyes, mouth, expressive hands, speech, and captions remain primary at every phase | Filling empty regions with cards | Director constraints + HyperFrames | protected-region and four-phase composite evidence |
| PBM-RQ-002 | Replace product-demo card language | Talking-head default uses type, light, depth, camera, gesture, and semantic cutaways; opaque rounded cards require an explicit semantic exception | Renaming existing cards | portrait grammar compiler | recipe-family and rendered-DOM negative tests; user format-fit review |
| PBM-RQ-003 | Create a recognizable HongRun signature | Repeated dot-to-orbit-to-focus geometry, luminous accents, controlled typographic weight, and a related sonic motif form a coherent identity | Putting a logo on every effect | portrait brand profile | profile/token hashes, Golden comparison, user identity-fit approval |
| PBM-RQ-004 | Make motion richer without mechanical density | Every meaningful opportunity records quiet/micro/meso/macro intent and an energy transition; event count is diagnostic only | One effect every N seconds or minimum event quotas | energy-map compiler | decision-complete map, no-cadence tests, paired playback |
| PBM-RQ-005 | Synchronize with actual delivery | Motion lands on word boundaries, gestures, emotional turns, or chapter changes; broad narration windows do not create long static overlays | Arbitrary beat grids | video-use words + Director energy map | timing/gesture evidence and onset tolerances |
| PBM-RQ-006 | Provide distinct structural variety | Eight initial portrait recipes have different hierarchy, geometry, choreography, and use cases | Color/entrance variants counted as new structures | portrait recipe registry + HyperFrames | schema fingerprints, DOM/layout/motion fingerprints, contact sheets |
| PBM-RQ-007 | Use camera and depth safely | Push, crop, parallax, subject separation, and masks require source/subject evidence and deterministic fallback | Face warping, guessed mattes, or unreviewed reframing | Director evidence + HyperFrames; optional adapters | subject/face/hand track binding, crop and parity gates |
| PBM-RQ-008 | Integrate semantic cutaways | Cutaways or IP/illustrations are brief, topic-relevant, source-evidenced, and compositionally integrated | Full-frame unrelated white-background illustrations | Director semantic/asset request + HyperFrames | provenance, topic fit, padding/anatomy, entrance/mid/exit evidence |
| PBM-RQ-009 | Establish a coherent sonic identity | Three to five motif families share a recognizable tonal envelope while remaining perceptually distinct and speech-safe | A unique random sound for every event or sound on every event | Director audio policy + FFmpeg | decoded PCM identity, onset, masking, loudness, family fingerprint |
| PBM-RQ-010 | Adapt to source luminance and framing | Light and dark adaptive palettes preserve at least 4.5:1 composite readability and avoid face/hand/caption/platform UI zones | One brown/black panel style for all sources | brand profile + adaptive layout | composited contrast and protected-region measurements |
| PBM-RQ-011 | Compare style, not content | Three 30–45 second Style Reels use identical source windows, captions, semantic events, mix policy, and duration | Comparing different scripts or different edit timelines | Director style-reel plan | source/event/hash equality and paired review |
| PBM-RQ-012 | Keep subjective authority honest | Automated gates prove mechanics; multimodal review rejects/recommends; HongRun alone approves brand taste and repeat-use willingness | Aggregate aesthetic score or agent self-approval | Director review | actor-specific signed/hash-bound decision fields |
| PBM-RQ-013 | Create a durable Golden | Approved direction yields a provisional portrait Golden; production default requires a second materially different portrait topic | Overfitting the `告别2025` clip | editorial regression + user review | two real-project receipts bound to the same implementation/profile version |
| PBM-RQ-014 | Preserve existing workflow behavior | Feature is default off for migrated and non-HongRun projects; screen/product and third-party modes remain unchanged | Applying HongRun style to all portrait footage | project migration + identity policy | legacy fixtures, third-party negative tests, config byte preservation |
| PBM-RQ-015 | Fail safely and recover cheaply | Missing tracking, runtime, asset, license, or Golden evidence selects a declared simpler recipe, quiet/caption treatment, or action_required | Silent generic-card fallback | Director compiler/invalidation/cache | negative tests and event-scoped invalidation receipts |
| PBM-RQ-016 | Avoid proprietary imitation | Borrow general principles such as masking, easing, rhythm, and layering while using original assets/components and verified licenses | Copying Jianying/CapCut templates, sounds, names, or protected assets | governance and license gates | provenance/license inventory and forbidden-source tests |
| PBM-RQ-017 | Keep review effort practical | One review page shows three aligned reels, event rationale, phase contact sheets, SFX/BGM toggles, and exact user questions | Reviewing scattered JSON or full videos before direction approval | Director review surface | desktop/mobile browser test and observed correction time |
| PBM-RQ-018 | Bound performance and cost | Standard recipes use DOM/SVG/GSAP; expensive tracking/matting/Remotion/WebGL paths are explicit, cached, and default off | Requiring GPU or paid cloud generation | capability registry + governance | cost ledger, cache keys, fallback and resume tests |

## Positive examples

- “人生无常” lands as a short variable-weight phrase: a luminous orbit traces
  behind the words, the frame gently pushes toward the speaker, then both settle
  within 1.4 seconds. No persistent card is created.
- “上半辈子 / 下半辈子” uses a person-centered spatial split whose two phrases
  occupy opposite depth planes. The speaker remains visually central and the
  comparison disappears before the next idea.
- “找回开心” receives a warm light transition, upward phrase motion, and a
  three-note resolution motif tied to the emotional change.

## Negative examples

- A dark rounded rectangle is placed above the speaker with the spoken keyword.
  It fails PBM-RQ-002 even if it fits the safe zone.
- Five effects are inserted only because ten seconds elapsed. It fails
  PBM-RQ-004 even if every effect has a different filename.
- A generated illustration replaces the full frame but does not add information
  beyond the caption. It fails PBM-RQ-008.
- A Style Reel uses different sentences for each direction. It fails PBM-RQ-011.

## Boundary examples

- A strong emotional pause may remain visually quiet. A subtle source-aware
  grade or no overlay is valid when the energy map records the reason.
- A low-light source may use the dark-adaptive palette, but must not default to
  an opaque brown product card.
- If subject matting is unavailable, a depth recipe may fall back to face-safe
  kinetic typography. It may not invent a silhouette mask.

## Trace index

| Design artifact | Requirements |
|---|---|
| `brand-aesthetic-spec.md` | PBM-RQ-001–004, 010, 012–013, 016 |
| `motion-language-v2.md` | PBM-RQ-001–008, 010, 015–016, 018 |
| `sonic-language-v2.md` | PBM-RQ-005, 009–010, 015, 018 |
| `architecture-and-tool-boundaries.md` | PBM-RQ-005–018 |
| `machine-contracts.md` and `schemas/` | PBM-RQ-003–015, 017–018 |
| `style-reel-plan.md` | PBM-RQ-003, 006, 009–013, 017–018 |
| `acceptance-matrix.md` | all requirements |
| `migration-and-rollback.md` | PBM-RQ-013–015, 018 |
| `implementation-plan.md` | all requirements |
