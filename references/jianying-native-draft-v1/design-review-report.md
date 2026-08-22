# Integrated design review

## Product and usability

The need is real: a native draft can reduce subtitle, track and audio correction
friction compared with importing loose files. It does not improve the automatic
edit itself. The design preserves value even when native compatibility fails by
keeping the master and neutral package independent.

## Architecture

Pass. The draft is a projection, not authority. Repair and layered profiles make
the fidelity/editability trade-off explicit. Timeline rounding, inventory and
fallback are machine-checkable.

## Security and privacy

Pass with implementation gates. Fresh isolated drafts, no existing-draft reads,
lexical safe roots, pinned dependencies and metadata scans address the highest
risks. Draft-store installation remains separately unauthorized.

## Creative fidelity

Pass with limits. Captions, clip-level motion, IP, audio and outro are editable.
HyperFrames internals and proprietary Jianying effects remain out of scope, so
the design does not promise native control it cannot prove.

## Commercial/practical value

Conditional pass. Value is demonstrated only if the real short canary completes
the five edits with acceptable relink effort and time. A technically valid draft
that is slower than the current Chinese import guide must not be promoted.

## Evidence boundary

Design review does not prove that any current Jianying version opens the draft.
It authorizes no dependency installation, native generation, draft-store write,
video render, commit or push. Recommendation: approve implementation through
WP3 first; require another explicit decision before WP4 installation.

