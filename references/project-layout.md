# Project Layout

Use one shared profile root and one isolated directory per video.

```text
profile-root/
├── profile.yaml
├── shared/
│   ├── character/
│   ├── generated/
│   ├── brand/intro/
│   ├── brand/outro/
│   ├── brand/motion-presets/
│   ├── audio/
│   ├── fonts/
│   └── templates/hyperframes/
└── videos/
    ├── index.yaml
    └── video-id/
        ├── project.yaml
        ├── source/
        │   └── cover/original-cover.png
        ├── covers/
        ├── edit/transcripts/
        ├── edit/captions/
        ├── edit/assets/
        ├── edit/reports/
        ├── hyperframes/
        ├── scripts/
        ├── work/
        └── exports/
```

Store reusable identity assets only under `shared`. Store content generated for one video under that video until explicitly promoted. Keep every HyperFrames composition, cache, storyboard, and render within the owning project.

Store an existing/published cover under `source/cover/` because it is an input. Store newly generated or revised covers under the project-level `covers/` directory.

Do not put original media in the Skill source. Do not use one global `edit` directory for multiple videos.
