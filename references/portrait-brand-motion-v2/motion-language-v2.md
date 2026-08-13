# Portrait Motion Language v2

Status: proposed additive grammar; implementation not authorized.

## 1. Purpose

`hongrun-portrait-expressive-v2` is a profile-bound expression layer above MQE
v1. It consumes the existing approved semantic opportunities, video-use word
timeline, subject/face/hand evidence, design tokens, caption region, and source
state. It emits typed portrait recipe choices and an energy map. It never edits
the transcript, EDL, or source media, and it never authors new meaning.

## 2. Grammar hierarchy

Every selected event has exactly one semantic role, one energy tier, one primary
recipe, zero or more compatible supporting layers, one audio decision, and a
declared fallback. Supporting layers are not extra semantic events.

### Micro layer

- phrase-weight or outline-to-fill emphasis;
- orbit/trace accents around approved copy;
- gesture echoes tied to verified hand motion;
- local light sweep or small icon burst with provenance.

### Meso layer

- spatial thought split;
- foreground/background phrase depth;
- brief evidence or semantic cutaway;
- camera push with type landing;
- structured three-step or relation explanation only when supported.

### Macro layer

- hook freeze/accelerate/release;
- masked chapter bridge;
- emotional palette/depth transition;
- resolution sequence that returns cleanly to the person.

## 3. Energy map

The planned `portrait-energy-map.json` records:

- chapter ID and source/output windows;
- entry and exit energy in `[0,1]`;
- semantic pressure, emotional turn, speech rate, pause, and gesture evidence;
- chosen tier: `quiet|micro|meso|macro`;
- transition intent: `rise|settle|contrast|resolve|sustain`;
- maximum simultaneous attention layers;
- rationale and evidence references;
- deterministic fallback tier.

Selection rules:

1. A content opportunity must exist before an energy tier is assigned.
2. A high speech rate reduces visual copy and concurrent layers; it does not
   automatically increase effects.
3. A verified gesture may authorize a gesture echo, never a guessed hand path.
4. A structural chapter boundary may authorize `macro`; elapsed time cannot.
5. The compiler reports density and long quiet intervals but never repairs them
   by injecting filler.
6. Adjacent events share one chapter energy curve and may form a controlled
   phrase sequence; independent random entrances are prohibited.

## 4. Initial portrait recipe catalogue

The eight recipes below are new profile-capable recipe contracts. Proposed IDs
avoid modifying existing MQE-01–MQE-16 semantics.

### PBM-01 — Luminous phrase pulse

- Role: `mark|resolve`; tier: `micro|meso`.
- Structure: approved phrase without a containing card; `pulse_dot` expands into
  `orbit_trace`, the phrase moves from outline to filled variable weight, then
  the orbit resolves into a small focus beam.
- Use: concise idea/emotional landing.
- Preconditions: approved phrase, word boundary, face/caption-safe placement.
- Contraindications: low-information verb, full sentence, dense overlapping
  gesture region.
- Primary runtime: DOM/SVG/GSAP.
- Fallback: MQE-12 with portrait token set, then `caption_only`.

### PBM-02 — Speaker-depth phrase

- Role: `explain|resolve`; tier: `meso`.
- Structure: phrase enters on a plane behind or beside the speaker, crosses a
  shallow depth relation, and returns without masking the face.
- Use: reflective or identity-defining statements.
- Preconditions: verified subject region; an actual matte is required only when
  text passes behind the subject.
- Contraindications: unverified matte, large head motion, insufficient negative
  space.
- Runtime: DOM/SVG/GSAP; optional evidence-bound subject mask.
- Fallback: face-safe side-depth phrase with no occlusion illusion.

### PBM-03 — Gesture echo

- Role: `mark|sequence`; tier: `micro`.
- Structure: a traced arc, dot burst, or directional beam follows one verified
  expressive hand movement and lands on approved copy/icon.
- Use: pointing, counting, opening, or directional gesture.
- Preconditions: hand track, gesture confidence, active window, clean caption
  separation.
- Contraindications: hand not visible, ambiguous limb topology, rapidly changing
  crop.
- Runtime: SVG path/GSAP.
- Fallback: PBM-01; never invent a hand path.

### PBM-04 — Thought contrast planes

- Role: `relate`; tier: `meso`.
- Structure: two approved concepts occupy different open planes around the
  person; a moving focus point exposes the relationship. No default pair of
  opaque cards.
- Use: real contrasts, before/after meanings, two-part questions.
- Preconditions: two semantic nodes and relation intent.
- Contraindications: unrelated labels, more than two primary concepts, crowded
  face/hand zones.
- Runtime: DOM/SVG/GSAP.
- Fallback: MQE-04 only when a container semantically represents two objects;
  otherwise PBM-01 sequence.

### PBM-05 — Cinematic camera phrase

- Role: `explain|transition`; tier: `meso|macro`.
- Structure: restrained push/pan/reframe synchronized with masked typography or
  a focus beam; source motion and phrase settle together.
