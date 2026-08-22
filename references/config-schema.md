# Configuration Schema

Use versioned YAML and relative asset paths where practical. Resolve relative paths from the declaring file.

## Versioning and migration

The current project schema is version 13. New projects write both
`schema_version: 13` and `version: 13`. Legacy projects from v1 through v12 are
deep-copied and migrated in memory before
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

Require `identity.mode: self|third_party|generic` after in-memory migration.
Unknown legacy identity defaults to `generic`; the workspace path is never
identity evidence. A `third_party` Production Contract forbids HongRun assets,
personal intro/outro, and first-person brand expression.

Allow `workflow.input_mode: source_first` or `polish_existing`. Use `polish_existing` for already edited or published masters. In that mode, preserve the supplied timeline and require explicit reasons for replacing existing captions, BGM, cover, or cuts.

Allow `editing.caption_punctuation: spoken_clean`, `source`, or `none`. Default
to `spoken_clean`: punctuation still controls semantic sentence boundaries, but
displayed commas, full stops, semicolons, and colons are hidden; question and
exclamation marks remain when they carry spoken tone. `none` is an explicit
project choice and removes all displayed punctuation without changing word
timings or sentence segmentation.

Allow `editing.caption_delivery: auto` or `none`; migration defaults to `auto`.
`auto` requires output-timeline `video-use/master.srt` whenever the source lacks
an independently verified subtitle stream or burned-caption layer, including
`polish_existing`, and burns that exact hash-bound file during `final_compose`.
`none` is the only valid opt-out and must be recorded as
`disabled_by_project` in the composition plan.

`editing.caption_treatment` is optional and migration defaults it to:

```yaml
caption_treatment:
  enabled: false
  mode: plain
  font_family: Microsoft YaHei UI
  base_color: "#F7F8FA"
  accent_colors: ["#51E3C2", "#FFD166"]
  max_emphasis_terms_per_caption: 2
  max_scale_percent: 116
```

When explicitly enabled, `mode` must be `semantic_emphasis`, caption delivery
must not be `none`, colors must be one to three `#RRGGBB` tokens, the maximum
emphasis count is 1–2, and scale is an integer in 105–120. The Director requires
`captions.json` to match `master.srt` text, segmentation, and millisecond timing,
then writes ASS plus a source/semantic/config-bound plan for sample and full
scopes. Every highlighted anchor must be an exact member of the event's
`approved_visible_copy`. Completion deterministically rebuilds the canonical
full ASS from current project paths, config and measured canvas. When enabled,
plain-SRT delivery is rejected; when disabled, a styled ASS is rejected. It
still keeps `master.srt` as the authoritative
plain-text subtitle and burns the ASS last.
No configuration permits arbitrary rainbow rotation or per-character flashing.

The standard editable delivery is config-free and is produced for every
completed normal full render under `work/director/editable-delivery/`. It binds
the automatic master, the pre-caption full HyperFrames candidate, current
`master.srt`, deterministic ASS/style plan, and current HyperFrames project
inventory. This baseline does not enable manual finishing, create a native NLE
draft, or imply support in a particular editor. `caption_delivery: none` remains
an explicit caption-delivery override; normal `auto` delivery produces the full
repair kit.

`qa.platform_occlusion` keeps its legacy hard-collision behavior unless an
current semantic brief carries `occlusion_focus={primary: product, status:
approved}`, the rendered event carries the matching semantic ID and
`semantic_focus.primary=product`, and it has an explicit
`occlusion_policy.mode=semantic_priority` with `intent=product_emphasis`. In
that narrow window, at most one face/hand region may be soft-protected. The
event must declare finite maximum overlap, duration and product-gap bounds; the
actual semantic/Storyboard output window determines duration, and post-exit
geometry—not a self-reported boolean—proves the clean exit. The overlay must
target and remain near the product. Product, caption and platform-UI regions
are never softened.

## Audio

Allow project-level `audio.sfx` and `audio.bgm` settings. Recommended defaults:

- `sfx.enabled: true`, volume `0.2–0.35`, a default ceiling of 6 selected visual
  events per minute, and `max_event_ratio: 1.0` because the ratio applies only
  after the semantic planner has accepted an event;
- require a `cue` or `intentionally_silent` decision for 100% of non-quiet
  events; audible cue coverage is adaptive rather than globally forced and the
  perceptual mode defaults to a 0.35–0.65 corridor;
