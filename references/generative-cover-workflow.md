# Reference-Guided Generative Cover Workflow

Use this workflow for the default real-person cinematic cover. Authorized photos define identity; they are not edit targets and are not pasted into the result.

## Editorial direction contract

When `cover.editorial.enabled=true`, require `semantic-brief.json` to contain:

- `cover_direction.headline`: a short claim or viewer benefit supported by the video;
- `highlight_terms`: one to three exact substrings of the headline;
- `eyebrow` and optional `subtitle`;
- `tone`, `visual_concept`, `subject_side`, and `visual_route`;
- `evidence_event_ids` that resolve to existing semantic events with transcript
  quotes or viewer takeaways.

Run `scripts/cover_editorial.py` to produce `cover-editorial-plan.json`. The
planner validates evidence, authorized identity/expression files, authentic
frames, personal-IP/supporting assets, rights basis, headline length, route,
subject placement, and two structurally distinct template families. Do not let
keyword frequency author the headline or visual concept.

## Route selection

| Route | Use when | Identity behavior |
| --- | --- | --- |
| `reference_regenerated` | A topic-specific cinematic or tutorial scene is needed | Regenerate from at least two identity references plus an expression reference; user likeness approval remains blocking |
| `authentic_frame_editorial` | The source contains a strong, intentional expression/gesture frame | Preserve the authentic frame and add deterministic editorial layers; record frame hash and provenance |
| `real_person_ip_hybrid` | A personal-IP component materially explains the topic | Regenerate the real creator from references and integrate only project-owned, purpose-declared IP/supporting assets |

`auto` may choose an authentic frame only when `prefer_authentic_frame=true` and
an existing frame is declared. It may choose the hybrid route only when an
available `personal_ip` asset has a stated purpose and rights basis. Otherwise
use reference-guided regeneration.

## Inputs

- one clear frontal face reference;
- one three-quarter or side reference;
- one body/proportion or natural-action reference;
- at least one expression reference that demonstrates the desired warmth,
  smile, eye contact, or energy; it may also be one of the identity references;
- actual video title, transcript summary, demonstrated product/topic facts, and extracted design tokens;
- an optional previously approved cover used only as a style/composition reference.

Never use another person's image as an identity reference. Keep every reference path in the per-video manifest.

## Clean-base generation contract

Generate a native 9:16 photorealistic movie-poster base with:

- the same recognizable creator, regenerated in a new pose and setting;
- an expression appropriate to the topic; for normal creator/tutorial covers,
  default to a natural slight smile, direct or near-direct eye contact, open
  posture, and active engagement rather than a blank or off-axis stare;
- a single coherent topic-specific action and environment;
- credible photographic skin, hands, clothing, materials, depth, and lighting;
- deliberate negative space for a short title;
- no text, logos, watermarks, fake metrics, or unsupported product claims;
- no pasted-cutout edge, generic gradient portrait, beauty-filter face, unrelated cyberpunk decoration, or collage of floating UI fragments.

Write one hash-bound generation-request JSON per variant. A configured generator
command may consume `{plan}`, `{prompt}`, `{output}`, and `{semantic_brief}`
placeholders. A missing command, paid-call authorization, clean base, or review
must produce `action_required`; never fabricate a generated file.

For software/tutorial topics, show the human doing a believable task and use restrained interface metaphors as part of the environment. For conversational topics, prioritize emotional posture, eye line, and cinematic atmosphere over decorative UI.

## Identity and scene gate

Review in this order:

1. face shape, eyes, nose, mouth, jaw, skin tone, age, hairline;
2. expression likeness, eye contact, warmth, and energy against the authorized
   expression reference;
3. body proportions, hands, and natural pose;
4. topic action, props, and environment;
5. light direction, depth, color, and negative space;
6. only then typography and thumbnail crop.

An attractive image that looks like a different person fails. A recognizable
person with an unintentionally lifeless expression also fails. A recognizable
person pasted onto an irrelevant background also fails.

## Typography and provenance

Generate the clean base without words. Use `scripts/compose_generated_cover.py` for exact local typography and center-safe preview. The manifest must record identity and expression reference paths, target expression, clean base, generator/prompt or prompt file, topic evidence, composition method, separate agent identity/expression reviews, user identity review, and final output.

Keep the generated clean base and final typed cover as separate files. Do not overwrite a previously approved cover.

Select from the controlled template families:

- `cinematic_editorial`: restrained film-poster hierarchy;
- `bright_tech_tutorial`: light expert/tutorial composition;
- `dark_high_energy`: high-contrast tool review or strong-result composition;
- `thought_leadership_ip`: editorial brush treatment with an optional owned IP component.

Templates must differ in hierarchy and composition, not only color. Render exact
Chinese text locally, auto-fit without changing wording, highlight only declared
terms, keep all text inside the center-safe region, and place the title opposite
the declared subject box. Supporting assets remain separate hashed inputs.

Run `scripts/cover_quality.py` for each candidate. It writes a native 9:16
thumbnail and verifies the plan and manifest hashes, exact typography, line
limit, minimum thumbnail type size, topic evidence, safe boxes, title/subject
avoidance, and supporting-asset provenance. These automated checks do not
approve personal likeness.

## Optional A/B editorial comparison

When quota and time permit, generate two independent clean bases that communicate the same verified topic with meaningfully different editorial strategies. Do not create a cosmetic variant by changing only color, title placement, or crop.

Compose each base separately with `scripts/compose_generated_cover.py`, run the
per-candidate QA, then run `scripts/compare_generated_covers.py`. The comparison
must pass identity provenance, topic evidence, exact local typography, native
9:16 size, rights basis, distinct communication strategies, automated QA, and
minimum visual-difference checks. The report may recommend one option for
editorial clarity, but it must not claim better platform performance without
real publishing data.

After review, use `scripts/promote_generated_cover.py` to copy only the passed editorial recommendation to the stable project cover path. Keep both candidates, their manifests, the comparison sheet, and the machine-readable report as evidence. Human likeness approval remains a release gate and must not be inferred from automated checks.

## Fallback

Use `scripts/build_cinematic_cover.py` only for an explicit unchanged-photo-pixel request, unavailable generation, or a disclosed emergency fallback. Label the manifest `literal_photo_composite_fallback`; never describe it as the default generative movie-poster result.
