# WP5 project-local generation amendment

Status: explicitly approved by HongRun on 2026-08-22. The exact decision is
retained in `wp5-project-local-generation-decision.json`.

This amendment supersedes only the real-project installation portions of the
frozen WP5 canary. It does not alter the canonical timeline, track, rights,
fallback, compatibility, human-review or production-default contracts.

## Current boundary

- Generate one new `native-draft/` candidate below the current video project's
  own output root. The unpublished tree is a hidden direct child of
  `published/`, beside its final target; the existing `staging/` directory is
  retained for plan-only compatibility but is not the real adapter write root.
- The generation API does not accept or discover a Jianying APP draft-store
  path and does not read, write, enumerate or modify any APP draft.
- Emit a detailed Chinese guide. The user finds the current location in their
  Jianying settings and manually copies the whole candidate folder as a new
  child. Same-name targets must not be merged or overwritten.
- Project-local automated validation promotes only to
  `generated_awaiting_manual_canary`. Opening, five edits, export and usability
  remain honest human evidence gates on the exact editor version.
- The adapter subprocess uses the exact approved project virtual-environment
  interpreter and `pyvenv.cfg` hashes, recorded Python version/architecture,
  Python `-I -S`, a controlled project-local working directory and a reduced
  environment without `PYTHONPATH`/`PYTHONHOME` or credential variables. It
  loads the adapter and all six transitive dependencies only from the exact
  offline wheel names and SHA-256 values in `jianying_native_adapter_lock.py`;
  project `site-packages` and `.pth` files are not loaded.
  Windows network blocking is not enforced by this implementation, so receipts
  record network-use evidence as `unknown` rather than claiming `false`.
- The host holds a no-share-delete handle on the project output root and the
  unpublished candidate throughout third-party execution. It promotes that
  same candidate through `SetFileInformationByHandle`, so the source path is
  never reopened during publication. The validator similarly pins the package
  parent and package identity before its first manifest read.
- Before `CreateProcess`, the host pins the approved virtual-environment root,
  `Scripts/`, interpreter and `pyvenv.cfg` through the complete subprocess run.
  The parent also pins the complete no-reparse chain and file handle for every
  adapter wheel and media source until the child exits; the isolated runner
  requires that receipt and independently rechecks path identities and hashes.
- The host pins the runner, adapter lock module and dependency-free locked-I/O
  module, plus their common parent, before `CreateProcess`. Their hashes are
  bound through request, projection report, candidate manifest and validator.
- The orchestrator supplies and requests no APP draft-store path. Third-party
  process file access is not OS-audited, so its actual APP-store access evidence
  remains `unknown`; documentation must not turn that unknown into a false
  system-wide claim.
- After candidate validation, the project-local CLI may refresh the Director
  status and manual-copy handoff with the candidate manifest/root. It still
  accepts no Jianying APP draft-store path.
- Linked native drafts contain absolute local media paths. The manifest marks
  them local/private and the Chinese guide forbids uploading or sharing the
  candidate directory as-is.
- WP4's marker-bound synthetic install/rollback implementation remains retained
  as historical isolation evidence and is not called by this route.
