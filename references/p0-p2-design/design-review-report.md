# P0-P2 Design Review Report

Status: candidate review complete; pending user approval.
Review scope: architecture, creative direction, aesthetics, commercial value,
practicality, usability, testability, security/privacy, and cost.
No production code or media render was reviewed or produced in this phase.

## 1. Review conclusion

The design is suitable to freeze as an implementation candidate. No unresolved
`BLOCKER` or `HIGH` design finding remains after the corrections recorded below.
This is a design verdict only: current implementation maturity is not promoted,
and both real canaries remain future implementation gates.

The recommended product decision is to continue with the design because it
addresses repeated, evidenced failures—random semantic copy, inaccurate/stale
geometry, weak motion craft, incomplete deliverables, and expensive review
cycles. The rejected alternative is to add more templates, enforce higher event
density, or imitate proprietary presets; those actions would optimize visible
activity instead of explanatory value.

## 2. Review by discipline

### Architecture — pass

- Director remains the single policy/evidence/gate owner.
- video-use, HyperFrames, FFmpeg, Remotion, and optional NLE/interchange tools
  have non-overlapping ownership.
- Semantic opportunities are separated from selected render events, eliminating
  the existing one-to-one/quota pressure.
- Contracts and downstream invalidation are hash-bound.
- Schema v10 is additive and in-memory; P2 remains default off.

Residual implementation concern: JSON Schema cannot enforce all cross-file set,
ordering, time-window, actor-authorization, or hash-consistency invariants. The
implementation plan therefore requires explicit cross-contract validators and
negative tests before any integration claim.

### Creative and aesthetic direction — pass

- The engine starts from viewer understanding and source evidence, not motion
  frequency.
- Sixteen recipes cover distinct semantic/motion structures without becoming a
  quota.
- Role-specific entrance/explain/hold/exit grammar prevents one global rhythm.
- Composite readability, target state, camera/depth, and sound are part of the
  design rather than post-render decoration.
- Multimodal review may reject/recommend; user paired preference remains the
  aesthetic gate.

Residual human judgment: no design can guarantee taste, likeness, click appeal,
or publishability. These remain explicit user fields, not a planned score.

### Commercial value — pass

- One universal MP4 avoids duplicate platform outputs.
- The editorial promise ledger aligns hook, title, cover, description, CTA, and
  motion claims to source evidence.
- Cost and correction time are acceptance metrics, preventing technically rich
  but commercially inefficient output.
- Third-party footage cannot inherit HongRun identity by directory convention.

Residual business input: the intended audience/CTA may be unknown. The safe
default is neutral education; conversion claims cannot be invented.

### Practicality and operating cost — pass

- Validation is ordered from cheap semantic/schema checks to sample render and
  human review, with full render last.
- Event-scoped caching and dependency invalidation are planned, while ambiguous
  dependencies fail closed to broader invalidation.
- Advanced WebGL/3D and external editor adapters have simpler fallbacks and are
  default off.
- Long/full media is not required to prove contract fixtures; real 30–90s
  canaries prove actual behavior before production promotion.

Residual input: a current authorized portrait talking-head source must be chosen
before implementation can reach `real_project_validated`.

### Usability — pass

- A single paired review surface replaces scattered JSON/file links.
- Review is organized by event and four motion phases, with semantic rationale,
  target overlay, and audio toggles.
- Manual adjustments become pending, auditable correction proposals rather than
  temporary Studio mutations that snap back or untracked file edits.
- Required missing work is visible as `action_required`.

Residual UX proof: the review surface must be tested with a real user on both
canaries; a fixture/browser test cannot establish low review effort.

### Testability and completion truth — pass

- All 20 requirements have automated, multimodal, and/or user evidence owners.
- Seven versioned machine schemas define the implementation seams.
- Positive, negative, and boundary examples exist for every contract.
- `fixture_validated`, `real_project_validated`, and `production_default` cannot
  be collapsed.
- Baseline/candidate hashes and actor-specific approvals prevent self-approval.

Residual technical work: schema examples were validated in memory during design,
but production validators, committed fixtures, full-suite tests, CI receipts,
and current canary receipts are intentionally not implemented in this phase.

### Security, privacy, license, and provenance — pass

- Local processing is preferred; cloud requests require provider, rights,
  privacy, cost, and scope evidence.
- Review server design remains loopback/read-only with CSRF/path/XSS tests.
- Secrets are excluded and unsafe log redaction fails closed.
- AGPL/proprietary projects inform methods only unless an independent adapter and
  license review is approved.

Residual external uncertainty: upstream APIs/licenses/versions can change and
must be reverified during implementation; this design does not claim an adapter
already exists.

## 3. Findings resolved during review

| Finding | Severity before fix | Resolution |
|---|---:|---|
| Keyframe receipt forced one target hash, excluding targetless typography/transition events | HIGH | changed to zero-or-more target-binding hashes; targetless events still require phase/layout/crop proof |
| Creative review forced one target binding for every event | HIGH | changed to a target-binding ID list that may be empty for targetless recipes |
| Audio license evidence reused the audio-asset schema and incorrectly required duration | HIGH | introduced a distinct rights-evidence shape with path, hash, and rights basis |
| Lost/hidden target observations were forced to invent a bounding box | HIGH | visible targets require a box; hidden/lost observations omit it and trigger the invalidation policy |
| External project/license statements lacked primary-source anchors | MEDIUM | added official repository links and kept them research-only/default-off |
| Optional-artifact wording conflicted with non-applicable fields | MEDIUM | clarified declared unavailable slots versus explicitly non-applicable optional fields |

No finding was deferred merely to make the candidate pass.

## 4. Validation performed

- Canonical objective fully reread and SHA-256 matched
  `402ec6d6b96d8e0b964f3b24eb0ce4231d4e9947ece28ad5650eb283810d3a12`.
- Seven schema files parsed as JSON and passed Draft 2020-12 meta-schema checks.
- One representative positive instance for every schema passed validation.
- Focused negative cases passed:
  - quiet-source opportunity carrying a render recipe was rejected;
  - visible target without a box was rejected;
  - intentionally silent audio decision carrying a cue was rejected.
- Required document inventory, schema inventory, RQ-001–RQ-020 traceability,
  and canonical objective hash passed cross-document validation.
- Repository status remained limited to the new design directory.

These checks validate the design artifacts, not production behavior.

## 5. Candidate approval questions

The design recommends all four choices below:

1. Approve additive project schema v10 and keep MQE opt-in for migrated projects
   until both current real canaries pass.
2. Use the authorized landscape product/data-report clip for R-L and provide one
   separate authorized portrait talking-head clip for R-P during implementation.
3. Keep advanced 3D/WebGL/shader recipes default off, using DOM/SVG/GSAP as the
   standard path.
4. Use 100% audio-decision coverage with adaptive audible cues, not sound on
   every event.

Explicit user approval of the design-freeze candidate authorizes only a later
implementation Goal. It does not itself authorize long rendering, upstream
changes, deployment, or publication.
