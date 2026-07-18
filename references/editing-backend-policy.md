# Editing Backend Policy

The workflow owns preservation policy. Backends provide evidence or execution primitives; they do not decide what meaning may be removed.

## Baseline

- Make video-use the required owner of the word transcript, EDL, cut timeline,
  output remapping, and edit validation. A cached local Faster-Whisper result may
  be adopted only through a hash-recorded schema conversion that changes no text
  or timing; provider choice does not transfer ownership back to this Skill.
- Preserve the raw transcript, cleaned transcript, and backend metadata.
- Cut speech on word boundaries, usually with 30–200 ms context padding.
- Add about 30 ms audio fades at new cut boundaries.
- Extract or encode segments once where practical, then concatenate. Avoid needless double encoding.
- Shift overlays to the output timeline and apply subtitles last.
- Review waveforms and adjacent frames at every new cut boundary.

## FunClip and FunASR

Use as an optional Chinese backend when product hotwords, multiple speakers, emotion/audio-event labels, transcript-selected candidate ranges, or local browser review are valuable. Its result is a transcript or candidate EDL. Under `preserve` mode, never execute a deletion merely because FunClip proposed it.

## Auto-Editor

Use only in analysis mode to propose silence, loudness, motion, or subtitle-based ranges. Save the command, thresholds, raw candidate ranges, and tool version. Cross-check each proposed removal against the transcript and screen activity.

Long silence, low motion, or missing subtitles are evidence, not permission to delete. Do not let Auto-Editor overwrite source media or directly produce the approved EDL.

## video-use

Load `/video-use` for every director run. Use its helpers and artifact contract
for word selection, segment extraction, output-timeline subtitle remapping,
per-segment fades/concat, overlays, subtitles-last composition, and final
boundary validation. Cloud transcription is not mandatory when a valid cached
word transcript exists, but a summary-caption file is never an acceptable
substitute.
