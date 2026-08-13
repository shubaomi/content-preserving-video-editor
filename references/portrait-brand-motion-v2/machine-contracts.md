# Machine Contracts

Status: design schemas only. Schema validity does not authorize implementation
or prove rendered aesthetics.

## 1. Shared rules

All artifacts use Draft 2020-12 JSON Schema, reject unknown top-level fields,
carry an explicit schema version, and are validated together with cross-file
invariants that JSON Schema cannot express. Paths in production instances must
be absolute and accompanied by current SHA-256. IDs use `[A-Za-z0-9._:-]+`.

The design defines six additive contracts:

1. `portrait-brand-profile`
2. `portrait-energy-map`
3. `portrait-motion-contract`
4. `portrait-sonic-plan`
5. `style-reel-plan`
6. `style-reel-review`

Existing `motion-design-contract`, `motion-recipe`, Storyboard, HyperFrames
choreography, keyframe receipts, creative review, audio decisions, Golden, and
real-project validation remain authoritative and are not duplicated.

## 2. portrait-brand-profile

Purpose: version the named user's approved or proposed visual/sonic identity.

Invariants:

- `profile_id=hongrun` and `identity_mode=self` for this profile;
- `approval_status=proposed` until a named user approves an exact Style Reel;
- signature primitives, palettes, typography, easing, texture, forbidden
  defaults, and sonic family IDs are explicit;
- production default requires a current Golden and two real validation receipts;
- no secret, source photo, or private media bytes are embedded.

## 3. portrait-energy-map

Purpose: record chapter-level energy and every meaningful opportunity's visual
intensity decision without cadence or quotas.

Invariants:

- source/output order and windows derive from the existing semantic brief/EDL;
- every semantic opportunity has exactly one energy decision;
- `quiet` has a non-empty content-specific rationale;
- micro/meso/macro rows cite evidence and a semantic event;
- gesture-driven rows cite a verified gesture/hand observation;
- chapter transitions cite chapter-boundary evidence;
- density is a reported metric only and cannot appear as a selection trigger.

## 4. portrait-motion-contract

Purpose: bind one existing selected MQE event to portrait eligibility, brand
profile, energy decision, primary portrait recipe, optional supporting layers,
protected regions, and fallback.

Invariants:

- semantic/copy/window fields inherit the existing approved contracts exactly;
- profile and energy-map path/hashes are current;
- one primary recipe; zero or more compatible supporting layers;
- all layer strings are metadata, not additional visible copy;
- camera, gesture, mask, cutaway, and IP capabilities cite required evidence;
- product-card treatment is forbidden by default;
- fallback is deterministic and cannot introduce a product card.

## 5. portrait-sonic-plan

Purpose: bind each selected portrait event to one current audio decision and the
shared signature motif vocabulary.

Invariants:

- 100% decision coverage, not 100% cue coverage;
- cue rows bind asset bytes, rights, decoded-PCM fingerprint, phase/word/gesture
  landing, duration, gain, and planned measurements;
- silent rows have an event-specific reason;
- motif families belong to the exact profile version;
- actual review mix evidence remains owned by existing audio production/QA.

## 6. style-reel-plan

Purpose: prove A/B/C compare expression rather than content.

Invariants:

- three distinct directions: `luminous_intelligence`,
  `high_energy_creator`, `humanist_cinema`;
- identical source/EDL/transcript/semantic event set/captions/duration and audio
  comparison policy across all directions;
- 30–45 second duration target; a justified small tolerance is explicit;
- each direction includes enough events to demonstrate micro, meso, and one
  applicable macro or explicitly explains why macro is unavailable;
- all reels remain isolated outputs and cannot become the automatic master.

## 7. style-reel-review

Purpose: preserve technical, multimodal, and user decisions without conflating
their authority.

Invariants:

- review starts pending and binds exact reel bytes plus all upstream contracts;
- automated status covers equality, decode, caption, geometry, parity, audio,
  source preservation, and evidence freshness;
- multimodal actor can reject or recommend only;
- HongRun supplies format fit, person primacy, expressive quality, non-noisy
  quality, semantic usefulness, sonic fit, and repeat-use willingness;
- user may select one direction, reject all, or request a scoped revision;
- approval produces a proposed Golden request, not production default.

## 8. Cross-contract validation order

1. Validate existing project/source/identity/rights configuration.
2. Validate existing EDL, transcript, semantic brief, adaptive regions, and
   motion-design contract.
3. Validate portrait profile and eligibility.
4. Validate energy map against every semantic opportunity.
5. Validate each portrait motion contract against selected events, recipes,
   protected regions, and capability evidence.
6. Validate sonic plan against selected events and profile families.
7. Validate Style Reel plan equality and direction distinctness.
8. After implementation, validate actual renderer/audio/caption/parity evidence.
9. Validate review authority and hashes.
10. Create/update Golden only after the named-user gate.

## 9. Cross-file rules not expressible in schemas

- event ID sets, order, windows, word IDs, and approved copy must match existing
  contracts exactly;
- source and derived artifact hashes must be recomputed from bytes;
- profile approval actor must be HongRun or another explicitly configured named
  owner, never an agent/multimodal actor;
- Style Reel source windows and event sets must be identical;
- structural direction fingerprints must differ in hierarchy, layout, camera,
  motion, and supporting layers—not merely tokens;
- Golden and maturity promotion require receipts bound to the same current Git
  commit, source tree, profile version, and configuration family.

## 10. Positive, negative, and boundary cases

Positive:

- A PBM-03 row cites a hand-track observation, approved phrase, word landing,
  gesture apex, safe region, and PBM-S02 motif.

Negative:

- A macro transition cites only `elapsed_seconds=15`; reject it.
- A Style Reel changes the semantic event set for the high-energy option; reject
  all three as a comparison set.
- A user approval is copied from the previous candidate after reel bytes change;
  mark stale.
- A portrait fallback selects MQE-04 generic cards; reject it unless the semantic
  exception explicitly proves a card-shaped evidence object.

Boundary:

- No authorized SFX exists: retain valid intentionally-silent decisions and
  compare visual directions without fictional audio readiness.
- No subject mask exists: PBM-02 may use side-depth placement but cannot place
  text behind the subject.
- The selected 30–45s source contains no chapter boundary: Style Reel plan marks
  macro not applicable and compares micro/meso treatments honestly.
