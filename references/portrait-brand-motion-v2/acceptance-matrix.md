# Acceptance Matrix

Status: design obligations, not current implementation claims.

## 1. Gate authority

| Owner | May pass | May reject/recommend | Cannot do |
|---|---|---|---|
| automated validators | deterministic contracts, media, timing, geometry, parity, audio, provenance | fail precise facts | approve taste or repeat-use willingness |
| multimodal reviewer | none of the user-only gates | format mismatch, semantic weakness, visual noise, anatomy/artifact concerns | approve brand identity, publishability, or likeness |
| HongRun | brand taste, direction, repeat use, publish willingness | any subjective outcome | override missing/corrupt/stale technical evidence without a tracked correction |

## 2. Acceptance rows

| ID | Requirement | Fixture/automated gate | Real Style Reel gate | Promotion blocker |
|---|---|---|---|---|
| PBM-AC-001 | eligibility and identity | self + HongRun + portrait evidence; reject third-party/generic/uncertain | review identifies source as person-first | yes |
| PBM-AC-002 | event inheritance | exact event/order/window/word/copy hashes | event rationale matches spoken source | yes |
| PBM-AC-003 | energy decisions | all opportunities covered; no cadence/quota/random triggers | quiet and active moments feel intentional | yes |
| PBM-AC-004 | no product-card default | DOM/style/recipe audit rejects generic card shell except evidenced semantic exception | HongRun answers format-fit yes | yes |
| PBM-AC-005 | person primacy | face/eyes/mouth/hand/caption/UI intersections and attention-layer limits | HongRun answers person-primary yes | yes |
| PBM-AC-006 | structural variety | fingerprints differ by hierarchy/layout/camera/choreography/layers | A/B/C visibly feel distinct | yes |
| PBM-AC-007 | timing | word/gesture/chapter binding and proposed onset tolerances | 1× playback feels synchronized | yes |
| PBM-AC-008 | camera/depth | safe crop, subject track, mask provenance, seek safety, fallback tests | no face distortion or artificial cutout feel | yes |
| PBM-AC-009 | semantic assets | asset request/provenance/rights/topic/padding/anatomy | cutaway adds understanding and integrates with footage | yes when applicable |
| PBM-AC-010 | composite readability | >=4.5:1 worst measured representative composite; no protected-region overlap | readable at full frame and thumbnail | yes |
| PBM-AC-011 | four phases | actual painted DOM/keyframe/parity evidence at entrance/mid/pre-exit/post-exit | no abrupt jump or leftover element | yes |
| PBM-AC-012 | sonic identity | all decisions covered; PCM identity/onset/masking/true peak; family diversity | HongRun answers sonic-fit yes or documented N/A | yes when cues exist |
| PBM-AC-013 | common comparison | identical source/EDL/transcript/captions/events/duration/audio policy | synchronized review works | yes |
| PBM-AC-014 | user authority | review actor and exact media hashes; stale decisions rejected | all six user questions recorded | yes |
| PBM-AC-015 | accessibility | reduced-motion representation, readable copy, caption separation | no discomfort at 1× playback | yes |
| PBM-AC-016 | legacy isolation | old config bytes unchanged; feature disabled; screen/product and third-party fixtures unchanged | existing canaries remain readable/reproducible | yes |
| PBM-AC-017 | failure and fallback | missing track/mask/asset/runtime/license selects declared safe fallback | no surprise product card appears | yes |
| PBM-AC-018 | cache/invalidation | profile/energy/recipe/renderer/audio changes invalidate exact dependencies | revised reel changes only approved scope | yes |
| PBM-AC-019 | cost/privacy/rights | provider reservation and reconciliation; local default; provenance complete | no unexpected upload or paid call | yes |
| PBM-AC-020 | Golden promotion | first approval creates provisional only; second different topic shares implementation/profile | named user approves both | yes for production default |

## 3. Required negative tests

1. Talking head routes to an existing generic product-card fallback.
2. Third-party portrait source requests the HongRun profile.
3. Energy map selects macro from elapsed time only.
4. Quiet opportunity has no rationale.
5. PBM-03 lacks a current hand/gesture track.
6. PBM-02 places type behind the subject without a verified mask.
7. PBM-05 camera crop intersects eyes/mouth or falls outside source bounds.
8. PBM-06 asset lacks rights/topic/anatomy/padding evidence.
9. A/B/C differ only by color or easing.
10. One Style Reel has a different event set, captions, duration, or audio policy.
11. An SFX decision cites a different/malformed cue, stale mix, or masked cue.
12. A review actor other than HongRun sets brand taste to approved.
13. A prior approval is replayed after reel/profile/recipe bytes change.
14. A first canary attempts to promote the profile to production default.
15. A migrated v10 project changes on-disk YAML or enables portrait v2.
16. Missing advanced runtime silently drops to an opaque rounded card.

## 4. Required boundary tests

- zero gesture events;
- no chapter boundary in the Style Reel window;
- no authorized SFX or BGM;
- centered close face with minimal negative space;
- low-light and bright source variants;
- reduced-motion preference;
- a valid semantic evidence card in a personal video;
- one strong emotional quiet passage longer than the contextual density warning;
- subject tracking available but subject mask unavailable;
- identical PCM in different containers and small permissible audio/render drift.

## 5. Maturity path

| State | Minimum evidence |
|---|---|
| documented | approved design-freeze candidate only |
| director_integrated | real routes, invalidation, failures, and default-off migration |
| fixture_validated | schemas/cross-contract tests, renderer fixtures, synthetic media, and current full-suite receipt |
| real_project_validated | exact approved `告别2025` Style Reel plus second different portrait topic |
| production_default | both validations share current implementation/profile/config family and HongRun explicitly approves default use |

No lower state may be described as higher maturity.

## 6. Success definition

The implementation succeeds only if:

- technical and preservation gates remain green;
- selected Style Reel is preferred over the current portrait candidate, not
  merely over no motion;
- HongRun approves format fit, person primacy, expressive quality, semantic help,
  sonic fit, and repeat use;
- the second topic confirms portability;
- correction time and render cost remain recorded and acceptable;
- old projects and non-HongRun modes remain unchanged by default.
