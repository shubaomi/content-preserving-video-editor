#!/usr/bin/env python3
"""Frozen-schema and cross-contract validation for the Motion Quality Engine."""
from __future__ import annotations

import json
import math
import re
import shutil
import subprocess
from pathlib import Path
from typing import Any, Callable, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from director_contracts import read_json, sha256_file


ROOT = Path(__file__).parents[1]
SCHEMA_ROOT = ROOT / "references" / "p0-p2-design" / "schemas"
DEFAULT_RECIPE_REGISTRY = ROOT / "references" / "motion-recipes-v1.json"
CONTRACT_SCHEMA_NAMES = (
    "motion-design-contract",
    "motion-recipe",
    "target-binding",
    "keyframe-receipt",
    "creative-review",
    "motion-audio-decision",
    "real-project-validation",
)
SCHEMA_PATHS = {
    name: SCHEMA_ROOT / f"{name}.schema.json" for name in CONTRACT_SCHEMA_NAMES
}
APPROVED_RECIPE_IDS = tuple(f"MQE-{index:02d}" for index in range(1, 17))
ACTION_REQUIRED_FALLBACK = "MQE-action-required"
FORBIDDEN_SELECTOR_KEYS = {
    "events_per_minute", "minimum_event_count", "minimum_family_count",
    "keyword_score", "random_family", "random_template", "random_sfx",
}


def _schema_errors(name: str, payload: Any) -> list[str]:
    path = SCHEMA_PATHS.get(name)
    if path is None:
        return [f"unknown contract schema: {name}"]
    if not path.is_file():
        return [f"contract schema is missing: {path}"]
    schema = read_json(path)
    validator = Draft202012Validator(schema, format_checker=FormatChecker())
    return [
        f"{name} schema "
        + (".".join(str(value) for value in error.absolute_path) or "root")
        + f": {error.message}"
        for error in sorted(validator.iter_errors(payload), key=lambda row: list(row.absolute_path))
    ]


def validate_contract_schema(name: str, payload: Any) -> list[str]:
    """Validate one instance against one of the seven frozen schemas."""
    return _schema_errors(name, payload)


def validate_all_schema_definitions() -> list[str]:
    """Meta-validate all seven design-frozen Draft 2020-12 schemas."""
    errors: list[str] = []
    for name in CONTRACT_SCHEMA_NAMES:
        path = SCHEMA_PATHS[name]
        if not path.is_file():
            errors.append(f"contract schema is missing: {path}")
            continue
        try:
            Draft202012Validator.check_schema(read_json(path))
        except Exception as error:  # jsonschema exposes several schema error subclasses
            errors.append(f"{name} schema definition is invalid: {error}")
    return errors


def validate_contract_instances(instances: Mapping[str, Any]) -> dict[str, list[str]]:
    """Validate supplied instances without pretending that absent contracts exist."""
    return {name: validate_contract_schema(name, payload) for name, payload in instances.items()}


def canonical_contract_evidence_refs(
    event: Mapping[str, Any], *, evidence_bundle_path: Path,
) -> list[str]:
    """Return schema-safe IDs while retaining exact frame hashes as authority."""
    bundle = read_json(evidence_bundle_path.resolve())
    known: dict[str, str] = {}
    for record in bundle.get("representative_frames") or []:
        if not isinstance(record, dict) or not record.get("path"):
            continue
        path = Path(str(record["path"]))
        if not path.is_absolute():
            path = evidence_bundle_path.parent / path
        digest = str(record.get("sha256") or "").lower()
        if re.fullmatch(r"[a-f0-9]{64}", digest):
            known[str(path.resolve())] = digest
    result: list[str] = []
    values = event.get("target_frame_evidence") or event.get("evidence_refs") or []
    for value in values:
        raw = value.get("path") if isinstance(value, dict) else value
        text = str(raw or "")
        if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}", text):
            result.append(text)
            continue
        path = Path(text)
        if not path.is_absolute():
            path = evidence_bundle_path.parent / path
        digest = known.get(str(path.resolve()))
        if digest is None:
            raise ValueError(
                f"{event.get('id')}: evidence path is not hash-bound by the evidence bundle: {path}"
            )
        result.append(f"frame-sha256:{digest}")
    if not result:
        raise ValueError(f"{event.get('id')}: every semantic opportunity requires visual evidence")
    return result


