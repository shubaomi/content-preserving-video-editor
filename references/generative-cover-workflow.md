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

For a creator-led experiment or learning diary, identify the creator's intended action and one evidenced result before choosing a prop. When a themed generation is requested, compose the creator doing that action and reacting to the result; neither a prop-only advertisement, a video still nor a fixed corner portrait substitutes for it. Series recognition can come from the byline, headline hierarchy and palette without repeating the pose. Treat example creators as composition inspiration only, never as identity inputs.

Resolve identity from the current owner's private profile, not from the shared Skill or another project's default. Before sending references, match the person, exact approved images, provider, purpose and reuse scope to current unrevoked consent. A reusable grant covers matching future covers only; missing, revoked or out-of-scope consent blocks transmission. Keep images, identifying paths and personal grants out of shared source control. Permission to generate is not approval of likeness, publication, training or a different provider.

At master review, compare the generated frontal/three-quarter geometry with the original photos, not a prior generated face: width-to-length, cheek volume, jaw taper and chin height. Correct reference drift rather than prescribing a thinner or rounder face. Check eyes, lips, gaze and hand contact for a believable response to the action. Use saturated color on scene and props without tinting skin. Check the exact approved headline including meaning-changing qualifiers, and inspect the title, face and action at thumbnail size. Present the master for the owner's likeness/expression decision before promoting it or producing the requested platform variants; do not treat technical QA as approval.

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

Before requesting artwork, write one source-grounded visual sentence: who does what, to which control or object, to reach which observable result? Lock the control's interaction (press, turn, drag, etc.) and every meaning-bearing target, unit and precision. An attractive substitute that implies a different mechanism fails. Put the visible action and its result on a readable sightline; distinguish a conceptual scene from real product evidence.

Use the creator's chosen, authorized reference period for facial geometry. Hair, styling and expression may change with the episode when permitted; do not conflate these with identity or apply a universal beauty filter. Match expressive intensity to a specific reaction. Name where the eyes should land. If a rich scene is requested, give foreground, subject and background distinct jobs with motivated light and contrasting accents; neither a flat color field nor unrelated clutter satisfies that brief.

Acceptance: inspect the **typeset** master at phone thumbnail size, first with the headline hidden. Can a reviewer point to the hand, the correct control, the gaze target and the intended readout when the story depends on them? Then check the exact copy, readable digits/unit, and that no glyph covers eyes, action or result. Repair failed invariants before asking for subjective likeness and taste approval. Do not hardcode a particular creator, prop, value, hairstyle or palette as the default.

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
