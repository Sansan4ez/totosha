"""Usage stats for doc_search and promotion reports."""

from __future__ import annotations

import json
from collections import defaultdict
from datetime import datetime, timezone
import logging
from pathlib import Path
from typing import Any

from .storage import ensure_document_layout, get_document_paths, iter_live_documents


logger = logging.getLogger(__name__)


def _utcnow() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def append_usage_stat(
    *,
    query: str,
    payload: dict[str, Any],
    intent_class: str = "unknown",
    answer_success: bool | None = None,
    selected_result_rank: int | None = None,
) -> dict[str, Any]:
    paths = get_document_paths()
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    record = {
        "timestamp": _utcnow(),
        "query": query,
        "intent_class": intent_class,
        "selected_source": payload.get("selected_source") or payload.get("tool_name") or "doc_search",
        "tool_name": payload.get("tool_name") or "doc_search",
        "alias_for": payload.get("alias_for"),
        "status": payload.get("status") or "unknown",
        "result_count": int(payload.get("result_count") or len(results)),
        "answer_success": answer_success,
        "selected_result_rank": selected_result_rank,
        "documents": [
            {
                "document_id": item.get("document_id"),
                "relative_path": item.get("relative_path"),
                "file_type": item.get("file_type"),
                "match_mode": item.get("match_mode"),
                "score": item.get("score"),
                "rank": rank,
            }
            for rank, item in enumerate(results[:5], start=1)
        ],
    }
    try:
        paths.usage_stats.parent.mkdir(parents=True, exist_ok=True)
        with paths.usage_stats.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")
        record["persisted"] = True
    except OSError as exc:
        logger.warning("failed to persist doc_search usage stat: %s", exc)
        record["persisted"] = False
        record["persist_error"] = type(exc).__name__
    return record


def load_usage_stats(*, limit: int | None = None) -> list[dict[str, Any]]:
    paths = get_document_paths()
    if not paths.usage_stats.exists():
        return []
    items: list[dict[str, Any]] = []
    for line in paths.usage_stats.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            items.append(json.loads(line))
        except Exception:
            continue
    if limit is not None:
        return items[-limit:]
    return items


def build_promotion_candidates(*, min_hits: int = 2) -> list[dict[str, Any]]:
    live_index = {record["document_id"]: record for record in iter_live_documents()}
    aggregates: dict[str, dict[str, Any]] = defaultdict(lambda: {"query_hits": 0, "top_rank_hits": 0, "queries": set(), "last_seen_at": None})

    for record in load_usage_stats():
        for document in record.get("documents") or []:
            document_id = document.get("document_id")
            if not document_id:
                continue
            agg = aggregates[document_id]
            agg["query_hits"] += 1
            if document.get("rank") == 1:
                agg["top_rank_hits"] += 1
            agg["queries"].add(record.get("query"))
            seen_at = record.get("timestamp")
            if seen_at and (agg["last_seen_at"] is None or str(seen_at) > str(agg["last_seen_at"])):
                agg["last_seen_at"] = seen_at

    candidates: list[dict[str, Any]] = []
    for document_id, agg in aggregates.items():
        if agg["query_hits"] < min_hits:
            continue
        live = live_index.get(document_id, {})
        candidates.append(
            {
                "document_id": document_id,
                "sha256": live.get("sha256"),
                "relative_path": live.get("relative_path"),
                "file_type": live.get("file_type"),
                "query_hits": agg["query_hits"],
                "top_rank_hits": agg["top_rank_hits"],
                "unique_queries": sorted(query for query in agg["queries"] if query),
                "last_seen_at": agg["last_seen_at"],
                "promotion_state": (live.get("promotion") or {}).get("state", "pending"),
            }
        )
    candidates.sort(key=lambda item: (-int(item["query_hits"]), -int(item["top_rank_hits"]), str(item["document_id"])))
    return candidates


def write_promotion_candidates_report(*, min_hits: int = 2) -> dict[str, Any]:
    paths = ensure_document_layout(get_document_paths())
    candidates = build_promotion_candidates(min_hits=min_hits)
    payload = {
        "generated_at": _utcnow(),
        "min_hits": min_hits,
        "candidate_count": len(candidates),
        "candidates": candidates,
    }
    paths.promotion_candidates.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload
