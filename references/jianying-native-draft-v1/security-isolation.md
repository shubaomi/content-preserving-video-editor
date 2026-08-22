# Security and isolation contract

## Trust boundary

Jianying draft files and third-party adapters are untrusted local inputs/tools.
The stable workflow must not execute embedded commands, import an arbitrary
draft, or trust self-reported success.

## Required controls

- Generate from typed Director-owned JSON only; never pass free-form shell text.
- Pin dependency version, distribution hash and license; install only in an
  isolated project environment after explicit implementation approval.
- Use argv subprocess calls with fixed executable paths and controlled cwd.
- Disable network access during deterministic generation where tooling permits.
- Never transmit media, draft contents, device identifiers or account data.
- Keep all writes under a lexical authorized project root; reject traversal,
  symlink and Windows Junction/reparse-point redirection before mkdir/write.
- Stage every file, fsync where applicable, validate, then atomically promote.
- Reject extra files, absolute home paths outside approved asset roots, device
  IDs, MAC addresses, account IDs, cookies, tokens and cloud identifiers.
- Never clone or sanitize an existing user draft as the template for a new one.
- Do not read Jianying databases, caches, cloud sync folders or current drafts.
- The install step requires a nonexistent target and a separate receipt; it
  cannot overwrite, merge or repair an existing draft.

## Third-party-specific boundary

Community tools are evidence candidates, not authorities. Historical security
or privacy fixes require a minimum safe-version rule, but “latest” is not an
allowed unpinned dependency. A writer and a validator must not share one
self-reported `pass`; Director re-parses the complete output inventory.

## Secret policy

No HMAC key, API key, Jianying account, login cookie or cloud token is part of
this feature. Local SHA-256 values detect drift only; they do not authenticate a
human identity. Named-user canary approval remains an explicit application-level
decision bound to current evidence.

