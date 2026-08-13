# Migration and Rollback

Status: proposed; no migration code or project YAML change is authorized.

## 1. Schema decision

The later implementation should introduce additive project schema version 11.
Schema v11 does not rewrite user YAML during migration. The in-memory migrator
adds a disabled configuration block:

```yaml
motion_quality:
  portrait_brand:
    enabled: false
    profile_path: null
    grammar_version: 2
    style_direction: null
    require_user_brand_approval: true
    style_reel:
      enabled: false
      target_duration_seconds: 38
      directions:
        - luminous_intelligence
        - high_energy_creator
        - humanist_cinema
```

This is a design shape, not production configuration. Exact validation belongs
to the implementation phase.

## 2. Enablement rules

The compiler may enter portrait v2 only when all are true:

- config explicitly enables it;
- `identity.mode=self`;
- configured profile resolves to a current HongRun profile;
- content format is verified portrait talking head;
- required profile and source evidence is current;
- project is not a third-party identity project;
- the selected maturity is sufficient for the requested use.

Before production-default promotion, enablement remains project-specific. After
promotion, only new HongRun self-profile portrait projects may inherit the
profile default; migrated projects remain disabled unless explicitly opted in.

## 3. Compatibility

- Existing MQE-01–MQE-16 IDs and semantics do not change.
- PBM-01–PBM-08 are additive.
- Existing talking-head `expressive-v1` remains the fallback grammar while v2 is
  disabled or not eligible.
- Screen/product, mixed, generic, and third-party grammars remain unchanged.
- Existing Golden and validation receipts remain historical evidence; they
  cannot validate the new profile/recipe/version.
- Existing project YAML bytes are never rewritten just to add defaults.

## 4. Cache invalidation

| Changed input | Minimum invalidation |
|---|---|
| brand profile/version/direction | energy-dependent motion contracts, choreography, render evidence, audio plan, review, Golden |
| energy map | affected portrait contracts/events, audio, review, Golden |
| portrait recipe/version | affected events, renderer evidence, parity, review, Golden |
| face/hand/subject/mask evidence | dependent recipes, camera/crop/geometry evidence, review |
| Style Reel comparison basis | all three reels and review |
| sonic asset/profile/policy | sonic plan, audio evidence, reels, review |
| user correction | exact affected contract and all downstream hashes |
| renderer/browser/runtime | render manifest, keyframes, parity, reels, Golden comparison |

## 5. Rollback levels

1. **Event fallback:** select the recipe's declared simpler portrait treatment,
   quiet/caption, or action_required.
2. **Project fallback:** disable `portrait_brand`; resume existing talking-head
   v1 grammar without changing source/EDL/captions.
3. **Profile rollback:** select the previous approved profile version and create
   fresh downstream artifacts/review; never rewrite old evidence.
4. **Code rollback:** run the prior commit with original project YAML bytes. New
   additive artifacts are ignored, not deleted.

Rollback never mutates approvals or Golden receipts. It creates a new traceable
state and invalidates stale downstream claims.

## 6. Stop triggers

- user rejects all Style Reel directions;
- person primacy cannot be preserved on the chosen source;
- standard runtimes cannot produce visibly distinct high-quality structures;
- required effects depend on an unavailable/unauthorized paid or cloud service;
- correction time or rendering cost is disproportionate to reusable value;
- second-topic validation proves the language is overfit to one clip;
- any regression changes source preservation, captions, universal delivery, or
  third-party identity isolation.

On a stop trigger, keep the current stable workflow and return to the design
decision rather than lowering QA thresholds.

## 7. Recovery checkpoint

The implementation phase must record:

- objective path/hash and approved candidate path/hash;
- repository branch/HEAD/status;
- current profile and recipe versions;
- completed work package, tests, and media evidence;
- exact next command;
- known failure/rollback state.

No checkpoint authorizes a commit, push, full render, or publication beyond the
user's explicit instruction.