- `sfx.minimum_unique_asset_ratio: 0.8`,
  `maximum_family_ratio: 0.5`,
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

Set `editable_motion.profile` to `calm`, `balanced`, or `adaptive_dynamic`. The adaptive profile records legacy schema-v1/v2 advisory ranges (`screen_tutorial: [4,10]`, `polish_existing: [3,7]`) whose upper values are blocking ceilings, plus `maximum_visual_quiet_gap_seconds: 12`, `anchor_repeat_cooldown_seconds: 40`, and distinct semantic/layout/SFX checks. These numerical cadence/family checks do not gate the schema-v3 decision-complete model. Audio SFX accepts `max_cues_per_minute`, `max_event_ratio`, `target_event_coverage`, `minimum_unique_asset_ratio`, `minimum_cue_duration_seconds`, `maximum_family_ratio`, and `same_file_cooldown_seconds`. Different filenames or pitch transpositions do not excuse a family that exceeds the configured share. Require a decision for every selected event, but let perceptual evidence select an adaptive audible subset; silence is a deliberate decision rather than missing work. BGM remains independently optional.

For route-, branch-, dependency-, and flow-based visuals, add
`geometry_contract.connector_contract` with `required_connector_count`,
semantic `relations`, and attachment intent. The matching aesthetic review must
store observed count, endpoint attachment, optical alignment, clipping status,
and a real snapshot path.

For source-bound focus/highlight/callout/overlay visuals, add
`geometry_contract.target_region_contract`:

```yaml
tracking_mode: scene_bounded       # static | scene_bounded | keyframed
active_selector: "#sample-trends .chart-target"
required_target_count: 2
target_ids: [primary-chart, secondary-chart]
minimum_useful_content_ratio: 0.35
maximum_static_state_delta: 0.12
active_output_start: 64.8
active_output_end: 70.8
active_source_start: 85.7
active_source_end: 91.7
source_state_evidence:
  - {phase: entrance, timestamp_seconds: 85.8, path: "C:/.../entrance.png", sha256: "..."}
  - {phase: midpoint, timestamp_seconds: 88.7, path: "C:/.../midpoint.png", sha256: "..."}
  - {phase: pre_exit, timestamp_seconds: 91.6, path: "C:/.../pre-exit.png", sha256: "..."}
```

The active window may be narrower than the semantic event, but must remain
inside it. All three evidence phases are required and hash-bound. Static and
scene-bounded targets must remain visually stable within the configured delta;
keyframed targets require review evidence that their keyframes cover each state
change. Each `target_ids` value is also a real `data-hf-id` in the composition;
the generated motion sidecar checks every declared target individually.

The matching aesthetic review uses `browser_dom_geometry_v1` measurement
receipts. Connector rows store canvas dimensions, node bounding boxes, path
start/end points, declared attachment edges, clipping state, and endpoint
tolerance (maximum 8 px). Target rows store the active selector, midpoint phase,
target IDs, overlay boxes, and useful-content boxes. The Director recomputes
attachment distances and useful-content intersection ratios.

Each non-quiet event also supplies `composite_contrast` with hash-bound midpoint
and post-exit/source evidence, overlay box, foreground RGB, panel RGB, and panel
alpha. The Director simulates the panel over the real source crop and requires
at least 4.5:1 representative contrast.

## Analysis backends

Keep backend choice separate from editing policy:

- the built-in evidence sampler covers the complete duration with a 15-second
  target interval, at least three frames, and at most 32 frames; every managed
  frame records `timestamp_seconds`, an owned coverage interval, its hash, and
  the sampling policy. Managed count/timestamp mismatch fails closed; partial
  extraction cannot self-report full coverage. This is an implementation
  contract, not a project option. The 32-frame cap may enlarge intervals on long
  sources; a semantic event still needs a cited frame captured within 15 seconds,
  and the current built-in sampler does not automatically add supplemental frames;
- legacy caller-supplied frames without timestamps remain readable and are
  explicitly marked `legacy_unspecified` rather than claiming time coverage;
