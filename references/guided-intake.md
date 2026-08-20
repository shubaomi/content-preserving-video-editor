# Guided Intake Protocol

This protocol is the default conversational entry to the Director. Its purpose
is to let a creator start with a short request such as “帮我剪这个视频”, without
memorizing project IDs, presets, Profile fields, or rendering commands.

## One-batch question rule

First reuse facts already present in the request, project, or current thread.
Ask one compact batch containing only unresolved items. Do not ask one question
per turn, and do not ask the user to repeat a path, authorization, identity, or
delivery choice that is already explicit.

Use this Chinese form as the canonical conversational shape:

> 请把还缺少的信息一次性告诉我：
>
> 1. 源视频绝对路径；
> 2. 视频身份与授权：本人录制 / 第三方视频 / 无需人物身份的通用视频；是否已获得剪辑授权，以及是否已获得发布授权；
> 3. 本次先做样片，还是继续一个已经通过样片审核的项目完成全片；
> 4. 如果是 HongRun 本人竖屏口播，是否启用 HongRun Profile 和 portrait-brand v2；
> 5. 是否还需要包含透明动效、独立音轨、IP 素材等内容的完整分层 NLE 交接包。
>
> `video_id`、视频类型、工作标题、发布标题、封面文案、简介、话题、比例、分辨率和帧率默认由系统根据源视频与内容自动生成。

Natural-language answers are accepted. The user does not need to reproduce the
numbering or use technical enum names.

## Defaults

- `video_id`, titles, cover copy, description, topics, platform target, canvas,
  frame rate, and content format: automatic.
- New or changed source: sample first.
- Universal MP4: enabled.
- Standard repair kit: always included with a completed full render (automatic
  master, no-new-caption candidate, SRT, ASS/style plan, HyperFrames inventory).
- Expanded layered Manual-NLE package: disabled unless requested.
- HongRun portrait-brand: explicit opt-in only; never inferred for third-party
  or generic footage.
- Editing authorization and publication authorization are separate. A locally
  reviewed sample may proceed with editing authorization, but publishable
  delivery and publishing copy remain blocked while publication rights are
  unknown or denied.
- Unknown optional preferences: keep the stable/default-off route rather than
  asking another round of low-value questions.

## Classification is the Director's job

The creator may provide a type hint, but it is not authority. Inspection derives
separate dimensions instead of forcing one label:

- input mode: preservation-first source or existing-edit polish;
- visual format: portrait talking head, product demonstration, screen tutorial,
  interview, screen-plus-camera, or a supported combination;
- identity: self, third party, or generic;
- orientation and platform-safe canvas;
- semantic behavior: explanation, demonstration, comparison, steps, claims,
  emotion, reuse-source, quiet-source, and caption-only opportunities.

For example, a vertical HongRun video that continuously shows the creator while
handling headphones is both `portrait_talking_head` and `product_demo`. The
combined evidence activates portrait grammar, product hard protection, and only
the approved bounded face-or-hand soft-overlap rule in product-first windows.

## Execution boundary

Intake completion authorizes project initialization, read-only inspection,
transcription/EDL requests, semantic planning, and the requested sample path. It
does not approve a new full render, likeness, aesthetic taste, publication, paid
providers, or third-party rights. Direct full rendering is accepted only as a
resume operation when the exact current sample approval and final-render
authorization already exist.

After intake, present one short summary and continue without further setup
questions. Stop only at a real owner handoff or user gate, and consolidate any
required user decisions into one minimal decision packet.
