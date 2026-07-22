# Autonomous Pre-Publish Delivery and Cover

## Completion target

In autonomous mode, produce one complete pre-publish package before asking for aesthetic feedback:

- verified final video with original speech, sentence captions, appropriate motion, SFX, and optional ducked BGM;
- platform cover;
- editable project and source plans;
- QA and source-coverage report;
- concise title, description, and platform-copy suggestions;
- asset and model provenance.

Do not pause for routine choices such as card side, animation family, SFX family, visual density within profile limits, or which approved photo best fits a cover. Make the choice, validate it, and continue.

## Hard gates

Ask only when continuation requires one of these:

- no authorized identity/photo reference exists;
- a semantic deletion exceeds the configured preservation boundary;
- private or sensitive material may be exposed;
- a paid service, upload, publication, or external side effect lacks authorization;
- two interpretations would create materially different messages or legal/reputation risk;
- automated validation still fails after the repair budget.

## Repair budget

Run up to two targeted automatic repair passes for failed checks. Repair only the failing dimension: text, identity drift, occlusion, timing, audio level, decode, or missing asset. Do not redesign successful parts. If a noncritical cosmetic warning remains, deliver the candidate and disclose it.

## Render strategy for long videos

Do not send a multi-minute source video through expensive HTML screenshot capture merely because the preview is authored in HyperFrames.

- Use HyperFrames for the editable full preview and for graphics timing.
- For videos longer than three minutes with sparse overlays, render a transparent graphics layer without the base video, then composite it with the clean base using FFmpeg.
- Prefer FFmpeg-native still-image fades, captions, audio mixing, and simple overlays when they are visually equivalent.
- Reserve full-frame HyperFrames rendering for dense motion or effects that cannot be reproduced reliably by composition.
- Render affected intervals first, then run the final pipeline without waiting for another aesthetic approval in autonomous mode.
- If a render is expected to be slow, keep a progress/status artifact and make the output resumable; do not appear stalled or restart completed work.

## Cover policy

Generate a cover by default after the edit's core story is known.

Default cover direction for a personal creator:

- use one authorized frontal real-person photo plus up to two complementary angle/body references;
- regenerate the person inside a new topic-specific scene rather than pasting a cutout onto a generic background;
- preserve recognizable face shape, age, skin tone, hairline, eyes, nose, mouth, and natural proportions across the references;
- use a cinematic movie-poster composition, dramatic but credible lighting, strong depth, and one clear focal point;
- connect the environment and props to the actual video topic;
- use a short hook, normally 4–10 Chinese characters plus an optional small product label;
- keep the face and hook readable at thumbnail size;
- avoid clickbait expressions, fake product claims, unrelated sci-fi decoration, excessive UI fragments, and visual styles that conflict with the creator profile.

Generate the poster artwork without text first. Add exact Chinese copy locally after the likeness, topic scene, and composition pass. Direct photographed-pixel compositing is a disclosed fallback for an explicit no-regeneration requirement or unavailable generation, not the default movie-poster method.

The video's hand-drawn IP style is optional for covers. Use it only when the topic or series identity benefits; do not force it when a real-person cinematic poster will perform better.

## Cover variants

Deliver one promoted cover. When enhanced editorial production is enabled,
generate two internally reviewed candidates with different communication
strategies and template families, then promote only the editorial recommendation.
Do not deliver both as platform duplicates or claim an expected performance
winner without publishing data. For Douyin and WeChat Channels, prefer a native
9:16 cover regardless of whether the video is 16:9 or 9:16. Keep the face and
title inside a center-safe region that survives list/grid crops.

Store per-video covers under the video's `covers/` directory. Promote a reusable series cover to shared assets only after approval.
