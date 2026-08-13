# Design review report

## Outcome

`pass_as_candidate` with zero unresolved blocker/high design findings.

## Product review

The need is real: a flattened master is convenient for publishing but poor for
late subtitle, motion, IP, audio, or CTA changes. Retaining only HyperFrames is
insufficient for a Jianying-first human editor because captions, audio, and
timing still require manual reconstruction. A typed layered package solves the
high-value part without depending on private editor internals.

## Chosen direction

Use an editor-neutral `manual_nle_package_v2` with a versioned
`jianying_desktop_compatible_v1` profile. Deliver ordinary editable/importable
assets and exact placement metadata. Keep native Jianying draft generation out
of scope until a sanctioned, stable interface is proven.

## Resolved design findings

- Native project import cannot be assumed; the package does not claim it.
- SRT editability is separated from ASS/emphasis visual fidelity.
- Text-free IP/outro/motion layers prevent avoidable baked-copy lock-in.
- Both event-local and optional full-duration overlays cover fine adjustment and
  easy alignment without making maximum storage the default.
- Alpha format uncertainty is handled by a versioned canary and PNG fallback.
- Clean base, audio stems, semantic layers, rights, path safety, atomic package,
  and returned-file revalidation have explicit gates.
- Normal workflow remains default-off and key/encryption-free.

## Open human decisions after implementation

1. Whether the Jianying import workflow is convenient enough to keep.
2. Which alpha candidate works reliably on the installed Desktop version.
3. Whether `balanced` or `max_editable` should be preferred per project.
4. Whether the modular outro/IP source package is useful enough to generate by
   default for HongRun projects.

These are canary decisions, not reasons to leave the design underspecified.

