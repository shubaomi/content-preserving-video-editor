# Package and layer specification

## Canonical directory

```text
manual-finish/nle-package-v2/
  00-reference/
    automatic-master.mp4
    preview-contact-sheet.jpg
  01-base/
    clean-a-roll.mp4
    dialogue.wav
  02-captions/
    master.srt
    master-reference.ass
    caption-emphasis-plan.json
    caption-style-guide.json
  03-motion/
    all-motion-overlay.mov              # optional convenience layer
    events/<event-id>/overlay.mov
    events/<event-id>/overlay-png/*.png # fallback/package-level dependent
    events/<event-id>/event.json
  04-ip-assets/
    sources/<asset-id>.<png|svg|webp>
    rendered/<event-id>.mov
    ip-assets-manifest.json
  05-audio/
    bgm.wav
    sfx-grouped.wav
    sfx-events/<event-id>.wav
    audio-stems-manifest.json
  06-outro/
    reference-composite.mp4
    background.mp4
    overlay-text-free.mov
    icons/<asset-id>.<png|svg>
    copy.json
    timing.json
    sfx.wav
    bgm.wav
    outro-manifest.json
  07-cover/
    cover.png
    cover-source-assets/
  08-timeline/
    timeline.otio.json
    layer-timeline.json
    markers.csv
    import-order.md                       # Chinese, project-specific guide
    screenshots/
      01-empty-project.png
      02-import-subtitles.png
      03-audio-panel.png
      04-project-settings.png
  09-source-project/
    hyperframes-project/                 # link/copy policy recorded in manifest
    semantic-brief.json
    storyboard.json
    motion-design-contract.json
    audio-plan.json
    edl.json
    transcript.json
  10-evidence/
    nle-handoff-package.json
    rights-manifest.json
    compatibility-report.json
    package-validation.json
    recomposition-parity.json
```

Every optional path exists only when its manifest row is `available`. Directory
names are stable; filenames are ASCII-safe and event IDs are preserved inside
JSON rather than trusted as raw filesystem names.

## Timeline and media invariants

- All video layers use the final output canvas, orientation, rational frame
  rate, color-space declaration, and a zero-based output timeline.
- Event-local overlays record `timeline_start`, `timeline_end`, source event ID,
  semantic event ID, handles, and exact frame range. They may start at zero in
  their own file but never lose their placement metadata.
- The optional full-duration overlay has exactly the clean A-roll duration and
  begins at zero, making drag-and-align import easy.
- Audio uses 48 kHz PCM WAV for editability. Stem duration and initial silence
  preserve output-timeline alignment; an optional event-local view may coexist.
- Captions use UTF-8 SRT for editability. ASS is a visual reference, not a claim
  that Jianying imports its rich styles. The emphasis plan identifies exact
  caption IDs, word IDs, character spans, colors, weight, scale, and timing.
- The import guide is generated in Chinese with the current package canvas,
  frame rate, exact folder order, event-SFX placement warning, five-task human
  canary, and four screenshots captured from a blank Windows Jianying Desktop
  11.1.0.14287 project. Screenshots contain no user media and are part of the
  package's complete hash inventory.
- Clean A-roll contains narration and approved video-use edits but no Director
  motion, burned captions, added BGM, or added SFX.

## Motion overlays

Each rendered motion event provides:

- a transparent event-local overlay when alpha render is supported;
- a PNG-sequence fallback when requested or when the MOV import canary fails;
- a poster/contact sheet for human identification;
- event metadata binding recipe, visible copy, output window, target bindings,
  semantic rationale, protected-region/soft-occlusion decision, and hashes.

Preferred candidate is alpha-capable MOV because MOV is a documented import
container. The codec is not promoted until a current Jianying Desktop canary
proves import, transparency, duration, and frame alignment. Standard H.264 MP4
must never be labeled transparent. PNG sequence is the lossless fallback.

## Personal-IP assets

For every used IP illustration, deliver when authorized:

1. original transparent PNG/SVG/WebP source;
2. rights/provenance and identity-mode record;
3. a text-free or minimally baked rendered overlay;
4. the owning HyperFrames component/project reference;
5. its intended event/window/scale/anchor information.

Third-party identity mode excludes HongRun IP sources. Fonts are referenced by
family/license; font binaries are copied only when redistribution is authorized.

## Modular outro

The follow/like/share outro is not a single mandatory flattened clip. It is a
module with:

- a reference composite showing approved appearance;
- optional background video;
- text-free alpha motion layer;
- separate icons/stickers;
- editable copy and layout/timing JSON;
- separate SFX/BGM stems;
- optional fully flattened outro for quick replacement.

Text inside the alpha layer is allowed only when explicitly marked
`baked_reference_only`. The editable route uses imported icons/media plus copy
and style instructions recreated as native Jianying text. This design does not
claim automatic creation of those native text objects.

## Import order

The generated guide instructs the editor to create a project with the declared
canvas/fps, then import in this order:

1. clean A-roll at timeline zero;
2. dialogue/BGM/SFX stems at zero, muting any unneeded reference audio;
3. full-duration motion overlay at zero or event-local overlays at recorded
   offsets;
4. SRT through Desktop caption import;
5. IP assets and modular outro tracks;
6. automatic master on a disabled/locked reference track for A/B comparison.

## Returned edit

The editor exports a new file outside the automatic-master path. A correction
summary lists changed events/layers/captions/audio/outro. Director records exact
bytes and runs all existing delivery gates again.
