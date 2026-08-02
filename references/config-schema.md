# Configuration Schema

Use versioned YAML and relative asset paths where practical. Resolve relative paths from the declaring file.

## Versioning and migration

The current project schema is version 9. New projects write both
`schema_version: 9` and `version: 9`. Legacy projects that only contain
`version: 1` or `version: 2` are deep-copied and migrated in memory before
validation or execution. Migration adds defaults but never rewrites the user's
existing `project.yaml`. Reject unknown future versions rather than guessing.
Schema versions must be real integers, not booleans or numeric strings. Audio
normalization targets must be finite numeric values; boolean, NaN, and infinite
LUFS/true-peak/LRA values are rejected before execution.

## Profile

Require `version`, `profile_id`, `paths.root`, and `paths.videos`. Optionally declare shared character, generated assets, intro, outro, motion presets, audio, fonts, and HyperFrames templates.

Allow `character.main_anchor`, `spec_board`, `action_sheet`, `avatar`, `identity`, and `status`. Treat a status beginning with `confirmed` as approved provenance; reject identity-sensitive generation when files are missing or status is unconfirmed.
When `main_anchor`, `spec_board`, or `action_sheet` is declared, resolve it from `paths.root` and require the file to exist before generation.

## Project

Require `schema_version`, `version`, `video_id`, `paths.root`, `paths.source`, `paths.edit`, `paths.hyperframes`, `paths.work`, `paths.exports`, `source.primary_video`, and `editing.mode` for new projects. Legacy projects may omit `schema_version` and receive it in memory.

Accept only `preserve`, `balanced`, or `tight`. Default to `preserve`. Resolve `profile` relative to `project.yaml`; resolve media relative to `paths.root`.

Allow `profile: null` for generic videos and skip IP-specific steps.

Allow `workflow.input_mode: source_first` or `polish_existing`. Use `polish_existing` for already edited or published masters. In that mode, preserve the supplied timeline and require explicit reasons for replacing existing captions, BGM, cover, or cuts.

Allow `editing.caption_punctuation: spoken_clean`, `source`, or `none`. Default
to `spoken_clean`: punctuation still controls semantic sentence boundaries, but
displayed commas, full stops, semicolons, and colons are hidden; question and
exclamation marks remain when they carry spoken tone. `none` is an explicit
project choice and removes all displayed punctuation without changing word
timings or sentence segmentation.

## Audio

Allow project-level `audio.sfx` and `audio.bgm` settings. Recommended defaults:

- `sfx.enabled: true`, volume `0.2–0.35`, a default ceiling of 6 selected visual
  events per minute, and `max_event_ratio: 1.0` because the ratio applies only
  after the semantic planner has accepted an event;
- `sfx.target_event_coverage: 1.0`; require a cue decision for every non-quiet
  event, with `intentionally_silent` reserved for evidenced exceptions;
- `sfx.minimum_unique_asset_ratio: 0.8`,
  `minimum_cue_duration_seconds: 0.8`,
  `minimum_post_gain_mean_dbfs: -34`, and
  `maximum_post_gain_mean_dbfs: -18`;
- `bgm.enabled_by_default: true`, `optional: true`, preview volume `0.08–0.12` for speech video;
- `bgm.asset: null` until the director's licensed-media resolver selects a local file;
- `bgm.ducking.enabled: true`, with provider and parameters recorded;
- `bgm.provider_chain`: ordered adapter mappings for media-use/HeyGen, MiniMax,
  and local MusicGen after an approved local asset. Each provider declares
  `name`, `enabled`, command/output, and paid-call authorization when applicable;
- `bgm.stop_after_first_success: true` to avoid unnecessary quota use;
- original speech always has priority.

Set `audio.production.enabled: true` to execute SFX/BGM production. Set
`audio.normalization.enabled: true` to enable the hash-bound two-pass final
normalizer; optional numeric keys are `target_lufs` (default `-14`),
`true_peak_dbtp` (default `-1.5`), and `lra` (default `11`). Both features are
disabled by in-memory migration for legacy projects. The normalizer accepts the
post-measurement only within 1 LU of integrated loudness, no more than 0.1 dB
above the configured true-peak target, and no more than 1 LU above configured
LRA. Final composition reuses an intermediate only when its input/parameter
signature and current file hash both match.

`source.has_existing_bgm` is a declaration, not presence evidence. An
`embedded_source` plan must include measured presence analysis. A configured
authorized asset that is enabled by default may be disabled only by an explicit
project/user decision; otherwise final composition mixes it with
`sidechaincompress`.

