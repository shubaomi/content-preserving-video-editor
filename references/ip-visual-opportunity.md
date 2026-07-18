# Topic-Specific IP Visual Opportunity

Run this audit for every semantic chapter before generating assets. Time alone never forces an illustration, but a long video cannot silently skip the audit.

## Decision score

- +2 abstract idea, mental model, or invisible mechanism.
- +2 method, process, or feedback loop with at least three meaningful steps.
- +2 major chapter transition or conclusion.
- +1 visually repetitive screen for roughly 20 seconds or more.
- +1 the IP character can perform a meaningful action rather than merely pose.
- -2 the real UI or physical action must remain visible for comprehension.
- -2 the insert would cover a face, pointer action, privacy-sensitive region, or key control.
- -1 it repeats an existing visual without adding explanation.

Score 3 or more: recommend a topic-specific IP visual. Score 1–2: optional. Score 0 or less: prefer UI annotation, captions, or no overlay. Record the decision and reason even when no asset is generated.

## Content routing

- UI instruction: keep the real screen and use restrained annotation.
- Abstract concept, workflow, comparison, debugging loop, risk, or takeaway: consider an IP knowledge illustration.
- Talking head: avoid covering the speaker; use a short cutaway only when it clarifies meaning.
- Repetitive UI with a conceptual narration shift: a brief topic-specific IP cutaway can reset attention.

For videos longer than three minutes, audit every semantic chapter. Two to four topic anchors are a useful review range, not a quota. If none score high enough, document why.

## Generation contract

The character main anchor, action sheet, avatar, and specification board are identity references only. Do not place them directly into the final video as if they were theme illustrations.

Before generation:

1. Write the chapter message and desired viewer takeaway.
2. Create a shot list and content confirmation card.
3. Give the character a content-bearing action and use 2–6 execution agents when a process genuinely benefits from them.
4. Generate each final image separately from the current topic.
5. Store it under the current video's `edit/assets/ip-generated/` directory.
6. Record model, prompt, reference assets, approval status, and usage interval.

Reusable branded intro or outro art may be promoted to shared assets only after approval. Topic-specific inserts stay with the video project.

## Audit format

Each JSON entry records `section_id`, `start`, `end`, `chapter`, `content_type`, `current_visual`, `score`, `decision`, `reason`, `ip_role`, and `asset_type`. A `generate` decision also requires `confirmation_card`.
