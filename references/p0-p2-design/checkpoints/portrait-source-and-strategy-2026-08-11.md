# Portrait canary source and strategy gate — 2026-08-11

## Goal binding

- Canonical implementation objective SHA-256: `a5fd4c50c668080663e7d8c0ba868e1033a3856906438266df622c0bd5531d82`.
- Approved design candidate: all 16 recorded document/schema hashes revalidated and matched.

## Authorized source

- Source: `E:\视频号\视频\告别2025.mp4`.
- User declaration: self-recorded personal video.
- Identity mode: `self`.
- Source SHA-256: `1d300965efc271692a7ccc959a5b7a5535866c0106beb424677d6facac7e6504`.
- Probe: 544×960 portrait, 25 fps, H.264 video, mono 48 kHz AAC, 145.036 seconds.
- Representative frames confirm a continuous centered talking-head composition.

## Offline transcript and proposed sample

- STT: local cached `faster-whisper-small`, CPU/int8, Chinese, no upload.
- Proposed source interval: `66.15s–140.48s`, approximately `74.33s`.
- Boundary rationale: begins before the complete physical-setback sentence and
  ends after the complete `加油，保重` close; no internal semantic deletion.
- Editorial arc: impermanence and setbacks → life-half transition → choosing to
  recover happiness → hopeful close.

## Proposed canary strategy awaiting confirmation

- Preserve every spoken sentence inside the selected interval.
- Build a captioned baseline and a separate captioned HyperFrames candidate.
- Protect the centered face and lower caption lane; use portrait side-safe motion.
- Use only content-bearing beats: impermanence, first/second-half transition,
  and recovering happiness. Quiet intervals are intentional.
- Use restrained reflective motion and adaptive SFX; no unlicensed BGM, cover,
  long intro/outro, or full-video delivery in this canary.
- Stop before cutting or rendering until the user confirms this strategy, per
  video-use's strategy-confirmation hard rule.

## Next exact action

After confirmation, create the isolated portrait canary project and 74.33-second
source excerpt, then run Director through paired 60–90 second sample QA and the
required automated, multimodal, and named-user gates. P1 remains blocked until
the formal portrait receipt passes.
