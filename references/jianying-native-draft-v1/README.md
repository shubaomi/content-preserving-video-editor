# Jianying native editable draft adapter v1 — design freeze

Status: `pending_user_approval`. No production implementation is authorized by
these documents.

The adapter is a disposable projection of the current editor-neutral timeline,
not a replacement for video-use EDL, `layer-timeline.json`, HyperFrames, or the
automatic master. V1 targets a newly created, isolated Jianying Desktop draft
that exposes captions, event overlays, IP images, audio stems, and modular outro
elements for human correction.

Read in this order:

1. `goal-objective.md`
2. `requirements-traceability.md`
3. `architecture-and-tool-boundaries.md`
4. `timeline-authority.md`
5. `draft-layout-and-versioning.md`
6. `track-contracts.md`
7. `security-isolation.md`
8. `migration-and-rollback.md`
9. `canary-plan.md`
10. `acceptance-matrix.md`
11. `implementation-plan.md`
12. `risk-and-cost-ledger.md`
13. `research-sources.md`
14. `design-review-report.md`

The editor-neutral standard repair kit and `nle-package-v2` remain mandatory
fallbacks. A native draft failure must never invalidate or overwrite them.

