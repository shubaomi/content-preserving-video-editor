# Risk and cost ledger

| Risk | Impact | Frozen mitigation | Residual owner |
|---|---|---|---|
| Private draft format changes | Draft will not open or fields drift | Exact tuple, default-off, fail closed, neutral fallback | Adapter maintainer |
| Community dependency compromise | Local code/data exposure | Pin hash/license, isolate, no network, security review | Director/security review |
| Existing draft damage | User loses work | No read/merge/overwrite; new target only; separate install gate | Director |
| Device/account metadata leak | Privacy breach | Fresh draft only, field/path scan, no user template cloning | Director |
| Caption style flattening | Manual result differs | Typed fidelity and ASS fallback; named canary | Caption adapter/HongRun |
| Alpha incompatibility | Motion becomes opaque | Exact codec evidence and current-version import canary | HyperFrames/HongRun |
| Layer duplication | Motion/audio appears twice | Profile-specific base contract and reconstruction parity | Adapter |
| Relink friction | Draft is technically valid but unusable | Linked/portable modes and timed five-task canary | HongRun |
| Storage growth | Large duplicate packages | Size estimate/budget; linked default; no extra render | Director |
| False compatibility claim | User trusts unverified draft | Maturity gates and exact version receipt | Director |
| Overcomplex v1 | Delayed delivery and more bugs | Exclude proprietary effects/UI automation/merge | Product owner |

## Cost boundary

Design and validation are local. No paid provider, cloud upload, login or key is
required. Implementation cost is dominated by version-specific fixture upkeep,
Windows safety testing and real Jianying canaries. This is justified only if the
five manual edits are materially faster than using the current neutral package.