- Use: perspective shift, emotional rise, chapter entry.
- Preconditions: subject track, crop-safe target, sufficient source resolution,
  seek-safe transform.
- Contraindications: face crop risk, unstable handheld motion, multiple rapid
  uses within one chapter.
- Runtime: HyperFrames media transform + DOM/SVG/GSAP.
- Fallback: PBM-01 or quiet source.

### PBM-06 — Semantic cutaway window

- Role: `explain|prove|relate`; tier: `meso`.
- Structure: source remains visible while a short integrated asset enters through
  a mask/depth window, adds evidence or a necessary metaphor, then exits fully.
- Use: facts, external evidence, genuinely clarifying illustration/IP component.
- Preconditions: asset request bound to semantic event, provenance/rights, topic
  fit, crop/padding/anatomy checks.
- Contraindications: subtitle repetition, full-frame replacement without need,
  white-background mismatch, unrelated generic IP.
- Runtime: HyperFrames DOM/SVG/media; optional selected Remotion component only
  under existing strict parity/license contracts.
- Fallback: PBM-01 or caption/source.

### PBM-07 — Luminous chapter bridge

- Role: `transition`; tier: `macro`.
- Structure: orbit trace becomes an edge-to-edge mask/light field, shifts color
  temperature and depth, then reveals the next chapter with no retained panel.
- Use: verified chapter or emotional boundary.
- Preconditions: chapter-boundary evidence and clean source window.
- Contraindications: ordinary sentence boundary, dense speech without settle
  time, repeated use within a short chapter.
- Runtime: SVG mask/GSAP; optional licensed texture.
- Fallback: MQE-11 portrait variant, then quiet cut.

### PBM-08 — Emotional resolution bloom

- Role: `resolve`; tier: `meso|macro`.
- Structure: local warm light, upward phrase movement, subtle camera release, and
  a sonic resolving motif converge, then clear to an unobstructed person.
- Use: hopeful conclusion, invitation, or emotional release.
- Preconditions: evidence-backed emotional turn, readable phrase, dialogue-safe
  audio corridor.
- Contraindications: unsupported sentiment, neutral technical explanation,
  unsafe true peak.
- Runtime: DOM/SVG/GSAP + FFmpeg audio mix.
- Fallback: PBM-01 with warm accent, then source-only ending.

## 5. Supporting layers

Supporting layers are declared inside a primary recipe and cannot introduce new
copy or claims:

- `ambient_light_field`: slow source-adaptive gradient/bloom.
- `micro_grain`: subtle texture with skin/caption exclusion.
- `orbit_particles`: bounded particles following an existing path.
- `focus_vignette`: local, measured luminance guidance without hiding context.
- `icon_burst`: licensed/provenance-bound icon fragments, maximum one semantic
  icon family per event.

At most one attention-heavy supporting layer and one low-energy ambient layer
may coexist with the primary recipe. Captions do not count as optional layers.

## 6. Source and region contracts

- Face and mouth are hard protected regions for text, icons, and high-contrast
  paths.
- Eyes receive an additional no-flash/no-particle exclusion zone.
- Hands are dynamic protected regions unless PBM-03 owns a verified gesture
  binding.
- Captions and platform UI avoidance remain hard constraints.
- Camera/crop effects bind the subject track and safe crop at entrance, mid,
  pre-exit, and post-exit.
- Subject masks bind exact source, model/provider/version, frame range, artifact
  hash, and quality evidence. Missing evidence selects fallback.

## 7. Choreography grammar

Recipes must not reuse one global entrance/explain/hold/exit token set. Each
phase carries visible, measurable poses:

- `entrance`: source-relative start state and first semantic cue.
- `explain`: actual transformation that expresses the relation or emphasis.
- `hold`: readable resolved hierarchy; may contain subtle ambient motion.
- `exit`: removes every nonpersistent element and restores source hierarchy.

Micro events should normally finish their semantic transformation within 1.5s.
Meso and macro events may last longer, but a long spoken window cannot justify a
long static overlay. The event may contain multiple word-bound micro beats under
one semantic parent.

## 8. Determinism and diversity

- Recipe selection comes from approved semantic role/form, portrait eligibility,
  energy map, source evidence, and brand profile—not keywords or randomness.
- Structural variety is measured from normalized DOM tree, layout geometry,
  motion sidecar, camera intent, and layer inventory.
- Reusing the same recipe is allowed when the meaning calls for it; repeated
  choreography within a cooldown requires a rationale or parameterized variation
  inside the recipe contract.
- A different color or entrance direction does not count as structural variety.

## 9. Advanced runtime boundary

Standard production path: DOM, SVG, CSS, GSAP, and HyperFrames media transforms.

Optional, default-off paths:

- subject segmentation/matting;
- Lottie assets;
- selected Remotion event components;
- Three/WebGL/shader depth or particles.

Each optional runtime keeps the existing strict source/subject/license/cost/
seek/parity evidence and deterministic 2D fallback. None is required to achieve
the base brand language.