Missing BGM must not fail the video. A missing or unmatched SFX cue for a
selected non-quiet event is blocking unless that event has an evidenced
`intentionally_silent` decision.

## Editable motion

Declare or document separate selectors for `layout_host`, `motion_wrapper`, and `editable_surface`. Studio edits belong to the layout host or editable surface. Animation timelines may transform only the motion wrapper.

Set `editable_motion.profile` to `calm`, `balanced`, or `adaptive_dynamic`. The adaptive profile records advisory ranges (`screen_tutorial: [4,10]`, `polish_existing: [3,7]`) whose upper values are blocking ceilings, plus `maximum_visual_quiet_gap_seconds: 12`, `anchor_repeat_cooldown_seconds: 40`, and distinct semantic/layout/SFX checks. Audio SFX accepts `max_cues_per_minute`, `max_event_ratio`, `target_event_coverage`, `minimum_unique_asset_ratio`, `minimum_cue_duration_seconds`, and `same_file_cooldown_seconds`. Default cue coverage to every selected non-quiet event; reduce event count at the semantic planner instead of leaving approved motion silent. BGM remains independently optional.

For route-, branch-, dependency-, and flow-based visuals, add
`geometry_contract.connector_contract` with `required_connector_count`,
semantic `relations`, and attachment intent. The matching aesthetic review must
store observed count, endpoint attachment, optical alignment, clipping status,
and a real snapshot path.

## Analysis backends

Keep backend choice separate from editing policy:

- `transcription.preferred: local_faster_whisper`;
- `transcription.optional: [funclip_funasr]` when Chinese hotwords, speakers, or text-selected candidates are valuable;
- `cut_candidates.auto_editor.analysis_only: true` when silence, motion, loudness, or subtitle evidence is useful;
- `nle.video_use: conditional` for complex timeline and boundary work.

No backend may approve semantic deletion. Store candidate ranges separately from the approved EDL.

Optional adapters use these canonical paths and default to disabled:

- `analysis.adapters.pyscenedetect`, `.mediapipe`, and `.paddleocr`;
- `analysis.subject_tracking` and `analysis.hook_pacing`;
- `transcription.router`, including backend availability/commands;
- `timeline.otio` and `render.cache`;
- `assets.media_catalog`;
- `extensions.b_roll`, `.multicam`, `.voice_isolation`, and `.localization`;
- `renderer.remotion`, `preferences`, `publishing.copy`, and
  `feedback.metrics_import`.

An enabled command adapter declares `command`, `outputs`, optional
`timeout_seconds`, and `required`. `required: true` converts unavailable or
failed execution into `action_required`; otherwise the report records the
truthful fallback and the core path continues.

An enabled `assets.media_catalog` command must include a
`{request_manifest}` placeholder, for example:

```yaml
assets:
  media_catalog:
    enabled: true
    command: [python, tools/catalog_adapter.py, "{request_manifest}"]
    outputs: [edit/assets/catalog-results.json]
    required: false
```

The Director replaces the placeholder with an absolute, hash-bound JSON request
manifest. The compatibility alias `assets.use_media_catalog: true` still enables
this route for legacy configuration, without rewriting the project file.

## Schema-v8 production governance (retained in schema v9)

Schema v8 adds these non-destructive defaults. Migration deep-copies the source
mapping and never rewrites the user's YAML:

- `workflow.production_contract.enabled: true` for a hash-bound preservation, dynamics,
  audio, cover, provider, and derived-output contract;
- `provider_governance.enabled: true`, with per-task configured candidates,
  explicit authorization/quota/availability, weighted selection evidence, a
  project budget cap, estimates, reservations, and reconciled actual cost;
- `assets.local_semantic_corpus.enabled: false`; the deterministic local index
  stores rights, source hash, embedding model/version/cache key, semantic score,
  motion score, and event binding. An unavailable CLIP/backend is reported and
  never downloaded implicitly;
- `brand.motion_playbook.enabled: true`, compiling project/profile tokens to
  JSON, CSS custom properties, and `DESIGN.md`;
- `qa.visual_dynamics.enabled: true` for sample/full/delivery hash-bound cadence,
  variety, quiet-interval, geometry, occlusion, connector, IP, SFX, and canvas
  checks;
- `editorial_regression.enabled: false` until an approved sample establishes
  a Golden Editorial baseline;
