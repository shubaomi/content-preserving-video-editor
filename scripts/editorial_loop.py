#!/usr/bin/env python3
"""Optional, evidence-bound editorial sidecars; never a renderer or publisher."""
from __future__ import annotations

import argparse
from copy import deepcopy
import json
import math
from pathlib import Path
from typing import Any, Iterable

from action_required_contract import sha256_file, write_json
from editorial_promise import build_promise_ledger, validate_promise_bindings
from feedback_loop import _load_snapshot

SCHEMA = Path(__file__).resolve().parents[1] / "references/ip-content-loop-v1/editorial-envelope.schema.json"
FILES = {"strategy": "strategy-snapshot.json", "episode": "episode-brief.json",
         "readiness": "content-readiness.json", "proof": "proof-map.json"}
SOURCE_ROLES = {"source", "transcript", "edl", "frame"}


def read(path: Path) -> dict[str, Any]:
    def invalid(value):
        raise ValueError(f"non-finite JSON number: {value}")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result
    result = json.loads(path.read_text(encoding="utf-8"), parse_constant=invalid,
                        object_pairs_hook=unique)
    if not isinstance(result, dict):
        raise ValueError("editorial document must be an object")
    return result


def contained(path: Path, root: Path, allowed: Iterable[Path] = ()) -> Path:
    resolved = (path if path.is_absolute() else root / path).resolve()
    if not resolved.is_relative_to(root.resolve()) and resolved not in {p.resolve() for p in allowed}:
        raise ValueError(f"editorial path is outside project/explicit read-only sources: {path}")
    return resolved


def save(path: Path, data: dict, root: Path) -> None:
    # Check the final path, including existing junction/symlink parents, before writing.
    write_json(contained(path, root), data)


def binding(identifier: str, path: Path, role: str) -> dict[str, str]:
    return {"id": identifier, "path": str(path.resolve()),
            "sha256": sha256_file(path), "role": role}


def envelope(kind: str, payload: dict, refs: list[dict], *, status="validated") -> dict:
    return {"schema_version": 1, "kind": kind, "id": f"editorial-{kind}",
            "status": status, "bindings": refs, "payload": payload}


def validate_envelope(doc: dict, root: Path, *, allowed_read_paths: Iterable[Path] = (),
                      authorities: dict[str, list[Path]] | None = None) -> dict:
    # Lazy dependency: disabled legacy projects do not need to load the new schema.
    from jsonschema import Draft202012Validator
    errors = sorted(Draft202012Validator(read(SCHEMA)).iter_errors(doc), key=lambda e: str(e.path))
    if errors:
        raise ValueError("editorial schema: " + "; ".join(e.message for e in errors[:8]))
    refs = {r["id"]: r for r in doc["bindings"]}
    if len(refs) != len(doc["bindings"]):
        raise ValueError("duplicate binding ID")
    for ref in refs.values():
        path = contained(Path(ref["path"]), root, allowed_read_paths)
        if not path.is_file() or sha256_file(path) != ref["sha256"]:
            raise ValueError(f"stale binding: {ref['id']}")
        if authorities is not None and ref["role"] in SOURCE_ROLES | {"user_record", "strategy"}:
            if path not in {p.resolve() for p in authorities.get(ref["role"], [])}:
                raise ValueError(f"unrecognized authoritative {ref['role']}: {ref['id']}")

    def visit(value):
        if isinstance(value, float) and not math.isfinite(value):
            raise ValueError("non-finite number")
        if isinstance(value, dict):
            if "basis" in value:
                ids = value["evidence_ids"]
                if any(i not in refs for i in ids):
                    raise ValueError("unknown fact evidence ID")
                expected = {"user_record"} if value["basis"] == "user_confirmed" else SOURCE_ROLES
                if value["basis"] in {"user_confirmed", "source_observed"} and not all(
                    refs[i]["role"] in expected for i in ids
                ):
                    raise ValueError("fact evidence role does not support its basis")
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)
    visit(doc)
    if doc["status"] == "stale":
        raise ValueError("stale editorial document")
    if doc["kind"] == "platform":
        payload = doc["payload"]
        for field, role in (("master_ref", "master"), ("promise_ref", "promise")):
            if payload[field] not in refs or refs[payload[field]]["role"] != role:
                raise ValueError(f"platform {field} requires a bound {role}")
        ledger = read(contained(Path(refs[payload["promise_ref"]]["path"]), root, allowed_read_paths))
        if payload["cta"] != ledger.get("cta"):
            raise ValueError("platform CTA must reuse the current promise")
        surfaces = [{"surface": surface, "copy": payload[field], "promise_id": ledger.get("promise_id"),
                     "proof_event_ids": (ledger.get("single_promise") or {}).get("proof_event_ids", [])}
                    for surface, field in (("title", "title"), ("description", "description"), ("cover", "cover_copy"))
                    if payload[field] is not None]
        errors = validate_promise_bindings(ledger, surfaces)
        if errors:
            raise ValueError("platform promise mismatch: " + "; ".join(errors))
    if doc["kind"] == "learning":
        observations = doc["payload"]["observations"]
        keys = set()
        for observation in observations:
            ref_id = observation["snapshot_ref"]
            if ref_id not in refs or refs[ref_id]["role"] != "metrics":
                raise ValueError("observation requires a bound metrics snapshot")
            key = tuple(observation[k] for k in ("publication_id", "platform", "version_id", "window_hours"))
            if key in keys:
                raise ValueError("duplicate publication observation")
            keys.add(key)
        if (doc["status"] == "no_observations") != (not observations):
            raise ValueError("no_observations must accurately describe missing data")
    return doc


