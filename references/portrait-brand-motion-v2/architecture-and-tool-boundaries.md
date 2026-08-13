# Architecture and Tool Boundaries

Status: proposed additive design.

## 1. High-level flow

```text
video-use words / EDL / output timeline
                  |
source evidence + subject/face/hand/caption regions + profile
                  |
approved semantic brief and all opportunity decisions
                  |
        portrait eligibility decision
             /              \
      not eligible        eligible
      existing MQE          |
                    portrait energy map
                           |
              portrait recipe compiler
                           |
        motion-design contract + choreography
                           |
             HyperFrames composition
                           |
  runtime DOM/keyframes/snapshots/parity + audio decisions
                           |
     three aligned Style Reels (design-validation only)
                           |
     automated -> multimodal -> named-user brand gate
                           |
        provisional portrait Golden / rollback
```

The portrait layer does not add a Director stage in the first implementation.
It enriches semantic planning, motion-design compilation, sample review, and
Golden evidence while preserving the current state machine and approval order.

## 2. Ownership table

| Concern | Owner | May do | Must not do |
|---|---|---|---|
| words, EDL, output mapping, captions | video-use | provide exact word and edit timeline | choose portrait effects or rewrite meaning |
| policy, identity, evidence, energy map, recipe selection, approval, invalidation | Director / this Skill | compile typed contracts and block unsafe work | render creative pixels or self-approve taste |
| full video composition and motion | HyperFrames | implement approved choreography with DOM/SVG/GSAP/media transforms and export runtime evidence | invent copy, meaning, target, energy, or approval |
| final mix, subtitle burn, encode, decode, loudness | FFmpeg under Director receipts | deterministic media mechanics | replace creative motion with translated static cards |
| selected complex event | optional Remotion adapter | render a named, contract-bound event with strict parity/license evidence | render a second full video or become required |
| subject/face/hand/scene perception | optional adapters | provide hash-bound observations/tracks | guess a region or promote stage status |
| brand taste | HongRun | approve/reject exact Style Reel and Golden | be inferred from automated scores |

No upstream video-use, HyperFrames, Remotion, OpenCut, or Jianying source change
is planned. An upstream edit requires an independent minimal reproduction owned
by that upstream project.

## 3. ADRs

### PBM-ADR-001 — Add a profile-bound expression layer, not a new editor

**Decision:** Extend the existing MQE compiler with portrait eligibility,
energy, profile tokens, recipes, and review contracts.

**Why:** The existing pipeline already proves preservation, captions, geometry,
audio, parity, and delivery. Replacing it would discard working guarantees.

**Trade-off:** The implementation must respect existing schemas and invalidation
rather than moving fast with a separate hardcoded renderer.

**Alternative rejected:** a standalone “HongRun renderer” with its own caption,
audio, and event timeline.

### PBM-ADR-002 — Brand language is versioned profile data plus executable recipes

**Decision:** Separate profile tokens and approved style direction from recipe
mechanics. Both are hash-bound in compiled artifacts.

**Why:** A brand is not one CSS file, and a recipe should remain reusable without
silently changing the user's identity.

**Trade-off:** Profile migration and Golden invalidation become explicit.

### PBM-ADR-003 — Energy map is editorial, not cadence optimization

**Decision:** Record quiet/micro/meso/macro decisions from semantic, speech,
gesture, and chapter evidence; prohibit fixed cadence and quota repair.

**Why:** The observed failure is format mismatch, not simply low activity.

**Trade-off:** Some videos remain deliberately sparse; richer output comes from
layered expression within justified events.

### PBM-ADR-004 — Three-way Style Reel precedes default-profile changes

**Decision:** Compare three aligned directions on identical 30–45s source and
semantic contracts before implementing a production default.

**Why:** “Cool” and “personal” are subjective and cannot be finalized from text
specification alone.

**Trade-off:** The first implementation includes isolated prototype components
and three short renders before a full video.

### PBM-ADR-005 — Standard path avoids advanced runtimes

**Decision:** DOM/SVG/GSAP and HyperFrames media transforms must express the base
language. Matting, Remotion, Lottie, Three/WebGL, or generation are optional.

