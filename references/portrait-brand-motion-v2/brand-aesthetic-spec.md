# Brand Aesthetic Specification

Status: proposed for user approval; no rendered style has been approved.

## 1. Brand promise

HongRun portrait videos should feel like a thoughtful independent creator using
technology with clarity, curiosity, warmth, and forward motion. The visual
language should be more expressive than a plain talking head, but it must never
make the creator look secondary to a template.

Recommended direction name: **Luminous Intelligence / 流光知性**.

This direction combines a light-future cinematic base with short high-energy
knowledge-creator accents. It is not cyberpunk, gaming UI, corporate dashboard,
or sticker collage.

## 2. Aesthetic pillars

1. **Person first** — eyes, expression, gesture, and voice are the visual anchor.
2. **Meaning becomes motion** — hierarchy and movement reveal the thought, not
   just repeat the subtitle.
3. **Luminous depth** — light, blur, focus, scale, parallax, and negative space
   create richness before containers are introduced.
4. **Calm base, decisive burst** — most frames remain readable and human; key
   ideas receive short, confident energy changes.
5. **One recognizable signature** — a point grows into an orbit/trace and lands
   as focus. The same temporal shape informs type, light, and sound.
6. **Original rather than imitative** — use common motion-design principles but
   no copied proprietary preset, branded template, or unlicensed sound.

## 3. Signature primitives

### Geometry

- `pulse_dot`: a small luminous point representing an idea appearing.
- `orbit_trace`: an asymmetric curved path suggesting exploration and relation.
- `focus_beam`: a short line/gradient that resolves attention onto a phrase or
  subject region.
- `split_plane`: two spatial fields for a genuine contrast, preferably without
  boxed containers.

The primitives may combine, but no event should display all of them merely to
look branded.

### Typography

- Primary: modern Chinese sans with strong variable-weight range; use the
  configured local font with a system sans fallback.
- Default emphasis unit: one meaningful phrase, normally 2–10 Chinese
  characters; never a low-information verb alone.
- Preferred techniques: weight interpolation, masked reveal, baseline travel,
  outline-to-fill, local tracking change, and foreground/background depth.
- Body-caption styling remains owned by the caption system and is not replaced
  with decorative typography. The caption system may use phrase-level semantic
  emphasis: normally zero or one, never more than two, source-matching key terms
  may receive a brand accent, weight, and a restrained 105–120% pop. The rest of
  the sentence stays stable and readable; not every word should perform.

### Shape and surface

- Prefer open shapes, strokes, gradients, masks, and soft depth.
- A container is permitted only when it encodes a semantic object such as a
  quote, evidence item, or real comparison. It must not be the default keyword
  treatment.
- Avoid uniform 18px rounded rectangles, glass dashboards, badges, and detached
  top-of-frame panels as the portrait default.

### Light and texture

- Soft directional bloom, controlled glow, shallow depth haze, and restrained
  film grain may support emotion.
- No global flashing, heavy chromatic aberration, constant neon outline, or
  large high-frequency particles.
- Any texture must preserve facial skin tone and caption readability.

## 4. Adaptive color system

The brand profile contains two palettes selected from measured source
luminance, contrast, and local color—not from the file name.

### Luminous light

| Token | Proposed value | Use |
|---|---|---|
| canvas tint | `#F7F7F2` | optional light-field base |
| ink | `#102A2A` | primary type and strokes |
| mint | `#2DD4BF` | identity accent |
| cyan | `#22D3EE` | motion/light accent |
| amber | `#F59E0B` | emotional/high-value accent only |
| soft violet | `#8B5CF6` | rare contrast accent |

### Luminous dark

| Token | Proposed value | Use |
|---|---|---|
| deep ink | `#071A1A` | translucent depth field |
| light ink | `#F8FAFC` | primary type |
| mint | `#34D399` | identity accent |
| cyan | `#22D3EE` | motion/light accent |
| warm light | `#F6C177` | emotional resolution |

Values are design candidates, not a production guarantee. The implementation
must measure composite contrast over the actual source and may select a safer
token from the same palette. It may not silently invent a new brand palette.

## 5. Motion character

- Overall character: intelligent, energetic, light, precise, and human.
- Entry: acceleration from a small idea or off-axis path; avoid identical fade
  and 8px translation across all recipes.
- Explain: one visible semantic transformation, such as orbit connecting two
  meanings, weight shifting to a key phrase, or depth separating a contrast.
- Hold: short enough to avoid a sticker-like panel; long enough to read.
- Exit: resolves into source space, light, or the next phrase; no unexplained
  leftover line or particle.
- Default easing vocabulary: asymmetric ease-out, restrained spring, path
  interpolation, and masked acceleration. Linear motion is reserved for scans or
  progress relations.

## 6. Energy language

Energy is a continuous chapter curve plus discrete semantic beats. It is never a
fixed cadence.

- `quiet`: source person and captions carry the moment.
- `micro`: 0.35–1.5s local emphasis, gesture echo, or light/type accent.
- `meso`: 1.5–5s thought structure, contrast, depth phrase, or brief cutaway.
- `macro`: 1.0–7s hook/chapter/resolution transformation; requires structural
  evidence and cannot be selected from elapsed time alone.

These ranges are validation bounds, not quotas. A long quiet passage may be
correct; every meaningful opportunity still needs a recorded decision.

## 7. Source adaptation

- Low-light close-up: use edge-safe luminous type, local glow, and gentle camera
  treatment; do not cover the forehead with opaque cards.
- Bright indoor talking head: use dark ink, colored orbit strokes, restrained
  shadow, and negative-space placement.
- Full-body or gesture-rich frame: prioritize gesture echoes and side-depth
  placement, with hand tracks when available. When the sentence explicitly
  teaches a physical product, the product becomes the primary hard-protected
  subject. A short product callout may partially cross one hand or face region
  if it remains near the product, stays within the measured cap, and restores a
  clean person-first frame on exit. The current semantic brief must explicitly
  approve product priority, the Storyboard window sets the time cap, and actual
  post-exit geometry proves restoration. Left and right hands remain distinct
  regions. Captions are never part of this exception.
- Centered close face: reduce overlay area and favor camera/light/type effects
  that do not compete with the eyes and mouth.
- Existing strong background design: reduce decorative layers and use source-
  integrated type or quiet decisions.

## 8. Forbidden defaults

- product dashboard cards, UI focus boxes, and process rails for personal speech;
- a rounded rectangle above the head containing the spoken keyword;
- full-sentence subtitle duplication as kinetic text;
- random template rotation, fixed cadence, or event-family quotas;
- constant punch zoom, shake, glitch, flash, or chromatic split;
- persistent overlay longer than its semantic transformation;
- untracked face/hand overlap, invented subject mattes, or unsafe crop;
- unrelated full-frame IP art or white-background cutaways;
- a different visual identity in every video;
- copied Jianying/CapCut assets, effect names, sounds, or proprietary project data.

## 9. Approval questions

Brand taste passes only if HongRun answers `yes` to all applicable questions for
the exact selected Style Reel:

1. Does this feel like a personal creator rather than a product demo?
2. Is the person still the primary subject?
3. Is it more expressive and visually distinctive without feeling noisy or
   cheap?
4. Does motion help the thought or emotion instead of restating captions?
5. Does the sonic language feel coherent and audible without competing with the
   voice?
6. Would you reuse this direction across future personal talking-head videos?

No automated score may substitute for these answers.