- `review.dashboard.enabled: true` for a static local read-only review page;
- `derived_content.clip_factory`, `.podcast`, and `.localization`, all disabled
  by default and constrained to existing transcript/EDL/contract evidence;
- `delivery.openmontage_handoff.enabled: false`, a human-only neutral package
  that reuses correction-ledger and returned-media revalidation contracts.

Provider candidates must not be selected merely because a name appears in YAML.
Availability, paid-call authorization, remaining quota, current evidence timestamp,
privacy/locality, latency, continuity/cache value, cost, Chinese suitability,
identity preservation, and task quality all participate in the recorded
decision. A reservation is not actual spend: adapters must reconcile it after
success or failure. Exceeding the project cap produces `action_required`.
Every external callback requires a current selected provider for its exact task.
The cost ledger remains auditable across resume by atomically refreshing its
Director stage artifact receipt after each valid reserve/reconcile transition.
Any positive `incremental_cost` is treated as paid and therefore requires current
authorization, price, and quota evidence. A success row also requires a separate
provider-result receipt; its declared absolute output paths and SHA-256 values are
recomputed. A still-reserved call is never retried automatically.
`provider_governance.max_evidence_age_days` defaults to 30; paid pricing and
quota timestamps older than that window, missing timezone information, or more
than five minutes in the future are rejected as stale evidence.

Treat `requires_paid_call: true` or any positive `incremental_cost` as paid.
For such a candidate, require explicit `paid_call_authorized`,
`verified_pricing_basis: true`, `pricing_source` equal
to `user_plan` or `user_contract`, a user-plan `cost_basis`, incremental cost,
positive remaining quota, pricing/quota evidence timestamps, an
`actual_cost_strategy`, and evidenced failure cost. Supported reconciliation
strategies are `fixed`, `result_field`, and `local_runtime`. The Director reserves
only at the real adapter boundary and final delivery rejects any unresolved
reservation.

`assets.local_semantic_corpus.backend: precomputed` is the no-download production
route: each authorized asset supplies a finite local embedding and the config
supplies same-model `query_embeddings` for requested queries. `fixture` is tests
only. A configured `clip` or `command` backend that is not actually available
returns `unavailable`; it never triggers an implicit model download. Enabling the
local corpus is sufficient to route media requests even when the external media
catalog is disabled.

The podcast module currently accepts a real signed 16-bit PCM WAV clean-audio
asset and verifies decode, duration, sample rate, channels, RMS, and peak. The
localization module accepts an authorized `result_file` whose provider identity,
language, current hash, transcript hash, glossary hash, complete word IDs,
translations, and back-translations
validate. The Director requires the selected translation provider and a prior
cost reservation before adopting that file. Missing translation, TTS, lip-sync,
or voice-clone authorization remains `action_required`. Tests may
use deterministic fixtures, but production reports must never label fixture
output as external-provider completion.

## Topic IP visuals

- `visuals.ip_opportunity_audit_required: true`;
- `visuals.theme_asset_mode: content_specific`;
- `visuals.character_reference_only: true`;
- `visuals.generated_asset_root: edit/assets/ip-generated`.
- `visuals.mid_video_ip_mode: conditional`;
- `visuals.outro_ip_mode: branded_topic_variant`.

The opportunity score guides review; it is not a forced image quota.

For generated topic visuals, allow:

- `visuals.semantic_dedup_required: true`;
- `visuals.default_integration_mode: pip-card`;
- `visuals.full_canvas_only_for_chapter_bridge: true`;
- `visuals.match_design_tokens: true`;
- `visuals.prefer_transparent_or_scene_matched_background: true`;
- `audio.one_transient_per_visual_beat: true`.

## Delivery and cover

Recommended defaults:

- `delivery.mode: autonomous_pre_publish` when the user asks for one-shot completion;
- `delivery.max_automatic_repairs: 2`;
- `delivery.render_after_automated_qa: true` in autonomous mode;
- `cover.enabled: true`;
- `cover.identity_mode: authorized_real_photo`;
- `cover.style: cinematic_movie_poster`;
- `layout.orientation: auto_from_display_metadata`;
- `layout.preserve_source_orientation: true`;
- `layout.standard_canvas: auto` (`9:16`, `16:9`, or `1:1` after inspection);
- `visuals.generated_aspect_ratio: match_video_canvas`;
- `cover.aspect_ratio: 9:16` for Douyin and WeChat Channels, independent of video orientation;
- `cover.hand_drawn_ip: optional`.
- `cover.preserve_original_face_pixels: false` for the default reference-guided
  regenerated-person workflow; literal source-pixel compositing is fallback only;
