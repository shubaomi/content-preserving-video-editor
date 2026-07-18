# Visual and IP Workflow

Select graphics from content needs rather than a fixed theme.

| Content need | Preferred treatment |
| --- | --- |
| UI operation | cursor focus, outline, zoom, arrow, before/after |
| Process | flow diagram, stages, path animation |
| Strong claim | restrained kinetic type or pull quote |
| Comparison | split frame or paired cards |
| Abstract concept | IP illustration or knowledge card |
| Dense explanation | quiet captions plus one summary graphic |
| Personal introduction | lower third or reusable intro |
| Closing | summary, reusable outro, next action |

Assign each overlay a `purpose`, `start`, `end`, `safe_zone`, and `style_family`.

Assign optional sound cues by meaning:

| Motion or event | Preferred restrained SFX |
| --- | --- |
| lateral card entrance | short whoosh |
| chip, badge, or small reveal | pop |
| UI action | soft click |
| success or closing confirmation | chime |
| real error or digital disruption | subtle glitch |

Keep most caption changes silent. Avoid repeating the same loud effect on every card.

Separate editable and animated geometry:

```text
timed clip host -> motion wrapper (GSAP) -> editable surface (Studio geometry)
```

Never let GSAP and Studio write the same transform target.

For personal IP work:

1. Confirm the main anchor, spec board, and action sheet belong to the intended person.
2. Load `/ip-diagram-creator`.
3. Create a content confirmation card and shot list.
4. Generate each image separately.
5. Check character anchors, text, readability, and role participation.
6. Animate the approved image as meaningful content, not decoration.

Make two independent IP decisions:

- **Mid-video:** generate or reuse an IP visual only when it explains an
  abstract concept, humanizes a dense chapter, or creates an evidenced visual
  reset. A long video does not create an image quota.
- **Outro:** default to a stable branded outro system (identity, composition,
  signature, CTA/safe zone) with a topic-specific pose, prop, or background
  variant. Do not force every video to reuse one identical finished picture,
  and do not generate an unrelated full-screen illustration merely to show the
  character.

The absence of an already-finished topic image is not by itself a reason to
mark IP as not applicable when confirmed identity references and an authorized
generator exist. The audit must separately state whether the narrative needs a
mid-video asset and whether the outro would benefit from a topic variant.

Never place user-specific images in the public Skill. Read them dynamically from the profile.