**Why:** The language should work on the user's machine, remain seek-safe, and
not depend on paid/cloud/GPU capabilities.

**Trade-off:** Some depth effects use simpler foreground/side placement when a
verified mask is unavailable.

### PBM-ADR-006 — No product-card fallback

**Decision:** Every portrait recipe declares a portrait-safe fallback chain
ending in simpler type/light, caption/source, or action_required. Generic product
cards are excluded unless the semantic object is genuinely a card/evidence item.

**Why:** Silent fallback to the current card shell would preserve the exact
brand failure this design is meant to solve.

### PBM-ADR-007 — Golden requires two content domains

**Decision:** The first approved Style Reel creates a provisional Golden;
production default requires another materially different HongRun portrait topic
under the same implementation/profile version.

**Why:** One low-light reflective clip cannot prove a durable personal language.

**Trade-off:** Initial use remains opt-in even after the first user approval.

## 4. Planned artifact graph

```text
portrait-brand-profile.json
           + portrait-energy-map.json
           + existing motion-design-contract.json
           + portrait-recipes-v2.json
           -> portrait-motion-contract.json
           -> hyperframes-choreography.json
           -> renderer manifest/export/keyframe receipts/parity
           + portrait-sonic-plan.json
           -> style-reel-plan.json
           -> style-reel-review.json
           -> portrait-golden.json (only after user approval)
```

Each arrow binds canonical path, SHA-256, schema version, producer, subject, and
input inventory. Self-declared status without current evidence is not completion.

## 5. Security, privacy, and rights

- Source media, face/hand tracks, masks, reference photos, and review media stay
  local by default.
- Cloud perception/generation requires current provider, rights, privacy, plan,
  cost, request, result, and output-hash receipts.
- Review servers retain existing loopback/auth/CSRF/path-containment rules.
- Logs and portable packs exclude or sanitize private absolute paths, identity
  references, tokens, and source-derived assets under existing policies.
- Third-party identity mode is never eligible for HongRun brand language.
- Proprietary app screenshots may be used only as user-supplied inspiration for
  general principles; no assets, templates, sounds, or project formats are
  imported without independent authorization and license review.

## 6. Reliability and recovery

- Every generated contract is immutable or atomically replaced under existing
  Director writers.
- Cache keys include source, EDL, transcript, semantic brief, region evidence,
  portrait profile/version, energy map, recipe registry, renderer/runtime, and
  audio assets/policy.
- Event-scoped invalidation is permitted only when shared chapter/profile/source
  artifacts remain unchanged.
- A missing optional capability chooses the declared deterministic fallback; a
  missing required proof yields action_required.
- No completion receipt is retained after any bound input changes.

## 7. Non-functional requirements

| Area | Frozen requirement |
|---|---|
| determinism | identical canonical inputs produce identical contracts and fingerprints |
| seek safety | every recipe passes arbitrary-time entrance/mid/pre-exit/post-exit checks |
| accessibility | all visible copy remains readable, caption-safe, and motion-reduction compatible |
| performance | standard Style Reel path runs without required GPU/cloud services; exact budgets measured during implementation |
| maintainability | new recipes are registry entries plus renderer components, not project-script hardcoding |
| observability | every selection/fallback/quiet/advanced decision records evidence and reason |
| cost | paid calls require existing governance; full-video render is prohibited before style approval |
| portability | existing universal MP4, HyperFrames project, and review artifacts remain deliverables |

## 8. Failure modes

| Failure | Required response |
|---|---|
| identity not HongRun/self | feature not applicable; existing grammar remains |
| portrait eligibility uncertain | action_required or existing neutral grammar; never apply HongRun identity |
| face/hand/subject evidence missing | choose no-occlusion/no-gesture recipe fallback |
| source too crowded for copy | camera/light-only or quiet/caption decision |
| recipe proof/parity fails | affected Style Reel blocked; do not approve candidate |
| SFX missing or masked | intentionally_silent or authorized replacement; no fabricated asset |
| user rejects all directions | keep feature disabled and return to design; do not select the least-bad direction |
| second-topic validation fails | Golden remains provisional and production default stays false |
