# Integrated Visual System

## One beat, one primary explanation

For every topic visual, inspect all overlays and sounds within the same semantic beat. Assign exactly one primary explanatory layer. Other layers may identify, guide attention, or provide continuity, but must not repeat the same message.

- If an IP diagram already explains the workflow, remove the workflow callout or change it to a short chapter label.
- If the real UI is sufficient, use pointer focus or annotation instead of a duplicate IP picture.
- If a caption says the full idea, keep the visual mostly pictorial; do not repeat the entire caption as image text.
- If two assets have the same viewer takeaway, keep the clearer one.

Record `semantic_owner`, `relationship_to_existing_motion`, and `redundancy_action` in the visual audit. Allowed redundancy actions are `replace`, `complement`, `demote`, and `none`.

## Integration modes

Choose the least disruptive mode that communicates the idea:

1. `pip-card`: a 28–42% canvas-width card anchored to a safe side or corner while the source remains visible.
2. `masked-reveal`: reveal a diagram through a rounded mask, wipe, crop, or tracked region.
3. `split-panel`: temporarily allocate part of the canvas to the topic visual and reflow the source without covering critical content.
4. `character-cutout`: use a transparent IP character or a few diagram components over the source.
5. `chapter-bridge`: a deliberate full-canvas transition, normally 2–4 seconds, only at a real chapter boundary.

Do not use a long full-canvas replacement inside a continuous UI demonstration. Use easing and a visual bridge back to the footage.

## Match the established visual system

Before generation, sample representative source frames and the existing motion system. Store a small design-token record:

- background and surface colors;
- accent colors and color temperature;
- border radius, border weight, and shadow softness;
- typography family, weight, and caption treatment;
- line-art weight, illustration detail, and icon style;
- safe zones and typical overlay scale.

Generate or post-process the topic asset to those tokens. Prefer transparent assets, scene-colored backgrounds, or the same card surface used elsewhere. A white background is acceptable only when white is an intentional shared surface with matching radius, border, shadow, and padding. Never drop a raw white 16:9 image onto footage as an unexplained second canvas.

## Motion and sound choreography

The entrance, internal emphasis, exit, and SFX form one cue:

- lateral slide or split panel: short restrained whoosh;
- small card or character reveal: soft pop;
- UI attachment or selection: click;
- verified result: light chime;
- real failure only: subtle glitch.

Use one transient cue per visual beat. Do not fire both the old callout sound and a new topic-image sound for the same event. Most topic visuals should stay 3–6 seconds; longer use requires internal progression or a continued explanatory role. Animate the wrapper, keep the editable surface stable, and use subtle scale, mask, parallax, or line-draw motion instead of a static pasted image.

## Reference-guided cinematic covers

Identity and topic fidelity gate the cover before typography:

1. Select one clear frontal photo plus up to two supporting references for profile, body proportion, hairline, and natural expression.
2. Treat every photo as an identity reference, not an edit target. Regenerate a new pose, wardrobe, environment, props, lighting, and camera angle that communicate the current video's subject.
3. Require high likeness without beauty-filter drift: preserve face shape, age, skin tone, hair, eyes, nose, mouth, jaw, and normal proportions across the references.
4. Reject outputs that look like a pasted cutout, a passport photo on a gradient, a generic studio portrait, or an attractive stranger. Topic props must form one coherent scene rather than floating decorative fragments.
5. Generate a clean 9:16 base with no text and intentional title negative space. Add exact Chinese copy locally only after likeness, topic fit, hand anatomy, and composition pass.
6. Use original photographed pixels only when the user explicitly requests literal fidelity or as a disclosed fallback when reference-guided generation is unavailable.

Store all identity reference paths, the clean-base generator/prompt, topic evidence, typography method, and separate agent/user identity-review states in the cover manifest.
