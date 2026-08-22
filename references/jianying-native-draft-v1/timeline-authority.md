# Authoritative timeline mapping

## Source hierarchy

1. video-use `edl.json` owns source-to-output cuts and gaps.
2. `layer-timeline.json` owns parallel layer placements on the output timeline.
3. `master.srt` owns caption text and output times.
4. semantic brief and Storyboard bind semantic IDs to render event IDs/windows.
5. audio/outro plans own their event-local placement and gain decisions.
6. The Jianying draft owns none of these decisions.

## Canonical timebase

The plan stores rational frame rate `{numerator, denominator}` and integer frame
positions. Variable-frame-rate sources must first use the already approved
constant-output timeline or become `action_required`.

For an authority time `t`:

```text
frame(t) = floor(t * numerator / denominator + 0.5)
start_frame = frame(start_seconds)
end_frame = frame(end_seconds)
duration_frames = end_frame - start_frame
```

Every interval requires finite `start >= 0`, `end > start`, and
`duration_frames > 0`. The adapter converts frames to native microseconds/ticks,
then reads its own result back. Round-trip error must be at most 0.5 output frame
per boundary and must never reorder or overlap captions that did not overlap in
the authority.

## Inventory equality

- Base clip inventory equals EDL output ranges for a clean reconstruction or one
  declared full-duration candidate for repair mode.
- Caption IDs/order equal the complete SRT segment inventory.
- Motion layer semantic/render IDs equal the approved render-event subset.
- Audio cue IDs equal current cue decisions; silent decisions create no clip.
- IP/outro layers equal only current available roles.
- Extra native timeline clips are forbidden.

## Gaps, transitions and speed

V1 preserves explicit gaps as empty output time. It supports only constant-speed
clips already represented by the EDL. Native transitions and speed ramps are
not generated; a current project requiring them is `action_required` unless the
clean full-duration base already contains them and repair mode is selected.

## Parity

Before real import, reconstruct a reference composite from projected source
assets outside Jianying and compare it to the automatic reference at event
boundaries, caption midpoints and audio cue windows. This proves the projection
plan, not Jianying rendering. Actual editor parity remains a canary observation.