def project_intent(strategy: dict, episode: dict, proof: dict, words: list[dict],
                   brief: dict, *, identity_mode: str) -> dict:
    """Project authored facts onto the existing promise authority, without editing words."""
    s, e = strategy["payload"], episode["payload"]
    if s["identity_mode"] != identity_mode:
        raise ValueError("strategy identity differs from the current project identity")
    if s["series_id"] != e["series_id"]:
        raise ValueError("strategy/episode series conflict requires user review")
    word_map = {str(w.get("id")): w for w in words if w.get("type", "word") == "word"}
    positions = {str(w.get("id")): i for i, w in enumerate(words)}
    events = {str(row["id"]): row for row in brief.get("events", [])}
    if len(positions) != len(words) or len(events) != len(brief.get("events", [])):
        raise ValueError("duplicate authoritative word/event IDs")
    claims = {row["claim_id"]: row for row in proof["payload"]["claims"]}
    if len(claims) != len(proof["payload"]["claims"]):
        raise ValueError("duplicate proof claim ID")
    refs = {row["id"]: row for row in proof["bindings"]}
    for claim in claims.values():
        ids, event_ids = claim["word_ids"], claim["event_ids"]
        if any(i not in word_map for i in ids) or any(i not in events for i in event_ids):
            raise ValueError("proof references unknown word/event IDs")
        if [positions[i] for i in ids] != sorted(positions[i] for i in ids):
            raise ValueError("proof word order is inconsistent")
        if any(i not in refs for i in claim["evidence_ids"]):
            raise ValueError("unknown proof evidence ID")
        if claim["support"] == "supported":
            if not ids or not event_ids or not claim["evidence_ids"]:
                raise ValueError("supported proof requires words, events and source evidence")
            if any(refs[i]["role"] not in SOURCE_ROLES for i in claim["evidence_ids"]):
                raise ValueError("generated or non-source evidence cannot prove a real claim")
            if not any(refs[i]["role"] in {"source", "transcript", "frame"} for i in claim["evidence_ids"]):
                raise ValueError("EDL timing alone cannot prove a factual claim")
        event_words = set()
        for event_id in event_ids:
            event = events[event_id]
            selected = set(event.get("transcript_word_ids") or [])
            if claim["support"] == "supported" and not selected.intersection(ids):
                raise ValueError("each proof event must contain selected word evidence")
            event_words.update(selected)
            for word_id in set(ids) & selected:
                word = word_map[word_id]
                start, end = word.get("start"), word.get("end")
                if any(isinstance(v, bool) or not isinstance(v, (int, float)) or not math.isfinite(v)
                       for v in (start, end)) or start >= end:
                    raise ValueError("invalid proof word window")
                if event.get("source_start") is not None and (
                    start < event["source_start"] - 0.001 or end > event["source_end"] + 0.001
                ):
                    raise ValueError("proof word is outside event source window")
        if not set(ids).issubset(event_words):
            raise ValueError("proof word IDs do not belong to the selected event occurrence")
    selected_claims = [claims.get(i) for i in e["proof_ids"]]
    if not selected_claims or any(c is None or c["support"] != "supported" for c in selected_claims):
        raise ValueError("episode requires existing supported proof IDs")
    thesis = e["thesis"]["value"]
    if thesis is None:
        # Unknown positioning remains unknown; the existing neutral ledger supplies a topic.
        thesis = build_promise_ledger({"events": list(events.values())})["single_promise"]["text"]
    if thesis not in {c["claim"] for c in selected_claims}:
        raise ValueError("episode thesis must match a supported proof claim")
    strategy_promise = s["promise"]
    if strategy_promise["basis"] == "user_confirmed" and strategy_promise["value"] != thesis:
        if e["thesis"]["basis"] != "user_confirmed":
            raise ValueError("strategy/episode promise conflict requires explicit user review")
    intent = {
        "mode": "explicit", "audience": s["audience"]["value"] or "interested_viewer",
        "viewer_job": e["viewer_job"]["value"] or "understand_the_evidence_backed_topic",
        "single_promise": thesis,
        "proof_event_ids": list(dict.fromkeys(i for c in selected_claims for i in c["event_ids"])),
        "cta": e["cta"]["value"] or f"继续了解{thesis}",
        "tone": s["tone"]["value"] or "neutral_educational",
        "prohibited_claims": s["boundaries"] or ["无证据的效果保证"],
    }
    build_promise_ledger({**brief, "editorial_intent": intent})
    return intent