def _probe_video_media(path: Path) -> dict[str, Any]:
    if not shutil.which("ffprobe"):
        raise RuntimeError("ffprobe is required to verify real-project media")
    completed = subprocess.run(
        [
            "ffprobe", "-v", "error", "-show_entries",
            "format=duration:stream=codec_type,width,height:stream_tags=rotate:stream_side_data=rotation",
            "-of", "json", str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    payload = json.loads(completed.stdout)
    stream = next(
        (row for row in payload.get("streams") or [] if row.get("codec_type") == "video"),
        None,
    )
    if not isinstance(stream, dict):
        raise ValueError(f"real-project media has no video stream: {path}")
    width = int(stream.get("width") or 0)
    height = int(stream.get("height") or 0)
    rotation = int((stream.get("tags") or {}).get("rotate") or 0)
    for side_data in stream.get("side_data_list") or []:
        if isinstance(side_data, dict) and side_data.get("rotation") is not None:
            rotation = int(side_data["rotation"])
            break
    if abs(rotation) % 180 == 90:
        width, height = height, width
    return {
        "duration_seconds": float((payload.get("format") or {}).get("duration") or 0),
        "width": width,
        "height": height,
    }


def _verify_real_artifact(record: Mapping[str, Any], label: str) -> list[str]:
    errors: list[str] = []
    path = Path(str(record.get("path") or "")).resolve()
    if not path.is_file():
        return [f"{label} file is missing: {path}"]
    if record.get("sha256") != sha256_file(path):
        errors.append(f"{label} hash is stale")
    return errors


def validate_real_project_validation(
    receipt: dict[str, Any], *,
    media_probe: Callable[[Path], Mapping[str, Any]] | None = None,
    repository_root: Path | None = None,
    configuration_path: Path | None = None,
) -> list[str]:
    """Validate a real canary receipt beyond its structural JSON Schema.

    The schema alone cannot prove that files exist, that media metadata is real,
    or that a passing receipt satisfies the frozen cross-canary thresholds.
    This validator therefore fails closed on every materialized evidence record
    and keeps pending user review distinct from maturity promotion.
    """
    errors = _schema_errors("real-project-validation", receipt)
    if errors:
        return errors

    probe = media_probe or _probe_video_media
    for label in ("source", "baseline", "candidate"):
        record = receipt[label]
        errors.extend(_verify_real_artifact(record, label))
        path = Path(record["path"]).resolve()
        if not path.is_file():
            continue
        try:
            observed = probe(path)
        except Exception as error:  # media evidence must fail closed
            errors.append(f"{label} media probe failed: {error}")
            continue
        for dimension in ("width", "height"):
            if int(observed.get(dimension) or 0) != int(record[dimension]):
                errors.append(f"{label} {dimension} differs from probed media")
        if not math.isclose(
            float(observed.get("duration_seconds") or 0),
            float(record["duration_seconds"]),
            abs_tol=0.25,
        ):
            errors.append(f"{label} duration differs from probed media")

    source = receipt["source"]
    duration = float(source["duration_seconds"])
    if not 30.0 <= duration <= 90.0:
        errors.append("real-project source duration must be 30 through 90 seconds")
    if receipt["canary_role"] == "landscape_screen" and source["width"] <= source["height"]:
        errors.append("landscape_screen source must have landscape display geometry")
    if receipt["canary_role"] == "portrait_talking_head" and source["height"] <= source["width"]:
        errors.append("portrait_talking_head source must have portrait display geometry")
    if receipt["candidate"]["sha256"] == receipt["baseline"]["sha256"]:
        errors.append("paired real-project baseline and candidate must be distinct media")

    errors.extend(_verify_real_artifact(receipt["rights"]["evidence"], "rights evidence"))
    observed_pairs: set[tuple[str, str]] = set()
    automated_ids: set[str] = set()
    for index, result in enumerate(receipt["requirement_results"]):
        pair = (result["requirement_id"], result["gate_owner"])
        if pair in observed_pairs:
            errors.append(f"requirement_results[{index}] duplicates {pair[0]} {pair[1]}")
        observed_pairs.add(pair)
        if result["gate_owner"] == "automated":
            automated_ids.add(result["requirement_id"])
        for evidence_index, artifact in enumerate(result["evidence"]):
            errors.extend(_verify_real_artifact(
                artifact, f"requirement_results[{index}].evidence[{evidence_index}]",
            ))
    required_ids = {f"RQ-{index:03d}" for index in range(1, 21)}
    if automated_ids != required_ids:
        errors.append("real-project receipt requires automated RQ-001 through RQ-020 results")

    decisions: dict[str, dict[str, Any]] = {}
    for index, decision in enumerate(receipt["user_decisions"]):
        criterion = decision["criterion"]
        if criterion in decisions:
            errors.append(f"user_decisions[{index}] duplicates criterion {criterion}")
        decisions[criterion] = decision

    status = receipt["overall_status"]
    maturity = receipt["maturity_recommendation"]
    if status == "pass":
        for result in receipt["requirement_results"]:
            if result["gate_owner"] == "automated" and result["status"] not in {
                "pass", "not_applicable",
            }:
                errors.append(f"passing receipt has blocking {result['requirement_id']} result")
        for criterion in ("sample_quality", "publishability"):
            if (decisions.get(criterion) or {}).get("decision") != "approved":
                errors.append(f"passing receipt requires user-approved {criterion}")
        metrics = receipt["metrics"]
        if float(metrics["semantic_correct_rate"]) < 0.95:
            errors.append("passing receipt requires semantic correctness of at least 0.95")
        if float(metrics["geometry_correct_rate"]) < 0.95:
            errors.append("passing receipt requires geometry correctness of at least 0.95")
        if metrics["caption_sync_pass"] is not True:
            errors.append("passing receipt requires caption sync evidence")
        if metrics["audio_audibility_pass"] is not True:
            errors.append("passing receipt requires audio audibility evidence")
        if float(metrics["correction_minutes"]) > 20.0:
            errors.append("passing receipt correction time exceeds 20 minutes")
        if metrics["baseline_candidate_preference"] != "candidate":
            errors.append("passing receipt requires explicit candidate preference")
        if metrics["publish_willingness"] != "yes":
            errors.append("passing receipt requires publish willingness yes")
        if maturity != "real_project_validated":
            errors.append("passing receipt must recommend real_project_validated")
    elif maturity == "real_project_validated":
        errors.append("pending receipt cannot recommend real_project_validated")

    if configuration_path is not None:
        path = configuration_path.resolve()
        if not path.is_file():
            errors.append("real-project configuration file is missing")
        elif receipt["configuration_sha256"] != sha256_file(path):
            errors.append("real-project configuration hash is stale")

    if repository_root is not None:
        root = repository_root.resolve()
        try:
            from test_acceptance_report import source_tree_sha256

            actual_source_tree = source_tree_sha256(root)
            if receipt["implementation"]["source_tree_sha256"] != actual_source_tree:
                errors.append("real-project implementation source tree hash is stale")
            current_commit = subprocess.run(
                ["git", "rev-parse", "HEAD"], cwd=root, check=True,
                capture_output=True, text=True, encoding="utf-8",
            ).stdout.strip()
            if receipt["implementation"]["git_commit"] != current_commit:
                errors.append("real-project implementation git commit is stale")
        except Exception as error:
            errors.append(f"real-project implementation binding failed: {error}")
    return errors


def load_recipe_registry(path: Path = DEFAULT_RECIPE_REGISTRY) -> dict[str, Any]:
    return read_json(path.resolve())


def _walk_keys(value: Any) -> list[str]:
    keys: list[str] = []
    if isinstance(value, dict):
        for key, child in value.items():
            keys.append(str(key))
            keys.extend(_walk_keys(child))
    elif isinstance(value, list):
        for child in value:
            keys.extend(_walk_keys(child))
    return keys


def validate_recipe_registry(registry: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if registry.get("schema_version") != "1.0.0":
        errors.append("motion recipe registry schema_version must be 1.0.0")
    if registry.get("registry_id") != "motion-recipes-v1":
        errors.append("motion recipe registry_id must be motion-recipes-v1")
    recipes = registry.get("recipes")
    if not isinstance(recipes, list):
        return [*errors, "motion recipe registry recipes must be a list"]
    ids = [row.get("recipe_id") for row in recipes if isinstance(row, dict)]
    if ids != list(APPROVED_RECIPE_IDS):
        errors.append("motion recipe registry must contain MQE-01 through MQE-16 in order")
    if len(ids) != len(set(ids)):
        errors.append("motion recipe IDs must be unique")
    for index, recipe in enumerate(recipes):
        if not isinstance(recipe, dict):
            errors.append(f"recipes[{index}] must be a mapping")
            continue
        errors.extend(
            f"recipes[{index}] {error}" for error in _schema_errors("motion-recipe", recipe)
        )
        ratios = [row.get("duration_ratio") for row in recipe.get("phases") or []
                  if isinstance(row, dict)]
        if len(ratios) == 4 and all(isinstance(value, (int, float)) for value in ratios):
            if not math.isclose(sum(float(value) for value in ratios), 1.0, abs_tol=1e-9):
                errors.append(f"recipes[{index}] phase duration ratios must total 1.0")
        fallback = recipe.get("fallback_recipe_id")
        if fallback not in set(APPROVED_RECIPE_IDS) | {ACTION_REQUIRED_FALLBACK}:
            errors.append(f"recipes[{index}] fallback_recipe_id is not declared")
        forbidden = FORBIDDEN_SELECTOR_KEYS.intersection(_walk_keys(recipe))
        if forbidden:
            errors.append(
                f"recipes[{index}] contains forbidden selector fields: {', '.join(sorted(forbidden))}"
            )
    by_id = {row.get("recipe_id"): row for row in recipes if isinstance(row, dict)}
    for recipe_id in APPROVED_RECIPE_IDS:
        visited: set[str] = set()
        current = recipe_id
        while current != ACTION_REQUIRED_FALLBACK:
            if current in visited:
                errors.append(f"motion recipe fallback cycle starts at {recipe_id}")
                break
            visited.add(current)
            row = by_id.get(current)
            if row is None:
                break
            current = str(row.get("fallback_recipe_id"))
    return errors


def _verified_artifact_hashes(
    contract: dict[str, Any], artifact_paths: Mapping[str, Path] | None,
) -> list[str]:
    if artifact_paths is None:
        return []
    errors: list[str] = []
    input_hashes = contract.get("input_hashes") or {}
    field_names = {
        "semantic_brief": "semantic_brief_sha256",
        "production_contract": "production_contract_sha256",
        "evidence_bundle": "evidence_bundle_sha256",
        "brand_playbook": "brand_playbook_sha256",
        "editorial_intent": "editorial_intent_sha256",
    }
    for name, path_value in artifact_paths.items():
        field = field_names.get(name)
        if field is None:
            errors.append(f"unknown motion-design artifact binding: {name}")
            continue
        path = Path(path_value).resolve()
        if not path.is_file():
            errors.append(f"motion-design {name} artifact is missing")
            continue
        if input_hashes.get(field) != sha256_file(path):
            errors.append(f"motion-design {name} hash is stale")
            continue
        if name == "semantic_brief":
            brief = read_json(path)
            brief_events = brief.get("events") if isinstance(brief, dict) else None
            if not isinstance(brief_events, list):
                errors.append("motion-design semantic brief payload is invalid")
            else:
                expected = []
                evidence_bundle_path = Path(artifact_paths["evidence_bundle"]).resolve()
                for row in brief_events:
                    if not isinstance(row, dict):
                        continue
                    expected.append({
                        "semantic_event_id": str(row.get("id") or ""),
                        "decision": row.get("decision"),
                        "rationale": str(row.get("decision_rationale") or ""),
                        "source_window": {
                            "start_seconds": row.get("source_start"),
                            "end_seconds": row.get("source_end"),
                        },
                        "output_window": {
                            "start_seconds": row.get("output_start"),
                            "end_seconds": row.get("output_end"),
                        },
                        "transcript_word_ids": list(row.get("transcript_word_ids") or []),
                        "approved_visible_copy": list(row.get("approved_visible_copy") or []),
                        "viewer_takeaway": str(row.get("viewer_takeaway") or ""),
                        "evidence_refs": canonical_contract_evidence_refs(
                            row, evidence_bundle_path=evidence_bundle_path,
                        ),
                    })
                actual = []
                for row in contract.get("opportunities") or []:
                    actual.append({key: row.get(key) for key in expected[0].keys()} if expected else {})
                if actual != expected:
                    errors.append("motion-design opportunities do not inherit the hashed semantic brief")
        elif name == "evidence_bundle":
            evidence = read_json(path)
            source = contract.get("source_media") or {}
            display = evidence.get("display") or {}
            if (evidence.get("source") or {}).get("sha256") not in {None, source.get("sha256")}:
                errors.append("motion-design source hash differs from evidence bundle")
            comparisons = (
                ("duration_seconds", evidence.get("duration_seconds"), source.get("duration_seconds")),
                ("width", display.get("width"), source.get("width")),
                ("height", display.get("height"), source.get("height")),
                ("orientation", display.get("orientation"), source.get("orientation")),
            )
            for label, observed, declared in comparisons:
                if observed is not None and observed != declared:
                    errors.append(f"motion-design source {label} differs from evidence bundle")
        elif name == "production_contract":
            production = read_json(path)
            declared_identity = (production.get("identity") or {}).get("mode")
            if declared_identity is not None and declared_identity != contract.get("identity_mode"):
                errors.append("motion-design identity differs from Production Contract")
    return errors


def validate_motion_design_contract(
    contract: dict[str, Any], *, artifact_paths: Mapping[str, Path] | None = None,
    recipe_registry: dict[str, Any] | None = None,
) -> list[str]:
    """Validate schema plus identity, selection, time, recipe, and file/hash invariants."""
    errors = _schema_errors("motion-design-contract", contract)
    if errors:
        return errors
    registry = recipe_registry or load_recipe_registry()
    registry_errors = validate_recipe_registry(registry)
    if registry_errors:
        return [*errors, *registry_errors]
    recipes = {row["recipe_id"]: row for row in registry["recipes"]}
    opportunities = contract["opportunities"]
    ids = [row["semantic_event_id"] for row in opportunities]
    if len(ids) != len(set(ids)):
        errors.append("motion-design semantic_event_id values must be unique")
    render_ids = [row["semantic_event_id"] for row in opportunities if row["decision"] == "render"]
    if contract["selected_event_ids"] != render_ids:
        errors.append("motion-design selected_event_ids must equal the ordered render decisions")
    duration = float(contract["source_media"]["duration_seconds"])
    for index, row in enumerate(opportunities):
        for window_name in ("source_window", "output_window"):
            window = row[window_name]
            start = float(window["start_seconds"])
            end = float(window["end_seconds"])
            if end <= start:
                errors.append(f"opportunities[{index}] {window_name} end must follow start")
        source_window = row["source_window"]
        if float(source_window["end_seconds"]) > duration + 0.05:
            errors.append(f"opportunities[{index}] source window exceeds source duration")
        if row["decision"] == "render":
            recipe = recipes.get(row.get("recipe_id"))
            if recipe is None:
                errors.append(f"opportunities[{index}] references an unknown recipe")
                continue
            if row.get("semantic_role") not in recipe.get("semantic_roles", []):
                errors.append(f"opportunities[{index}] semantic role is unsupported by recipe")
            if contract["identity_mode"] == "third_party" and row.get("recipe_id") == "MQE-14":
                errors.append("third_party identity forbids MQE-14 personal IP recipe")
    source_path = Path(contract["source_media"]["path"])
    if not source_path.is_file():
        errors.append("motion-design source media is missing")
    elif contract["source_media"]["sha256"] != sha256_file(source_path):
        errors.append("motion-design source media hash is stale")
    errors.extend(_verified_artifact_hashes(contract, artifact_paths))
    forbidden = FORBIDDEN_SELECTOR_KEYS.intersection(_walk_keys(contract))
    if forbidden:
        errors.append(
            "motion-design contract contains forbidden selector fields: "
            + ", ".join(sorted(forbidden))
        )
    return errors


def validate_storyboard_motion_binding(
    storyboard: dict[str, Any], contract: dict[str, Any],
    recipe_registry: dict[str, Any] | None = None,
) -> list[str]:
    """Require HyperFrames to consume the compiled recipe instead of reselecting motion."""
    errors: list[str] = []
    rows = storyboard.get("events") if isinstance(storyboard, dict) else None
    if not isinstance(rows, list):
        return ["storyboard events must be a list for motion-design binding"]
    registry = recipe_registry or load_recipe_registry()
    from motion_quality_engine import choreography_fingerprint  # avoid import cycle at module load

    recipes = {row["recipe_id"]: row for row in registry["recipes"]}
    expected = [
        row for row in contract.get("opportunities") or [] if row.get("decision") == "render"
    ]
    if len(rows) != len(expected):
        errors.append("storyboard event count must equal motion-design render decisions")
        return errors
    for index, (event, compiled) in enumerate(zip(rows, expected)):
        if not isinstance(event, dict):
            errors.append(f"storyboard events[{index}] must be a mapping")
            continue
        if event.get("semantic_event_id") != compiled.get("semantic_event_id"):
            errors.append(f"storyboard events[{index}] semantic_event_id is not compiler-bound")
        if event.get("motion_design_contract_id") != contract.get("contract_id"):
            errors.append(f"storyboard events[{index}] motion_design_contract_id is stale")
        if event.get("recipe_id") != compiled.get("recipe_id"):
            errors.append(f"storyboard events[{index}] recipe_id differs from compiler selection")
            continue
        recipe = recipes.get(str(compiled.get("recipe_id")))
        if recipe is None:
            errors.append(f"storyboard events[{index}] compiler recipe is missing")
            continue
        if event.get("choreography_fingerprint_sha256") != choreography_fingerprint(recipe):
            errors.append(f"storyboard events[{index}] choreography fingerprint is stale")
        if list(event.get("target_binding_ids") or []) != list(
            compiled.get("target_binding_ids") or []
        ):
            errors.append(f"storyboard events[{index}] target binding IDs differ from compiler output")
    return errors