- Storyboard event strings are fail-closed: each must either equal approved
  visible copy or occupy an explicit non-visible metadata path. Only root-level
  `approved_visible_copy` and `visible_copy_manifest` are authoritative; nested
  copies and arbitrary custom string props are invalid. Final DOM/OCR review is
  still required because the JSON validator does not inspect rendered pixels;

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
    nle_package:
      enabled: false
      profile: jianying_desktop_compatible_v1
      level: balanced # reference_only | balanced | max_editable
      include:
        motion_layers: true
        ip_assets: true
        modular_outro: true
        event_sfx: true
    jianying_native_draft:
      enabled: false
      adapter: pyjianyingdraft_0_3
      profile: layered_reconstruction # repair_draft | layered_reconstruction
      asset_mode: linked # linked | portable
      install: false
      max_package_gib: 8.0
```

Keep the expanded layered package and human-return workflow disabled by default.
`enabled: false` or backend `none` still permits the config-free standard repair
kit but does not pause for a human return. `opencut` and `other_nle` mean only that
a human will use that finishing surface; they do not authorize or imply an API,
CLI, MCP, or headless integration. Resolve declared asset and return paths from
`paths.root`. The returned path must differ from the automatic master path.
Missing optional assets are legal and must be represented as `unavailable` in
the handoff manifest.

`nle_package.enabled: true` additionally builds the editor-neutral layered
package under `work/director/manual-finish/nle-package-v2/`. It copies only
current materialized assets, writes an EDL-authoritative zero-based timeline,
SRT/ASS-reference handoff, audio/media layer inventory, compatibility report,
and deterministic Jianying Desktop import guide. It never writes a Jianying
native draft and all `native_draft`, editor API/CLI, and headless-render claims
remain false. `balanced` requires a current clean A-roll and `master.srt`;
unmaterialized motion, IP, audio, cover, or outro layers stay explicitly
`unavailable`. Compatibility remains pending until the five-task named-user
Jianying Desktop canary is recorded.

Configured `ip_source`, `ip_rendered`, and `outro_*` records must be mappings
with `path`, `provenance`, `rights_status`, and a `rights_evidence` file reference.
The referenced `nle_asset_rights` receipt must bind the exact current asset
path/hash and authorize that precise role. A preview-pending modular outro may
package `outro_copy`, repeated `outro_icon`, and `outro_source_project`; it must
not claim `outro_overlay` or `outro_reference` before visual approval and
render/decode/parity evidence.
After approval, `outro_overlay` must be a text-free ProRes 4444 MOV with current
alpha/decode evidence and exact timeline placement. `outro_reference` must bind
the approved preview appearance. Both remain ordinary media assets rather than
native Jianying layers, and their role-specific rights receipts remain required.

With `include.motion_layers: true`, a current HyperFrames renderer payload, and
`--execute-external`, Director may render only the approved event windows as
transparent ProRes 4444 MOV candidates. Each event must retain its semantic and
renderer IDs, exact output-timeline offset, canvas, frame rate, decoded alpha
evidence, clean exit, and black/white/busy composite proofs. The package also
contains a deterministic ZIP of the retained HyperFrames project for deep edits.
This automated evidence does not prove that the installed Jianying version
imports or preserves alpha; the compatibility receipt remains pending until the
human canary. Without external execution or current renderer authority, the
motion roles remain `unavailable` rather than triggering a speculative render.

`jianying_native_draft.enabled: true` requires `manual_finish.enabled: true`,
backend `other_nle`, and `nle_package.enabled: true`. In schema v13 the Director
only compiles `jianying-draft-plan.json`, a Chinese status/usage guide, and a
target-free install proposal. The adapter remains default-off, does not launch
Jianying, does not read or write its draft store, and does not produce a real
native draft. `install` must remain `false`; unknown adapter/profile/asset mode,
non-finite size budgets, or extra secret-bearing fields fail validation. Real
materialization/installation requires exact-version compatibility and the WP5
short named-user canary before any real-project claim. The separately approved
WP4 installer is not configured by this block: it accepts only a validated
synthetic fixture, one fixed nonexistent target, and a marker-bound test store
inside the authorized project root. It cannot be switched to a real draft store.
`layered_reconstruction` preserves one base clip per EDL output range. Its clean
A-roll is already conformed, so native source-in equals the output start;
`repair_draft` instead uses one full-duration baked pre-caption candidate and
adds only editable captions plus a locked reference. `portable` is accepted as
an explicit plan mode, but WP0–WP3 synthetic fixtures do not claim a portable
real editor project or copy media into the Jianying draft store.

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

Director state keeps lifecycle `status` separate from production `readiness`.
Completed stages normally report `ready`; audio and cover may instead report
`contract_ready`, `asset_ready`, or `not_applicable`. A contract-ready stage is
not evidence that its media asset exists. `director.py next` reduces this state
to the single current owner, instruction, expected output, and resume command.

## Schema v11 identity, motion-quality opt-in, portrait brand, and required assets

Schema v11 retains the v10 defaults and adds a disabled portrait-brand block:

```yaml
identity:
  mode: generic