def load_bundle(directory: Path, root: Path, *, transcript: Path, edl: Path,
                source: Path, semantic_brief: Path, evidence_bundle: Path,
                project_file: Path, identity_mode: str, strategy_path: Path | None = None) -> tuple[dict, list[Path]]:
    """Validate required sidecars and return a projection plus every cache dependency."""
    allowed = [source] + ([strategy_path] if strategy_path else [])
    evidence = read(evidence_bundle)
    frames = []
    for row in evidence.get("representative_frames", []):
        frame_path = Path(row["path"])
        path = contained(frame_path if frame_path.is_absolute() else evidence_bundle.parent / frame_path, root)
        if not path.is_file() or row.get("sha256") != sha256_file(path):
            raise ValueError("stale source frame evidence")
        frames.append(path)
    authorities = {"source": [source], "transcript": [transcript], "edl": [edl],
                   "frame": frames, "user_record": [],
                   "strategy": [strategy_path] if strategy_path else []}
    # User confirmation records are explicit project-local inputs, not arbitrary bindings.
    user_record = directory / "user-record.json"
    if user_record.is_file():
        record = read(user_record)
        if (set(record) != {"source", "message"} or record["source"] != "explicit_user_message"
                or not isinstance(record["message"], str) or not record["message"].strip()):
            raise ValueError("invalid explicit user record")
        authorities["user_record"].append(user_record)
    docs, dependencies = {}, [transcript, edl, source, semantic_brief, evidence_bundle, project_file, SCHEMA,
                              Path(__file__).resolve(), Path(__file__).with_name("editorial_promise.py"), *frames]
    for kind, name in FILES.items():
        path = contained(directory / name, root)
        doc = validate_envelope(read(path), root, allowed_read_paths=allowed, authorities=authorities)
        if doc["kind"] != kind or doc["status"] != "validated":
            raise ValueError(f"{kind} requires validated structure; subjective decisions remain separate")
        docs[kind] = doc
        dependencies.extend([path, *(contained(Path(r["path"]), root, allowed) for r in doc["bindings"])])
    if strategy_path:
        original = validate_envelope(read(strategy_path), root, allowed_read_paths=allowed, authorities=authorities)
        if original["kind"] != "strategy" or docs["strategy"]["payload"] != original["payload"]:
            raise ValueError("strategy snapshot conflicts with shared read-only strategy")
        if not any(r["role"] == "strategy" and Path(r["path"]).resolve() == strategy_path.resolve()
                   for r in docs["strategy"]["bindings"]):
            raise ValueError("strategy snapshot must bind the shared source hash")
        dependencies.append(strategy_path)
    required = {"source": source, "transcript": transcript, "edl": edl, "semantic_brief": semantic_brief}
    bound = {(r["role"], contained(Path(r["path"]), root, allowed))
             for d in docs.values() for r in d["bindings"]}
    if any((role, path.resolve()) not in bound for role, path in required.items()):
        raise ValueError("editorial bundle lacks current source/transcript/EDL/semantic brief bindings")
    brief = read(semantic_brief)
    intent = project_intent(docs["strategy"], docs["episode"], docs["proof"],
                            read(transcript).get("words", []), brief, identity_mode=identity_mode)
    if isinstance(brief.get("editorial_intent"), dict) and brief["editorial_intent"] != intent:
        raise ValueError("semantic brief editorial intent conflicts with the sidecar projection")
    return intent, list(dict.fromkeys(p.resolve() for p in dependencies))


