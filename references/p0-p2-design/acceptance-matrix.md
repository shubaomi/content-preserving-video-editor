# P0-P2 Acceptance Matrix

Status: design-freeze candidate; thresholds are the recommended implementation
baseline and require user approval with the design freeze.

## 1. Gate ownership

| Gate owner | May pass | May reject | May not do |
|---|---|---|---|
| Automated | hashes, schemas, timing, geometry, decode, loudness, contrast, collisions, stage readiness | any measurable contract violation | approve aesthetics, likeness, click appeal, or publishability |
| Multimodal reviewer | semantic fit, explanatory value, anatomy/text anomalies, clutter, mechanical rhythm, visual consistency | reject or recommend revision with evidence | write user approval or promote production default |
| User | paired creative preference, brand taste, likeness, cover appeal, final publishability | reject for any creative/business reason | make a tampered or technically invalid artifact valid without regeneration |

An automated failure blocks later approval. A multimodal pass is only a
recommendation. User approval is necessary but not sufficient when automated
evidence is invalid or stale.

## 2. Evidence levels

| Level | Evidence | Maximum maturity |
|---|---|---|
| D | documents and schemas only | `documented` |
| F | deterministic fixtures, negative tests, synthetic short media | `fixture_validated` |
| R-L | current authorized 30–90s landscape screen/product source | contributes to `real_project_validated` |
| R-P | current authorized 30–90s portrait talking-head source | contributes to `real_project_validated` |
| U | explicit user paired review and publishability decision | required for `real_project_validated` |

Fixture, generated color cards, mocked PNG headers, structured JSON, and old
project reports cannot substitute for R-L, R-P, or U.

## 3. Recommended canaries

### Canary R-L — Landscape screen/product demo

- Duration: 60–90 seconds; 30 seconds allowed only if it still contains all
  required risk states.
- Source: current authorized product/data-report screen recording.
- Must contain: small UI text, at least one target change (scroll/modal/route or
  layout), one comparison/process/proof opportunity, a quiet-source interval,
  captions, one audible cue, and one intentionally silent motion decision.
- Identity: `third_party` or `generic` according to the actual rights/creator
  contract; no HongRun identity when the source is third-party.

### Canary R-P — Portrait talking head

- Duration: 60–90 seconds; source selection is a required user input before the
  implementation validation run.
- Must contain: visible face, at least one hand/gesture or body movement, captions,
  one concept cutaway/side annotation, one protected face/hand test, and one
  event near a platform safe-zone boundary.
- Identity: `self` only for HongRun-owned footage; otherwise `third_party` or
  `generic` with personal assets forbidden.

Both canaries must use the same implementation commit and compatible schema-v10
configuration. Changing code after the first run makes that receipt stale.

## 4. Core acceptance matrix

| Requirement | Automated acceptance | Multimodal review | User acceptance | Blocking rule |
|---|---|---|---|---|
| RQ-001 preservation | immutable source hash; valid EDL/word/output map; no unexplained omission; source tail/final-edit-correctness pass | flag narrative loss or misleading compression | confirms no material section was lost | any unexplained omission or wrong ending blocks |
| RQ-002 semantic binding | 100% rendered events bind approved semantic ID, words, window, takeaway, copy and evidence; zero extra visible strings | ≥95% events judged semantically correct; zero critical misleading event | candidate motion helps rather than restates speech | one critical wrong/unapproved event blocks |
| RQ-003 geometry | ≥95% target/connector observations within configured tolerance; zero lost/offscreen/incorrect target at reviewed phases | reject visually wrong enclosure/attachment even if tolerance passes | no observed “框错、线错、对不准” issue in sample | any stale/wrong target or clipped primary element blocks |
| RQ-004 source state | state signatures cover entire active window; all changes rebind or exit | confirm overlays leave before content becomes irrelevant | accepts timing around scroll/modal/route | stale overlay at any reviewed state blocks |
| RQ-005 density | 100% opportunity decisions; zero forced quota/cadence; concurrent primary events ≤1 | candidate is neither empty nor distracting; quiet beats justified | candidate preferred to baseline for rhythm | event count alone cannot pass/fail; unexplained filler blocks |
| RQ-006 motion craft | all four phases, seek safety, strict check, animation map and keyframe receipt pass | choreography, hierarchy and pacing have a clear reason; no mechanical repetition | candidate preferred for motion quality | missing phase/receipt or broken seek blocks |
| RQ-007 readability | composite contrast/crop/caption/face/safe-zone checks pass at all selected phases | full-size and thumbnail remain legible over source | no important item is hard to read | any unreadable primary copy/target blocks |
| RQ-008 SFX | 100% audio decisions; cue assets decode/hash; onset tolerance ≤80 ms; no `dialogue_harmed`; final true peak/loudness pass | cues fit the action and motif set is coherent, not repetitive | SFX-on version is audible and not distracting | missing decision, inaudible selected cue, or speech harm blocks |
| RQ-009 required stages | applicable required outputs are `asset_ready/ready`; exact hashes bind delivery | identify any package that feels obviously incomplete | pre-publish checklist has no unexplained missing item | contract-only required stage blocks |
| RQ-010 captions | text traces to words; median sync error ≤120 ms, p95 ≤250 ms; punctuation-tail and cut-boundary tests pass; final SRT hash/filter verified | natural phrase segmentation and readable cadence | first/middle/last and transition spots feel synchronized | missing captions, wrong wording, or gross drift blocks |
| RQ-011 universal output | one universal MP4; platform reports bind same hash; full decode and technical gates pass | crop/safe-zone preview remains usable | user accepts one file for both platforms | identical duplicate platform files are a workflow defect |
| RQ-012 adaptation | rotation-aware display geometry; correct layout family; face/UI/caption constraints pass | composition fits landscape screen and portrait person | accepts both canaries without format-specific manual repair | either canary failure prevents real-project promotion |
| RQ-013 third-party identity | identity mode required; forbidden asset/copy/intro/outro checks pass | flag implicit identity impersonation | confirms rights and identity treatment | any HongRun identity insertion in third-party mode blocks |
| RQ-014 IP/cover | provenance, semantic binding, anatomy/text/crop/padding and layout technical checks pass | topic fit, anatomy, expression and integration recommended/rejected | user alone approves likeness and cover click appeal | likeness cannot be auto-approved; N/A allowed when identity-neutral |
| RQ-015 approval integrity | sample/full/project/config/evidence hashes bind approvals; any drift invalidates | candidate reviewed at actual representative events | explicit sample approval precedes full render | stale/missing approval blocks full render |
| RQ-016 review usability | one review surface contains embedded paired media, markers, phases, rationale, target, audio toggles; proposals remain pending | review evidence is sufficient to diagnose each event | review can be completed without external frame-description work | missing paired evidence blocks approval request |
| RQ-017 optional adapters | disabled by default; capability verified; export/loss/round-trip receipts; returned master fully revalidated | review any visual loss after round trip | user chooses whether manual finish is worth it | adapter cannot report automatic completion |
| RQ-018 cost/privacy/cache | provider rights/privacy/budget checks; exact reservations/actuals; cache equivalence/invalidation; resume works | recommend cheaper fallback if creative gain is negligible | accepts cost/time before expensive run | unapproved upload, unknown rights, or budget overrun blocks |
| RQ-019 promise coherence | hook/title/cover/description/motion claims trace to one ledger and evidence; prohibited claims absent | assess topic fit and non-mechanical coherence | user accepts promise and publishing copy | invented or conflicting claim blocks |
| RQ-020 truthful completion | maturity audit verifies exact evidence and authors; stale/tampered/fixture-as-real cases fail | recommendation stored separately | publishability/taste/likeness fields are explicitly user-authored | any actor impersonation or maturity jump blocks |

