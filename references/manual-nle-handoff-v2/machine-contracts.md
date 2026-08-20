# Machine contracts

## Contract set

### `nle-handoff-package-v2`

Top-level package receipt. Required fields:

- schema/kind/status/package profile and level;
- project, source, automatic-master, EDL, and implementation references;
- ordered layer inventory;
- nested timeline, rights, compatibility, validation, and import-guide refs;
- package root and complete file inventory with SHA-256, size, type, purpose,
  provenance, rights status, availability, and generated/copied/link mode;
- capability claims with every native API/CLI/draft/headless flag false;
- package integrity hash for drift detection only.

`status=pass` is derived only after every required nested artifact validates.

### `nle-layer-asset-v2`

One media/text/source layer. Required invariants:

- canonical path remains under the package or is an explicitly declared
  immutable external source reference;
- available files exist and match hash/size; unavailable rows have no hash;
- media timing uses finite non-negative rational values and `end > start`;
- video declares width/height/fps/pixel format/alpha status and decode receipt;
- audio declares sample rate/channels/duration and decode receipt;
- caption declares authority, encoding, segmentation count, and timebase;
- identity/IP/font assets declare rights and redistribution status;
- event-local assets bind semantic/render event IDs and exact output window.

### `nle-layer-timeline-v2`

Ordered track/layer placement independent of any NLE. It binds:

- output timeline rate, canvas, duration, and zero origin;
- track roles and z/order;
- clips with source refs, source range, timeline range, gain/opacity defaults,
  handles, semantic event ID, and editability class;
- OTIO projection and round-trip/loss report;
- marker inventory for events, captions, chapters, product windows, and outro.

### `nle-asset-rights-v1`

Personal-IP and modular-outro files are never authorized merely because a path
exists in project configuration. Each available `ip_*` or `outro_*` layer must
carry a current rights receipt that binds the exact source path and SHA-256,
allowed package role, identity mode, non-empty rights basis, and redistribution
policy. The receipt is copied into `10-evidence/asset-rights/` and becomes part
of the package inventory. Missing, malformed, stale, role-mismatched, or
identity-mismatched evidence makes package construction fail closed.

### `manual-nle-modular-outro-v1`

The HongRun `luminous_intelligence` source compiler emits a 3–6 second
HyperFrames project with explicit canvas/rate, local GSAP runtime, brand
profile hash, copy/timing JSON, three independently editable SVG action icons,
and deterministic file inventory. Its initial status is always
`preview_pending` and `render_authorized=false`. The source project may be
archived deterministically as `outro_source_project`; only the copy, icons, and
source archive enter the NLE package before visual approval. Text-free overlay,
reference composite, and stems remain `unavailable` until preview approval and
their own render/decode/parity evidence exist.

After approval, `manual-nle-outro-render-approval-v1` binds the exact preview
contract/snapshot, explicit actor decision, two-item render scope, reason, and
time. Its SHA-256 is drift detection only, not encryption or identity
authentication. `manual-nle-outro-render-receipt-v1` then binds the current
source contract, approved/reference byte equality, text-free ProRes 4444 asset,
alpha evidence, full reference decode, canvas/rate/duration, and role-specific
rights receipts. The transparent layer contains no CTA words; editable copy is
recreated from `copy.json` as native NLE text.

### `nle-compatibility-report-v2`

Records facts instead of assumptions:

- target editor/version/platform and observation time;
- SRT import result and editability;
- each media format import/decode/alpha/audio result;
- relink behavior, timing drift, frame mismatch, color/alpha issues;
- native draft/API/CLI/headless flags;
- unsupported or manually recreated features;
- named human canary result.

### `nle-return-receipt-v2`

Binds returned media to package, automatic master, correction summary, and fresh
QA. It does not accept a returned path equal to the automatic master. Any bound
package/source/output drift reopens manual finish and delivery QA.

## Deterministic validation rules

1. Validate types before accessing nested values; reject bool-as-number and
   NaN/Infinity.
2. Preserve lexical authorized roots and reject Junction/symlink/reparse-point
   redirection before any mkdir/copy/write.
3. Preflight the complete package, build into a sibling staging directory,
   validate all nested files, then atomically publish the package directory or
   manifest. Failure leaves the previous valid package unchanged.
4. Hash actual bytes once and reuse the immutable snapshot for parse/validation.
5. Inventory every generated/copied file; extra, missing, stale, duplicate, or
   cross-package files fail validation.
6. Decode/probe media; extension and caller booleans are not evidence.
7. Recompose clean A-roll + selected overlays + audio + caption reference and
   compare against the automatic master within frozen per-layer tolerances.
8. Alpha evidence includes decoded alpha-channel presence, nontrivial alpha
   coverage, black/white/busy-background composites, and import-canary result.
9. Caption instructions must map exact `master.srt` segments and current word
   IDs; no paraphrase or timing change.
10. Human import/editability approval is separate from automated package QA.
11. Generated outro copy, icons, and source archive remain independently
    removable; source-project availability never implies a rendered overlay or
    approved visual appearance.

## Editability classes

- `native_editable`: verified native text/audio/media behavior in the named NLE.
- `media_layer_editable`: imported media can be moved/trimmed/hidden but its
  internal graphics/text are baked.
- `source_project_editable`: editable only in the retained HyperFrames project.
- `reference_only`: visual/audio reference, not the edit surface.
- `unavailable`: no file was generated or authorized.

No layer may claim a higher class without a current compatibility receipt.