def build_platform_packages(copy_path: Path, ledger_path: Path, master: Path,
                            root: Path, *, cover_copy: str | None = None) -> list[dict]:
    copy, ledger = read(copy_path), read(ledger_path)
    refs = [binding("publishing-copy", copy_path, "brief"), binding("promise", ledger_path, "promise"),
            binding("master", master, "master")]
    packages = []
    for platform in ("douyin", "wechat_channels"):
        recommended = copy.get(platform, {}).get("recommended", {})
        payload = {"platform": platform, "promise_ref": "promise", "master_ref": "master",
                   "title": recommended.get("title"), "description": recommended.get("description"),
                   "cover_copy": cover_copy, "cta": ledger["cta"], "publish_authorized": False}
        # Reuse the existing promise validator for every platform, not a second claim scorer.
        surfaces = [{"surface": surface, "copy": text, "promise_id": ledger["promise_id"],
                     "proof_event_ids": ledger["single_promise"]["proof_event_ids"]}
                    for surface, text in (("title", payload["title"]), ("description", payload["description"]))]
        if cover_copy:
            surfaces.append({**surfaces[0], "surface": "cover", "copy": cover_copy})
        errors = validate_promise_bindings(ledger, surfaces)
        if errors:
            raise ValueError("platform promise mismatch: " + "; ".join(errors))
        doc = envelope("platform", payload, deepcopy(refs))
        doc["id"] += "-" + platform
        validate_envelope(doc, root)
        packages.append(doc)
    return packages


