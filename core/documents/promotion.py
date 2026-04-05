"""Promotion helpers for exporting doc_search content into corp-db-ready manifests."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Any

from .cache import load_parse_cache
from .storage import ensure_document_layout, find_document_by_sha256, get_document_paths, load_live_document


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _chunk_text(text: str, *, target_chars: int = 900) -> list[str]:
    clean = re.sub(r"\s+", " ", text or "").strip()
    if not clean:
        return []
    chunks: list[str] = []
    start = 0
    while start < len(clean):
        end = min(len(clean), start + target_chars)
        if end < len(clean):
            split_at = clean.rfind(". ", start, end)
            if split_at <= start:
                split_at = clean.rfind(" ", start, end)
            if split_at > start:
                end = split_at + 1
        chunks.append(clean[start:end].strip())
        start = end
    return [chunk for chunk in chunks if chunk]


def export_document_for_corp_db(document_id: str) -> dict[str, Any]:
    paths = ensure_document_layout(get_document_paths())
    live = load_live_document(document_id, paths)
    sha256 = str(live.get("sha256") or "")
    full_manifest = find_document_by_sha256(sha256, paths) if sha256 else None
    record = full_manifest or live
    cached = load_parse_cache(sha256)
    if not cached:
        return {
            "status": "normalization_missing",
            "document_id": document_id,
            "sha256": sha256,
            "relative_path": live.get("relative_path"),
            "error": "normalized_sidecar_required",
        }
    text = str(cached.get("text") or "")
    meta = dict(cached.get("meta") or {})

    chunks = _chunk_text(text)
    promotion_dir = paths.manifests / "promotion"
    promotion_dir.mkdir(parents=True, exist_ok=True)
    base_name = f"{document_id}_{sha256[:12] if sha256 else 'legacy'}"
    manifest_path = promotion_dir / f"{base_name}.json"
    jsonl_path = promotion_dir / f"{base_name}.jsonl"

    manifest = {
        "status": "success",
        "generated_at": _utcnow(),
        "document_id": document_id,
        "sha256": sha256,
        "relative_path": live.get("relative_path"),
        "chunk_count": len(chunks),
        "jsonl_path": str(jsonl_path),
        "chunk_source": "normalized_sidecar",
        "normalized_sidecar_dir": str(cached.get("sidecar_dir") or ""),
        "parser_version": meta.get("parser_version"),
        "ocr_config_hash": meta.get("ocr_config_hash"),
        "routing_hint": {
            "preferred_source_after_ingest": "corp_db_search",
            "fallback_source": "doc_search",
            "promoted_from_document_id": document_id,
        },
    }
    rows = []
    for index, chunk in enumerate(chunks, start=1):
        rows.append(
            {
                "document_id": document_id,
                "sha256": sha256,
                "chunk_id": f"{document_id}#chunk-{index}",
                "chunk_index": index,
                "source_relative_path": live.get("relative_path"),
                "chunk_source": "normalized_sidecar",
                "text": chunk,
            }
        )

    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    jsonl_path.write_text("".join(json.dumps(row, ensure_ascii=False) + "\n" for row in rows), encoding="utf-8")
    return manifest