## 5. Cross-canary promotion thresholds

All conditions are conjunctive:

1. Both R-L and R-P use real, authorized, current sources.
2. Every automated blocker above passes.
3. Semantic correctness is at least 95% across reviewed rendered events and has
   zero critical mismatch.
4. Geometry correctness is at least 95% across phase observations and has zero
   wrong target, stale overlay, clipped primary element, or connector attached
   to the wrong node.
5. Caption sync thresholds pass for both sources; terminology/text correctness is
   100% for the reviewed sample.
6. Every motion event has an audio decision; all selected cues are audible
   without dialogue harm. Audible cue percentage is reported, not optimized to a
   fixed target.
7. The user prefers the candidate over the baseline for both canaries, answers
   `yes` to sample publish willingness, and records reasons.
8. Required corrections take no more than 20 minutes per 60–90s sample after
   the first complete candidate, with no more than two critical corrections.
9. The same implementation commit and schema version bind both receipts.

These thresholds promote to `real_project_validated`, not automatically to
`production_default`. Production default is a separate, explicit decision after
cost, stability, and migration evidence are reviewed.

## 6. Sample selection and review points

The sample is a continuous 60–90s segment when possible. If risk coverage cannot
fit one segment, a review reel may concatenate source-preserving extracts, but
its EDL must be explicit and it cannot be presented as a continuous narrative.

For each selected event, collect:

- baseline and candidate at matched semantic time;
- entrance, mid/explain, pre-exit, and post-exit snapshots;
- target boxes and connector edges on the real source;
- original sentence, word IDs, approved copy, rationale, and takeaway;
- SFX off/on and, if BGM is enabled, BGM off/on auditions;
- automatic findings and multimodal recommendation;
- user decision and optional correction proposal.

Review at 1× playback and full resolution, then inspect thumbnail/mobile scale.

## 7. Positive, negative, and boundary cases

### Positive

The landscape candidate uses a verified comparison effect over two chart
regions, exits before scroll, keeps captions visible, and uses a restrained
two-note cue. The user prefers it because the relationship is clearer.

### Negative

All unit tests pass, but a cyan label disappears on the source and one box moves
with the wrong chart. The canary fails RQ-003 and RQ-007; green fixtures do not
promote it.

### Boundary

The portrait candidate contains only two rendered motion events in 75 seconds
because the speaker and gestures carry the explanation. Opportunity decisions
and paired review show that extra graphics would distract. It can pass RQ-005.

## 8. Approval records

User decisions must include reviewer, timestamp, baseline/candidate hashes,
criterion, decision, and reason. Applicable criteria are:

- overall sample quality;
- candidate-vs-baseline preference;
- publishability;
- brand taste (self-owned only);
- likeness (when a real person is generated or transformed);
- cover click appeal (when a cover is in the deliverable package).

`not_applicable` requires an evidence-backed identity/delivery reason. An empty
or defaulted field is pending, not approval.
