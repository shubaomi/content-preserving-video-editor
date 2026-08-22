# Native track contracts

## Deterministic order

| Order | Track ID | Content | Required |
|---:|---|---|---|
| 0 | `video.base` | Clean A-roll or repair candidate | yes |
| 10–99 | `video.motion.<event_id>` | Event-local transparent overlay | layered profile only |
| 100–149 | `video.ip.<asset_id>` | Authorized rendered PNG/IP layer | when available |
| 150–189 | `video.outro.*` | Background, overlay, icons | when available |
| 200 | `text.captions` | One native segment per SRT cue | yes unless explicit caption opt-out |
| 210 | `text.outro` | Native CTA copy | when modular outro copy exists |
| 300 | `audio.dialogue` | Dialogue stem only with silent base | conditional |
| 310 | `audio.bgm` | BGM stem | when authorized/enabled |
| 320–399 | `audio.sfx.<event_id>` | Event-local SFX | for cue decisions only |
| 900 | `reference.master` | Disabled/locked automatic reference | optional canary aid |

Track IDs and layer IDs are stable derivations from authority IDs; display names
are Chinese but are not identity authorities.

## Machine-enforced invariants

The frozen plan Schema records role-specific payloads rather than a generic
media clip: caption text and UTF-16 emphasis ranges, video alpha and transform,
IP rights receipt and protection windows, 48 kHz audio gain, modular outro role,
and the disabled locked reference state. The validator must additionally enforce
cross-record rules that JSON Schema cannot express compactly:

- track IDs, orders, clip IDs, cue IDs and event IDs are unique and deterministic;
- track `kind`, clip `role` and payload `type` form an allowed tuple;
- every clip ends within canonical duration and inventories equal authorities;
- caption emphasis ranges are ordered, non-overlapping and within UTF-16 text;
- semantic/render IDs are mandatory only for event-bound motion/SFX;
- repair and layered profiles obey their distinct base/audio/duplication rules;
- every file reference resolves under an approved root and matches SHA-256;
- `plan_sha256` is calculated over canonical JSON with that field omitted.

## Base picture

`repair_draft` uses the full pre-caption candidate and marks
`motion_editability=baked`. `layered_reconstruction` requires a current clean
A-roll whose audio policy is explicit. A base with embedded dialogue must not be
combined with a dialogue stem. No layer may duplicate pixels already present in
the chosen base.

## Captions

- UTF-8 SRT is authoritative; one cue becomes one native text segment.
- Text, order and frame boundaries must round-trip exactly within 0.5 frame.
- Base font, size, alignment, outline and color come from the caption style plan.
- Per-range bold/color/scale is used only when the adapter supports it and a
  generated-draft round-trip test returns the same UTF-16 range boundaries.
- Unsupported emphasis is labeled `degraded` and falls back to base native style
  plus attached ASS reference; it is never silently described as full fidelity.
- Line wrapping is editor-display behavior; it may not change authoritative text.

## Motion

Each render event uses one decoded alpha-capable layer with exact start/end
frames. V1 supports move, scale, opacity, trim, hide and replace at clip level.
It does not expose internal HyperFrames nodes or easing. Standard H.264 cannot be
labeled transparent. If ProRes 4444 fails the exact editor canary, the profile
may test a PNG sequence in a later approved change; it may not switch silently.

## IP assets

Only role-specific rights-approved assets enter the draft. Prefer transparent
rendered PNG for editor compatibility; retain original SVG/source references in
the package but do not claim native SVG editing without evidence. Face/product
protection and semantic windows remain metadata and review markers.

## Audio

Use decoded current stems, normally 48 kHz. Native volume is derived from the
approved linear gain and must round-trip within 0.1 dB. Cue onset error is at
most the existing event tolerance. No auto-ducking, normalization, denoise or
effect is added by the adapter. The automatic master remains the audible parity
reference.

## Outro

Project text-free background/overlay, icons, CTA copy and SFX as separate roles.
Native copy must equal the current copy contract. If only a baked reference is
available, mark the outro baked and do not fabricate editable sublayers.
