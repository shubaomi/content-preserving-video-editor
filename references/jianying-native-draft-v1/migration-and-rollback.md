# Migration and rollback

## Additive configuration

Future implementation adds an optional block equivalent to:

```yaml
delivery:
  manual_finish:
    jianying_native_draft:
      enabled: false
      adapter: pyjianyingdraft_0_3
      profile: layered_reconstruction
      asset_mode: linked
      install: false
      max_package_gib: 8
```

Legacy and migrated projects receive `enabled: false` in memory. No existing
project YAML is rewritten solely to add defaults. Enabling native draft does not
implicitly enable full rendering, manual return, editor installation, or UI
automation.

## Build rollback

- Failure before atomic promotion removes only the current staging directory.
- A prior published build remains byte-for-byte unchanged.
- Rebuilding creates a new build ID; it never mutates a prior package.
- Drift in canonical authorities invalidates the build and install proposal.

## Install rollback

- Installation is outside v1 implementation until separately authorized.
- It may create only one new draft directory after proving the target absent.
- The install receipt inventories every created byte and the pre-install parent
  state.
- Automated rollback is permitted only when the target still exactly matches
  that inventory; otherwise it becomes a manual action to protect user work.
- Existing drafts are never rollback targets.

## Capability fallback

Any adapter, editor-version, alpha, range-style, media-path or parity failure
leaves the automatic master, standard editable delivery and `nle-package-v2`
available. Native failure is `unavailable`/`action_required`, not a failure of
the automatic delivery.

