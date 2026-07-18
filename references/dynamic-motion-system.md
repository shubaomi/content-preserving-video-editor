# Adaptive Dynamic Motion System

## Why this exists

The former `sparse` preset intentionally capped a full video at three to five
visual beats.  It protected source clarity, but made instructional and
talking-head edits feel visually static.  This system keeps source content
intact while planning short, semantic, auditable attention events.

## Delivery phases

1. **Foundation (implemented):** versioned motion profiles, deterministic
   confidence-first semantic event planner, visual/SFX vocabularies, and a
   semantic/layout audit.
2. **Renderer integration (implemented):** map events to independently editable
   HyperFrames host/motion/surface layers and separately mixed audio tracks.
3. **Project proof (in progress):** build isolated `dynamic-motion-v1`
   variants, run the automated and visual QA gates, and record the evidence
   paths here.

## Non-negotiable rules

- `calm`, `balanced`, and `adaptive_dynamic` are user-level profiles; the
  latter is the approved default for HongRun tutorial and talk content.
- An event is an explanation, not decoration. It must carry transcript or
  visual evidence, a purpose, collision result, and an intentional quiet/skip
  reason when no event is placed.
- Event-rate ranges are quality-bounded targets with blocking lower and upper
  bounds for `balanced` and `adaptive_dynamic`. Never fill a quiet interval
  with a low-confidence card merely to reach the lower bound; instead improve
  transcript segmentation, cover an overlooked semantic beat, use a source-
  native annotation/zoom, or record an explicit user-approved sparse override.
- A transition or UI verb (`然后`, `打开`, `添加`, `点击`) is not a visible
  semantic anchor by itself. Require a compact object, topic, result, contrast,
  or measured value; reject sentence-length anchors.
- Require project-glossary evidence before promoting an unfamiliar title-cased
  English STT token. A plausible product-name homophone is not publishable text.
- Limit an exact anchor to two occurrences per video by default and keep at
  least 40 seconds between those occurrences.
- A complete sentence remains a complete sentence. At most three key terms
  may receive emphasis. Existing burned captions receive keyword-level
  support only, never a duplicate full subtitle layer.
- Motion never permanently alters source pixels, source timing, or the source
  speech track. BGM, original audio, and SFX stay independently controllable.
- `pending` geometry or redundancy is a failed gate, not evidence. Never use
  layout overflow/occlusion opt-outs to silence it.
- Every planned variant must have a distinct render contract and real renderer
  behavior. A renamed copy of the same card, a swapped glyph, or a changed
  border is not a different variant.
- A failed semantic, safety, caption, audio, or decode gate blocks release.

## Advisory budgets and blocking ceilings

| Mode | Recommended events/minute | Blocking event ceiling | Default SFX ceiling | Caption handling |
| --- | ---: | ---: | ---: | --- |
| `screen_tutorial` | 3.5–6 (`adaptive_dynamic`) | 6/minute | 6/minute and 35% of events | compact topic/object plus up to 3 highlights |
| `polish_existing` | 2.5–4.5 (`adaptive_dynamic`) | 4.5/minute | 6/minute and 35% of events | preserve burned captions; compact keyword/tag/icon only |

The planner permits quiet source-dense, face-sensitive, platform-UI, or
low-confidence intervals. A long quiet exception is valid only after visual
review stores a verified evidence kind and at least one sample path; generic
prose such as “source UI is primary” is insufficient. Family variety is an
advisory review signal; semantic fit takes priority over mechanical rotation.

## Validation evidence

Implementation results, modified files, and per-project render evidence are
appended as each phase finishes. This file deliberately never treats a planned
feature as a completed render.

### 2026-07-13 historical implementation evidence

- Added `scripts/attention_planner.py`, `scripts/motion_density_audit.py`,
  `scripts/build_local_sfx_library.py`, `scripts/build_dynamic_hyperframes.py`,
  and `scripts/slice_attention_plan.py`.
- Added `references/motion-vocabulary.json`, `references/sfx-palette.json`,
  and the approved HongRun light-motion identity document.
- Expanded profile `hongrun-approved.json` to schema version 2 without
  rewriting history; the approved provenance is recorded verbatim.
- Full automated regression: `python -m unittest discover -s tests -v` passed
  40 tests. Skill quick validation passed under UTF-8 mode.
- The former TabOut plan had 53 events (8.546/min, 19 SFX) and GPT Live had 49
  events (7.494/min, 20 SFX). Those counts passed the old numerical audit but
  are not quality evidence. User review rejected the TabOut result for repeated
  low-information anchors, card repetition, overlap, and overflow.
- Both rebuilt dynamic HyperFrames projects passed `npx hyperframes check
  --samples 15` with zero errors and warnings.
- A 90-second TabOut full-canvas sample rendered and fully decoded with H.264
  video and AAC audio. The older WebM overlay encoder did not retain alpha.
  A CSS key color inside an `--overlay-only` export was also verified to become
  opaque black, so it is explicitly rejected. The replacement fallback uses an
  opaque key-color baseline and compositor coverage validation; its real sample
  composition is in progress.
- On 2026-07-15 the planner, renderer, audit, tests, and this contract were
  revised to make semantic confidence and resolved geometry blocking. Old
  dynamic plans must be regenerated and cannot be grandfathered into release.
