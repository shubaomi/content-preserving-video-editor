# Existing Edit Polish Mode

Use `workflow.input_mode: polish_existing` when the input has already been edited in Jianying/CapCut or another NLE, already contains subtitles/BGM/transitions/cover material, or has already been published.

Current automation status: `implemented` for hard-caption/subtitle-stream detection, conservative embedded-mix handling, transient SFX candidates, monotony analysis, transcript-anchored enhancement planning, incremental baseline-audio reuse, and variant verification. The workflow deliberately does not claim source separation or certain music classification from energy alone.

## Preservation contract

- Treat the supplied master as the baseline and preserve it unchanged.
- Do not recut, reorder, retime, retranscribe, replace music, replace captions, or replace the cover by default.
- Do not stack a second subtitle layer over burned-in captions.
- Keep the existing mix unless measurement finds speech masking, clipping, or a clear defect.
- Create a new polish variant and retain direct comparison with the baseline.

## Low-cost diagnostic first

Before authoring, inspect metadata and sample frames. Determine, with explicit confidence:

- orientation and effective aspect ratio;
- presence of burned-in captions or a subtitle stream;
- likely continuous BGM and existing SFX/transitions;
- chapter changes and long visually repetitive intervals;
- existing cover availability and whether it is usable;
- privacy, rights, and platform-safe-zone risks.

Reuse embedded subtitle streams, sidecar files, or project exports when available. Run local STT only when timing/content cannot otherwise be recovered; do not default to cloud transcription.

## Enhancement budget

Default adaptive scope for a 3–10 minute existing edit:

- an advisory 3–7 semantic attention events per minute, with 7/minute as the default ceiling rather than a quota;
- use micro, meso, and macro events rather than one repeated card;
- generate 0–2 topic images only when an abstract idea cannot be clarified by footage, typography, or annotation;
- reuse existing BGM and most SFX;
- keep the existing cover unless it fails identity, readability, ratio, or topic-fit gates;
- allow one targeted repair pass.

These are review ranges, not quotas. Fewer enhancements are correct when the existing edit already communicates well.

## Visual routing

- Prefer cursor focus, crop/zoom, underline, arrow, small pull quote, progress marker, or picture-in-picture.
- Keep one primary explanatory visual per beat.
- Avoid covering existing burned-in captions, faces, gestures, or important source content.
- Use topic IP images only as integrated picture-in-picture, split panel, mask reveal, or transparent components; do not paste a full-screen white image inside continuous footage.
- Match the existing video's design tokens rather than forcing a new theme.

## Audio routing

- Detect or infer existing music before adding any bed.
- Do not add a second BGM track.
- Sound no more than 35% of visual events and 6 SFX/minute by default; skip it when the source already has an equivalent sound or the cue risks masking speech.
- Measure speech dominance and clipping; do not remix solely because the original settings differ from a generic preset.

## Cover handling

- Treat the original cover as an input asset under `source/cover/`.
- Keep it by default.
- Put generated or revised covers under the project-level `covers/` directory.
- Rebuild only when identity, text, topic, aspect, or crop QA fails.

## Deliverables

- untouched baseline master;
- polish candidate;
- enhancement beat list with implemented/skipped reasons;
- baseline-versus-polish snapshots;
- newly added asset/SFX manifest;
- QA report and final decode evidence.