def build_learning_candidates(rows: list[dict], root: Path, request_path: Path,
                              *, comments_path: Path | None = None) -> dict:
    """Offline observational hypotheses; no raw comments, preference writes or video invalidation."""
    refs = [binding("request", contained(request_path, root), "user_record")]
    observations, snapshots, keys = [], [], set()
    publication_bindings = {}
    required = {"snapshot", "window_hours", "metric_definition", "denominator", "traffic_source"}
    for row in rows:
        if not isinstance(row, dict) or set(row) != required:
            raise ValueError("learning input requires exact snapshot/comparability fields")
        path = contained(Path(row["snapshot"]), root)
        snapshot = _load_snapshot(path)
        binding_data = snapshot["binding"]
        version = binding_data.get("version_id")
        if not version:
            raise ValueError("learning snapshot requires a release version_id")
        hours = (snapshot["_observed_at"] - snapshot["_published_at"]).total_seconds() / 3600
        window = row["window_hours"]
        if isinstance(window, bool) or not isinstance(window, (int, float)) or not math.isfinite(window) or abs(hours-window) > 1/3600:
            raise ValueError("observation window must match the actual snapshot timestamps")
        if row["denominator"] is not None and row["denominator"] != snapshot["metrics"]["views"]:
            raise ValueError("denominator must match observed views, or be null when unknown")
        key = (binding_data["publication_id"], snapshot.get("platform"), version, window)
        release_key = key[:3]
        release_binding = (binding_data["release_manifest_sha256"], binding_data["video_sha256"],
                           snapshot["published_at"])
        if release_key in publication_bindings and publication_bindings[release_key] != release_binding:
            raise ValueError("same publication/version has conflicting release bindings")
        publication_bindings[release_key] = release_binding
        if key in keys:
            raise ValueError("duplicate publication/platform/version/window observation")
        keys.add(key)
        ref_id = f"snapshot-{len(snapshots)}"
        refs.append(binding(ref_id, path, "metrics"))
        observations.append({"publication_id": key[0], "platform": key[1], "version_id": version,
                             "snapshot_ref": ref_id, **{k: row[k] for k in required - {"snapshot"}}})
        snapshots.append(snapshot)
    for release_key in publication_bindings:
        series = sorted((snapshot for snapshot in snapshots if (
            snapshot["binding"]["publication_id"], snapshot.get("platform"),
            snapshot["binding"]["version_id"]) == release_key), key=lambda s: s["_observed_at"])
        if any(a["metrics"]["views"] > b["metrics"]["views"] for a, b in zip(series, series[1:])):
            raise ValueError("cumulative views must not decrease across snapshots")
    # Count independent publications AND distinct source releases, not repeated snapshots.
    cohorts: dict[tuple, set[tuple]] = {}
    for observation, snapshot in zip(observations, snapshots):
        if (observation["traffic_source"] in (None, "unknown") or
                observation["metric_definition"] in ("unknown", "") or
                observation["denominator"] is None or observation["denominator"] < 200 or
                observation["window_hours"] < 24):
            continue
        key = (observation["platform"], observation["window_hours"],
               observation["metric_definition"], observation["traffic_source"])
        cohorts.setdefault(key, set()).add((observation["publication_id"], snapshot["binding"]["video_sha256"]))
    comparable = any(len({p for p, _ in group}) >= 2 and len({v for _, v in group}) >= 2
                     for group in cohorts.values())
    hypotheses = []
    if comparable:
        hypotheses.append({"value": "可比较的观察仅支持提出假设：下一期测试开场表达是否影响理解，不推断增长因果。",
                           "basis": "editorial_inference", "evidence_ids": [r["id"] for r in refs if r["role"] == "metrics"]})
    if comments_path:
        path = contained(comments_path, root)
        comments = read(path)
        categories = {"questions", "objections", "purchase_intent", "next_topics"}
        if set(comments) != {"categories"} or not isinstance(comments["categories"], dict) or set(comments["categories"]) - categories:
            raise ValueError("comments require anonymized category counts only; raw text/identities are forbidden")
        if any(type(v) is not int or v < 0 for v in comments["categories"].values()):
            raise ValueError("comment category counts must be non-negative integers")
        refs.append(binding("comments", path, "comments"))
        if sum(comments["categories"].values()):
            hypotheses.append({"value": "用户提供的脱敏评论类别可作为下一期选题线索；不代表真实购买或因果效果。",
                               "basis": "editorial_inference", "evidence_ids": ["comments"]})
    status = "no_observations" if not observations else "pending_user_review" if comparable else "insufficient_evidence"
    payload = {"observations": observations, "hypotheses": hypotheses,
               "next_experiment": ("仅改变下一期开场表达；保持主题、时长、投放来源与观察窗口一致，记录完播与评论追问；人工审核后执行。"
                                   if comparable else None), "automatic_apply": False}
    result = envelope("learning", payload, refs, status=status)
    validate_envelope(result, root)
    return result


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--learning-input", type=Path, required=True,
                        help="Project-local JSON with observations array and optional comments path")
    args = parser.parse_args()
    root = args.project_root.resolve()
    request_path = contained(args.learning_input, root)
    request = read(request_path)
    if set(request) - {"observations", "comments"} or not isinstance(request.get("observations"), list):
        raise ValueError("learning request requires observations and optional comments only")
    result = build_learning_candidates(request["observations"], root, request_path,
                                       comments_path=Path(request["comments"]) if request.get("comments") else None)
    output = root / "work/director/editorial-loop/learning-candidates.json"
    save(output, result, root)
    print(json.dumps({"status": result["status"], "output": str(output)}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