motion_quality:
  enabled: false
  advanced_runtimes:
    enabled: false
    evidence: {}
  portrait_brand:
    enabled: false
    profile_path: null
    grammar_version: 2
    style_direction: null
    require_user_brand_approval: true
    style_reel:
      enabled: false
      target_duration_seconds: 38.0
      directions:
        - luminous_intelligence
        - high_energy_creator
        - humanist_cinema
editing:
  caption_sync_closure: {enabled: false}
editorial_intent:
  enabled: false
  mode: neutral_education
extensions:
  optional_media_adapters: []
renderer:
  remotion: {enabled: false}
delivery:
  required_assets:
    captions: {stage: video_use_timeline, applicability: required, required_readiness: ready}
    audio: {stage: audio, applicability: optional, required_readiness: asset_ready}
    cover: {stage: cover, applicability: optional, required_readiness: asset_ready}
    identity: {stage: production_contract, applicability: required, required_readiness: ready}
    universal_video: {stage: final_compose, applicability: required, required_readiness: ready}
```

Enabling `motion_quality` opts semantic planning into schema v3
(`opportunity_model: decision_complete_v1`). Every opportunity must contain an
ordered source/output window, evidence, one editorial decision, and a rationale.
Only `render` decisions appear in the HyperFrames Storyboard, in the same relative
order. A render decision requires an explicit unique `approved_visible_copy`
string list; all non-render opportunities remain auditable in the brief. Fixed
cadence, minimum event/family counts, and family-ratio pass/fail gates are not
part of this model. `action_required` stops the semantic stage. With
`motion_quality.enabled=false`, existing schema-v1/v2 briefs and one-to-one
Storyboard behavior remain compatible.

`motion_quality.portrait_brand.enabled=true` is legal only with
`motion_quality.enabled=true`, `identity.mode=self`, a non-empty `profile_path`,
portrait grammar version 2, an explicit frozen `style_direction`, and a
verified or not-yet-classified talking-head source. An explicit non-talking-head
content type is rejected. The A/B/C direction list is exact and ordered; unknown
fields, cadence/quotas, random selectors, a disabled user gate, or a duration
outside 30–45 seconds are invalid. v1-v10 migration always writes this block as
disabled in memory even if a legacy mapping attempted to enable it, and never
changes the YAML bytes.

The repository-provided proposed HongRun profile is
`references/portrait-brand-profiles/hongrun-portrait-brand-v2.0.0.json`. It is
an opt-in `proposed` profile, not a user-approved or production-default style;
projects must reference it explicitly and the Style Reel gate may later promote
an exact profile version without mutating older project YAML.

Two current HongRun portrait topics exercise the exact v2.0.0
`luminous_intelligence` route and bind explicit named-user review, so that exact
opt-in route is `real_project_validated`. Product-first explanation windows may
authorize one bounded face-or-hand soft overlap only when the current semantic
brief, Storyboard, event window, product target, and post-exit geometry all
agree; product, caption, and platform-UI regions remain hard protected. The repository profile deliberately
remains `status: proposed`, migrated projects remain disabled, and no new project
inherits this route. `production_default` promotion is not implemented in this
release; it requires a separately designed trusted approval authority plus a
new HongRun decision bound to the current profile, implementation, and retained
real-project evidence.

When `style_reel.enabled=true`, planning is additive and isolated under
`work/director/style-reel/`; it does not insert a new automatic render stage.
The planner accepts only 30–45 seconds and the exact ordered direction list. It
writes a current `style-reel-authorities.json` alongside the frozen-schema plan
and includes current `audio-plan.json` and `portrait-sonic-plan.json` file
references for event-level audition receipts. Each receipt is recomputed from
decoded voice/off/on/cue PCM; the dashboard must display the exact receipt-bound
tracks. The full residual must match the planned cue window with silence outside
it, and the lexical project `assets/sfx` path must remain a non-linked child of
the project root.
so source, EDL, source/output transcripts, semantic brief, captions, voice stem,
audio policy, subject evidence and profile bytes can be revalidated instead of
trusting digest strings. The selected window must be fully covered by the
current video-use EDL; chapter macro treatment requires an independent typed
boundary mapped into that window. Render requests remain
`blocked_by_user_window_confirmation` until an explicit HongRun confirmation
receipt binds the exact plan, authority manifest and source/output window by
SHA-256, names
HyperFrames as owner, contain no executable command, and retain
`full_video_render_authorized: false`. Existing projects with the block disabled
never create these artifacts.

An implemented fixture review requires three distinct direction media files
with equal duration and exactly one video plus one audio stream with matching
codec, dimensions, frame rate, sample rate and channel count; one current
per-direction contract; and four current decodable
phase images for every semantic event. The context manifest additionally binds
a distinct aligned baseline, exact semantic sentences/copy/takeaways/rationales,
direction recipes, and required voice/SFX-off plus SFX-on auditions. A synthetic
fixture remains `pending` and is never eligible for a user decision; any
authority, plan, reel, contract, phase, report, baseline or audition drift
blocks the page. A real-project review may become `awaiting_user` only after the
later HyperFrames runtime, caption-last, voice/mix and parity gate. Only HongRun
may then select, revise, or reject through an explicit hash-bound decision receipt;
the fixture UI does not perform that write. A second-topic candidate records a
separate exact-thread repeat-use decision and may establish
`real_project_validated`; it cannot set `production_default`.

For the first real selection, the reviewed pending JSON remains immutable and
the WP6 package carries `awaiting_user`. The explicit decision receipt binds both.
The resulting profile snapshot may use `status: provisional_golden` only inside
the project-local WP7 evidence directory; the shared proposed profile and the
existing project YAML remain unchanged. A generated preference candidate is
pending, profile-versioned, explicit-only, non-auto-applying, and cannot enable
production default before the second-topic named-user gate.

When portrait-brand v2 and `audio.production.enabled` are both active, the
Director compiles the current portrait motion contracts through
`references/portrait-sonic-motifs-v2.json`. PBM-S01 through PBM-S05 each expose
at least two project-owned, rights-bound local synthesis variants for technical
Style Reel evaluation. The compiler writes `portrait-sonic-plan.json` and
`portrait-sonic-compile-report.json`; the plan also binds the exact generated
sonic-library manifest, its frozen registry and generator, and every nested
asset/rights hash. It then projects the exact event decisions
into the existing HyperFrames `audio-plan.json`; it does not create a second
mixer. `audio.sfx.enabled: false` produces one event-specific
`intentionally_silent` decision per portrait render event. Missing, stale, or
unlicensed variants also remain silent and truthful. Cue timing is bound to the
current output timeline: word <=80 ms, EDL-mapped gesture apex <=120 ms, and
chapter lead <=180 ms. The generated library is technically ready for Style
Reel audition only. The existing named-user answers preserve technical and reuse
evidence but do not establish current real-project maturity without the second
explicit visual review, while production-default status
remains false pending a separate explicit promotion. A legitimate audition may reduce the
compiled starting gain to protect speech, but the measured value and its
post-gain relation must match freshly decoded off/on evidence. Any cue-bearing
portrait sample, including a non-executing resume, also requires a current
full-sample mix output and hash-bound receipt.

When `motion_quality.enabled=true`, evidence acquisition writes
`work/director/evidence/adaptive-layout-constraints.json`. An optional
`source.content_type` may be `screen_tutorial` or `talking_head`; absent an
explicit value, portrait sources take the conservative talking-head route and
landscape sources take the screen-tutorial route. The contract records the
normalized display space, protected-region evidence, identity mode, and a safe
fallback. It does not manufacture coordinates when face/hand/critical-UI
evidence is missing.

Sample and full Storyboards then declare for every render event:

```yaml
target_binding_required: true
target_binding_ids: [binding-chart-primary]
```

Targetless typography or transition recipes declare `false` and `[]`. Binding
files live under separate `work/director/target-bindings/sample/` and `full/`
directories and follow the frozen `target-binding` schema. The Director checks
the binding ID/filename, semantic parent, source/output window, resolved status,
active window, observations, state changes, evidence paths and SHA-256 values.
This capability is `fixture_validated`; real-project promotion waits for both
the landscape and portrait canaries and user review.

The same opt-in activates the Director-owned Motion Quality Engine. Its recipe
registry is fixed at `references/motion-recipes-v1.json`; projects do not supply
random weights, keyword maps, cadence targets, family quotas, or SFX-based
selection. A render opportunity may provide a supported `semantic_role` and a
structured `form` such as `semantic_mark`, `ui_focus`, `compare`, `process`,
`relation`, `metric_proof`, `product_lens`, `chapter_bridge`, `kinetic_phrase`,
`evidence_pip`, `ip_vignette`, `architecture`, or `depth_stage`. Preconditions
are evaluated against current evidence, identity, adaptive layout, target
bindings, and `motion_quality.advanced_runtimes.enabled`. A failed precondition
uses the recipe's declared deterministic fallback; an exhausted chain becomes
`action_required`. The compiler writes separate sample/full contracts inside
`work/director/motion-design/` without rewriting `project.yaml`.

The compiler selects a format grammar from source evidence. `screen_tutorial`
uses verified source targets and product-explainer structures. `talking_head`
uses face-safe expressive typography, word emphasis, side rails, light/depth
accents, semantic cutaways, and chapter transitions, while rejecting detached
dashboard cards. Neither grammar introduces a fixed cadence or random rotation.
The portrait grammar remains fixture-validated until a future real candidate
passes both technical review and the separate user brand-taste gate.

Advanced runtimes require six absolute file/hash evidence records under
`motion_quality.advanced_runtimes.evidence`: `seek_safe`,
`deterministic_2d_fallback`, `preview_render_parity`, `device_support`, `license`,
and `cost`. Every record must be current and pass where applicable. Its bound
proof artifact is parsed by kind: seek samples and error bounds, a decodable 2D
fallback, decodable byte-matching parity frames, an exact passing device list,
a non-empty hash-bound license document, or finite cost calculation inputs.
Hash-bound arbitrary bytes and self-declared `pass` fields are not evidence.
Missing or stale evidence selects the declared deterministic 2D fallback rather
than an advanced recipe.

P1 opt-ins are `editing.caption_sync_closure.enabled`,
`audio.sfx.perceptual.enabled`, `editorial_intent.enabled`, and
`editorial_regression.enabled`. They respectively bind delivered caption timing,
per-event audio decisions and actual mix identity/audibility, a shared proof
ledger across hook/title/cover/description/CTA/motion copy, and Current Golden
schema v2 runtime fingerprints. Golden v2 hashes normalized DOM, motion,
geometry, cropped overlay perceptual evidence, and sample audio contracts; a
full comparison never reuses a sample audio manifest as full-timeline proof.

P2 adapters remain default off. Remotion requires `react_components`,
`parity_evidence`, and `license_evidence` as absolute path/SHA-256 records;
legacy path strings and boolean parity are rejected. Each parity event binds a
decodable reference and rendered image, and the Director recomputes image delta
within the strict tolerance. A no-audio measurement is valid only when the
event/component/hash-bound component manifest declares a `visual_only` output
with `audio_policy: forbidden`; otherwise it requires hash-bound byte-identical
reference/render audio evidence. An unmeasured numeric zero is rejected.
Optional media adapters
live in `extensions.optional_media_adapters`; enabling one without a real
provider result creates `action_required`. A manual NLE handoff may add a typed,
EDL-hash-bound package, but still claims no OpenCut/Jianying API or headless
rendering.

It also activates strict project-side HyperFrames render evidence. No additional
project YAML keys are required. The Director derives the following paths for
sample and full scopes independently:

```text
<hyperframes-project>/renderer-evidence-contract.json
<hyperframes-project>/renderer-project-manifest.json
<hyperframes-project>/renderer-export.json
<hyperframes-project>/keyframe-receipts/<event-id>.json
<project>/sample-qa|full-qa/preview-render-parity.json
```

Build the manifest only after the editable project source is final. It contains
the absolute project root, sorted relative source inventory, sizes, hashes, and
an integrity hash; runtime snapshots, receipts, renderer export, render output,
and cache folders are excluded. Any later source edit or addition makes the
manifest stale. The actual project runtime, not a Director request file, must
export painted visible text, the unique DOM selectors owned by each event root,
and four-phase DOM/geometry measurements for every compiled event. HyperFrames
keyframe diagnostics must match both the event window and one of those owned
selectors; an unrelated tween at the same time does not count. The receipt
phase sequence is `entrance`, `mid`, `pre_exit`, `post_exit`; the snapshot plan's
historical `midpoint` output maps to `mid`.

The generated renderer-evidence request contains the absolute runtime-capture
script and scope-specific arguments for project, Storyboard, motion contract,
project manifest, target-binding directory, output, and runtime snapshots. The
script requires the Python Playwright package and resolves its executable with
`npx hyperframes browser path`; no project YAML browser path is needed. It opens
only local project assets, verifies actual media seek state, and fails as
`action_required` when execution is unavailable. The logical `animation_map`
receipt is generated from `npx hyperframes keyframes <project> --json`; there is
no claimed upstream `animation-map` command.
The same request includes a receipt-builder script and scope-specific arguments.
It runs only after the configured parity artifact exists, binds strict-check and
keyframe diagnostics to the current project/contract/export hashes, and writes
the event receipts into the derived keyframe-receipt directory.

Project-level parity tolerances come from `qa.preview_render_parity`; composite
contrast must remain at least 4.5:1. A receipt may tighten but not relax these
limits. Missing or invalid runtime export, any absent event or phase, stale
hashes, or parity failure becomes `action_required`. These artifacts are
currently `fixture_validated`; they do not by themselves promote a project to
`real_project_validated`.

The same opt-in also requires a paired creative review before preview approval.
No additional project key is required. The Director derives:

```text
<project>/edit/video-use/base-preview.mp4
<sample-hyperframes-project>/sample-preview.mp4
<project>/work/director/review-media/candidate-with-sfx.mp4  # only when cues exist
<project>/work/director/sample-qa/sample-review-mix.json     # hash-bound mix receipt
<project>/work/director/sample-qa/review-audio/<event-id>-sfx-off|on.<audio>
<project>/work/director/sample-qa/review-audio/<event-id>-bgm-off|on.<audio>  # optional pair
<project>/work/director/sample-qa/mix-audibility.json
<project>/work/director/sample-qa/creative-review.json
<project>/work/director/review/creative-review.html
```

Both media files must be distinct, aligned continuous 60–90 second samples. The
review remains pending until a named human records publish willingness and a
baseline/candidate/tie preference plus a non-empty reason. Any bound hash drift resets approval.
When one or more SFX decisions are `cue`, the review candidate is the complete
`work/director/review-media/candidate-with-sfx.mp4`, not the raw HyperFrames
render. Its receipt must
match the current audio-plan cue order, event IDs, absolute asset paths, SHA-256
values, output bytes, FFmpeg mix command, and full decode. Plans containing only
`intentionally_silent` decisions keep `sample-preview.mp4`. Required captions
are applied to the chosen candidate afterward so subtitle delivery remains last.

`editing.caption_delivery: none` changes only the caption asset to an evidenced
`not_applicable` rule. Mandatory caption, identity, and universal-video policies
cannot be rebound or weakened. Optional audio/cover may be promoted to required
per project, but `contract_ready` never satisfies a required `asset_ready`
policy. Enabling `delivery.release_pack` makes the cover effectively required
because that publish package cannot be complete without it. Migration does not
rewrite `project.yaml`.

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

Interactive review serves only a loopback proposal API. When explicitly enabled,
Director creates short-lived in-memory authorization and CSRF nonces and embeds
them only in that generated local review session; users configure no keys. The
server permits `Origin: null` only for this explicitly enabled mode, only for the
proposal endpoint, and still enforces project containment and current SHA-256.

Only loopback review hosts are valid. Booleans must be real booleans; ports,
body limits, sample counts, and view counts are positive integers. Thresholds
must be finite and bounded. Unknown future schemas are rejected, and migration
never rewrites `project.yaml`.
Audit- and release-pack output directories must resolve to dedicated descendants
of `paths.root`; the project root itself and external absolute directories are
rejected. When `delivery.release_pack.enabled` is true, privacy review, exact
video/cover/copy rights coverage, and separate publication authorization remain
mandatory and cannot be disabled by the three `require_*` flags.
The same setting promotes cover readiness to a blocking delivery requirement;
with release packaging disabled, an absent optional cover is recorded as
`optional_unavailable` and platform reports validate the universal MP4 without
inventing cover-crop evidence.
