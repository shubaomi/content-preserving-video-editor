# Architecture and tool boundaries

## Decision

Add a `manual_nle_package_v2` capability behind the existing default-off
`delivery.manual_finish` stage. It produces an editor-neutral package with a
Jianying Desktop compatibility profile. The package is a set of media, text,
timeline, source, and evidence artifacts; it is not a Jianying project file.

## Ownership

| Concern | Owner | May not claim |
|---|---|---|
| Source words, EDL, clean timeline, caption timing | video-use | Motion authorship or brand styling |
| Meaning, package policy, profile/IP governance, QA, return revalidation | Director | Native NLE runtime/API |
| Motion source, component structure, alpha-capable render | HyperFrames | Final audio mix or caption authority |
| Layer extraction, transcode, audio stems, reference recomposition | FFmpeg | Creative replacement for HyperFrames |
| Manual adjustment and native editor effects | Human editor | Automatic Director completion |
| Brand/taste/editability approval | HongRun | Agent-authored approval |

## Processing graph

```text
video-use EDL + clean timeline ----> clean A-roll --------------------+
master.srt ------------------------> editable captions ---------------+
semantic caption plan ------------> style instructions + ASS ref ----+
HyperFrames project/render cache --> event alpha overlays ------------+--> NLE package
audio plan + current assets -------> dialogue/BGM/SFX stems ----------+
profile/IP assets -----------------> source assets + rendered layers --+
outro contract --------------------> modular outro kit ----------------+
all authorities -------------------> timeline/manifest/import guide ---+

automatic universal MP4 ---------------------------------------------> immutable reference
human NLE export -----------------------------------------------------> full revalidation
```

## Current Jianying/CapCut boundary

Official help currently documents SRT/TXT import on Desktop and SRT import on
Web, creating editable caption blocks. It also states that an exported project
re-imported as video does not recover individual layers and that direct
cross-draft import is unsupported. Therefore:

- SRT is the only frozen native-editability claim.
- MOV/PNG/MP4/WAV assets are ordinary imported media, not native effects.
- Alpha MOV compatibility is a canary result, not an unconditional claim.
- The package must include PNG-sequence fallback for transparency.
- Native draft export remains `documented_future_adapter` only.

Primary references:

- https://www.capcut.com/help/how-to-import-subtitles
- https://www.capcut.com/help/import-a-previous-project-into-the-current-project
- https://www.capcut.com/help/can-not-local-assets-be-recognized-during-import
- https://www.capcut.com/create/transparent-video-export-alpha-channels

## Configuration boundary

Proposed additive schema (not implemented in this phase):

```yaml
delivery:
  manual_finish:
    enabled: false
    backend: other_nle
    package_version: 2
    package_profile: jianying_desktop_compatible_v1
    package_level: balanced # reference_only | balanced | max_editable
    include:
      event_motion_layers: true
      full_duration_motion_layer: false
      semantic_caption_instructions: true
      personal_ip_sources: true
      modular_outro: true
      per_event_sfx_stems: false
    alpha_preferences:
      candidates: [prores_4444_mov, png_sequence]
      require_import_canary: true
```

Migrated and third-party projects keep this disabled. Identity policy controls
whether personal-IP and branded outro assets may be included.

## Package levels

- `reference_only`: current manifest plus immutable automatic master and source
  authorities; no new layer rendering.
- `balanced` (recommended): clean A-roll, SRT/style instructions, event-local
  overlays, grouped audio stems, IP/outro source assets, timeline/import guide.
- `max_editable`: balanced plus full-duration convenience overlay, per-event SFX
  stems, PNG-sequence transparency fallback, and expanded source assets.

No package level changes the automatic master or marks human finishing complete.