- `cover.generate_background_separately: true`;
- `cover.identity_qa_before_aesthetic_qa: true`.

Enhanced editorial covers use:

```yaml
cover:
  production:
    enabled: true
  editorial:
    enabled: true
    mode: auto # auto | reference_regenerated | authentic_frame_editorial | real_person_ip_hybrid
    prefer_authentic_frame: false
    headline_max_characters: 26
    headline_max_lines: 3
    template_families:
      - cinematic_editorial
      - bright_tech_tutorial
      - dark_high_energy
      - thought_leadership_ip
    authentic_frames: []
    supporting_assets: []
```

Each supporting asset entry accepts `path`, `role`, `purpose`, and
`rights_basis`. Use `role: personal_ip` only for the user's confirmed personal
IP asset. Version-1 through version-6 projects receive
`cover.editorial.enabled: false` in memory, so the legacy cover path is not
silently redesigned. Newly initialized projects enable the editorial planner
but leave external cover production disabled until explicitly requested.

The optional human-finishing configuration is:

```yaml
delivery:
  manual_finish:
    enabled: false
    backend: none # none | opencut | other_nle
    returned_final: null
    modifications: []
    assets:
      clean_a_roll: null
      captions: null
      transparent_motion_layer: null
      bgm_stem: null
      sfx_stems: []
      cover: null
```

Keep it disabled by default. `enabled: false` or backend `none` leaves the
automatic one-shot workflow unchanged. `opencut` and `other_nle` mean only that
a human will use that finishing surface; they do not authorize or imply an API,
CLI, MCP, or headless integration. Resolve declared asset and return paths from
`paths.root`. The returned path must differ from the automatic master path.
Missing optional assets are legal and must be represented as `unavailable` in
the handoff manifest.

An OpenMontage-oriented handoff may alternatively set:

```yaml
delivery:
  openmontage_handoff:
    enabled: true
    returned_final: null
    modifications: []
```

This produces an editor-neutral package and `action_required`; it does not call
OpenMontage, depend on it, or claim an API, MCP, CLI, or headless renderer.
Do not enable `manual_finish` and `openmontage_handoff` together; schema v9
rejects that ambiguous double handoff.

Configure the blocking Studio/render parity tolerance as follows:

```yaml
qa:
  preview_render_parity:
    tolerances:
      position_px: 4.0
      size_px: 4.0
      time_seconds: 0.05
```

These values are migration defaults and project-level maximums. A parity report
may use stricter values but cannot relax them.

Rendering permission does not authorize uploading or publishing. External publication remains a separate hard gate.

## Schema v9 optional capabilities

These blocks default off and are added only in memory for legacy projects:

```yaml
analysis:
  semantic_confidence:
    enabled: false
    low_confidence_threshold: 0.7
    second_provider: {enabled: false}
render:
  cache:
    enabled: false
    event_level: {enabled: false, fallback_to_full_render: true}
review:
  interactive:
    enabled: false
    host: 127.0.0.1
    port: 8765
    max_body_bytes: 65536
cover:
  reference_pack:
    enabled: false
    manifest: null
    required_roles: [front, smiling, explaining]
preferences:
  learning:
    enabled: false
    minimum_samples: 2
    default_scope: video
feedback:
  learning_loop:
    enabled: false
    minimum_snapshots: 2
    minimum_views: 200
    minimum_elapsed_hours: 24.0
delivery:
  audit_bundle:
    enabled: false
    output_dir: work/director/portable-audit-bundle
  release_pack:
    enabled: false
    privacy_manifest: null
    rights_manifest: null
    publication_authorization: null
    output_dir: exports/release-pack
    require_privacy_audit: true
    require_rights_authorization: true
    require_publication_authorization: true
```

Only loopback review hosts are valid. Booleans must be real booleans; ports,
body limits, sample counts, and view counts are positive integers. Thresholds
must be finite and bounded. Unknown future schemas are rejected, and migration
never rewrites `project.yaml`.
Audit- and release-pack output directories must resolve to dedicated descendants
of `paths.root`; the project root itself and external absolute directories are
rejected. When `delivery.release_pack.enabled` is true, privacy review, exact
video/cover/copy rights coverage, and separate publication authorization remain
mandatory and cannot be disabled by the three `require_*` flags.
