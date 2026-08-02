#!/usr/bin/env python3
"""Optional rights-aware local semantic asset index with pluggable embeddings."""
from __future__ import annotations

import hashlib
import json
import math
import re
from pathlib import Path
from typing import Any

from director_contracts import sha256_file, write_json


def _stable_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"),
    ).encode("utf-8")).hexdigest()


def _tokens(text: str) -> list[str]:
    return sorted(set(re.findall(r"[\w\u4e00-\u9fff]+", text.lower())))


def _fixture_embedding(text: str) -> list[str]:
    return _tokens(text)


def _cache_key(path: Path, model: str, backend: str, semantic_text: str) -> str:
    return _stable_hash({
        "file_sha256": sha256_file(path), "model": model, "backend": backend,
        "semantic_text": semantic_text,
    })


def build_index(
    *, config: dict[str, Any], assets: list[dict[str, Any]], output: Path,
) -> dict[str, Any]:
    backend = str(config.get("backend") or "none")
    if config.get("enabled") is not True:
        return {"schema_version": 1, "status": "disabled", "entries": [], "rejected": []}
    if backend not in {"fixture", "precomputed"}:
        return {
            "schema_version": 1,
            "status": "unavailable",
            "reason": "configured embedding backend is not locally available; no model was downloaded",
            "backend": backend,
            "entries": [],
            "rejected": [],
        }
    model = str(config.get("embedding_model") or "fixture-v1")
    entries: list[dict[str, Any]] = []
    rejected: list[dict[str, Any]] = []
    for asset in assets:
        path = Path(str(asset.get("path") or "")).resolve()
        if not path.is_file():
            rejected.append({"path": str(path), "reason": "missing_file"})
            continue
        rights = str(asset.get("rights_basis") or "").strip()
        if not rights:
            rejected.append({"path": str(path), "reason": "missing_rights_basis"})
            continue
        semantic_text = str(asset.get("semantic_text") or asset.get("purpose") or path.stem)
        if backend == "precomputed":
            raw_embedding = asset.get("embedding")
            if (
                not isinstance(raw_embedding, list) or not raw_embedding
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       or not math.isfinite(float(value)) for value in raw_embedding)
            ):
                rejected.append({"path": str(path), "reason": "missing_precomputed_embedding"})
                continue
            embedding: list[Any] = [float(value) for value in raw_embedding]
        else:
            embedding = _fixture_embedding(semantic_text)
        entry = {
            "path": str(path),
            "sha256": sha256_file(path),
            "type": str(asset.get("type") or "unknown"),
            "source": str(asset.get("source") or "local user asset"),
            "purpose": str(asset.get("purpose") or "semantic retrieval"),
            "rights_basis": rights,
            "embedding": embedding,
            "embedding_backend": backend,
            "embedding_model": model,
            "embedding_version": str(config.get("embedding_version") or "1"),
            "embedding_cache_key": _cache_key(path, model, backend, semantic_text),
            "semantic_text": semantic_text,
            "motion_score": float(asset.get("motion_score") or 0.0),
        }
        entries.append(entry)
    implementation = Path(__file__).resolve()
    report = {
        "schema_version": 1,
        "status": "complete",
        "config": config,
        "config_sha256": _stable_hash(config),
        "implementation": {"path": str(implementation), "sha256": sha256_file(implementation)},
        "entries": entries,
        "rejected": rejected,
    }
    report["integrity_sha256"] = _stable_hash(report)
    write_json(output.resolve(), report)
    return report


def validate_index(report: dict[str, Any], config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    if report.get("schema_version") != 1 or report.get("status") != "complete":
        errors.append("semantic corpus index is not complete schema 1")
    if report.get("config") != config or report.get("config_sha256") != _stable_hash(config):
        errors.append("semantic corpus configuration binding is stale")
    if report.get("integrity_sha256") != _stable_hash(
        {key: value for key, value in report.items() if key != "integrity_sha256"}
    ):
        errors.append("semantic corpus integrity hash is stale")
    for index, entry in enumerate(report.get("entries") or []):
        path = Path(str(entry.get("path") or ""))
        if not path.is_file() or entry.get("sha256") != (
            sha256_file(path) if path.is_file() else None
        ):
            errors.append(f"semantic corpus entry {index} file binding is stale")
        for field in ("type", "source", "purpose", "rights_basis", "embedding_model",
                      "embedding_version", "embedding_cache_key"):
            if not entry.get(field):
                errors.append(f"semantic corpus entry {index} lacks {field}")
    implementation = report.get("implementation") or {}
    path = Path(str(implementation.get("path") or ""))
    if not path.is_file() or path.resolve() != Path(__file__).resolve() or (
        implementation.get("sha256") != (sha256_file(path) if path.is_file() else None)
    ):
        errors.append("semantic corpus implementation binding is stale")
    return errors


def search_index(
    *, index: dict[str, Any], query: str, event_id: str, limit: int = 5,
) -> dict[str, Any]:
    query_tokens = set(_fixture_embedding(query))
    results: list[dict[str, Any]] = []
    for entry in index.get("entries") or []:
        raw_embedding = entry.get("embedding") or []
        if raw_embedding and all(isinstance(value, (int, float)) and not isinstance(value, bool)
                                 for value in raw_embedding):
            query_vector = ((index.get("config") or {}).get("query_embeddings") or {}).get(query)
            if (
                not isinstance(query_vector, list)
                or len(query_vector) != len(raw_embedding)
                or any(isinstance(value, bool) or not isinstance(value, (int, float))
                       for value in query_vector)
            ):
                similarity = 0.0
                query_vector = []
            else:
                query_vector = [float(value) for value in query_vector]
            dot = sum(float(left) * right for left, right in zip(raw_embedding, query_vector))
            left_norm = math.sqrt(sum(float(value) ** 2 for value in raw_embedding))
            right_norm = math.sqrt(sum(value ** 2 for value in query_vector))
            similarity = dot / (left_norm * right_norm) if left_norm and right_norm else 0.0
        else:
            entry_tokens = set(raw_embedding)
            union = query_tokens | entry_tokens
            similarity = len(query_tokens & entry_tokens) / len(union) if union else 0.0
        results.append({
            **{key: entry[key] for key in (
                "path", "sha256", "type", "source", "purpose", "rights_basis",
                "embedding_model", "embedding_version", "embedding_cache_key", "motion_score",
            )},
            "semantic_similarity": round(similarity, 6),
            "event_id": event_id,
        })
    results.sort(key=lambda row: (-float(row["semantic_similarity"]), -float(row["motion_score"]), row["path"]))
    return {
        "schema_version": 1,
        "status": "complete" if results else "no_match",
        "query": query,
        "event_id": event_id,
        "index_integrity_sha256": index.get("integrity_sha256"),
        "results": results[:max(0, int(limit))],
    }
