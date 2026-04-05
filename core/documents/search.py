"""Bounded multiformat document search executor."""

from __future__ import annotations

import logging
import re
from time import perf_counter
from typing import Any

from .normalize import extract_text_for_search, load_search_limits
from .storage import (
    get_document_paths,
    iter_legacy_documents,
    iter_live_documents,
)


logger = logging.getLogger(__name__)

WORD_RE = re.compile(r"[\wА-Яа-яЁё]+", re.UNICODE)


def _query_terms(query: str) -> list[str]:
    return [term.lower() for term in WORD_RE.findall(query or "") if term.strip()]


def _collapse_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _score_text(query_terms: list[str], text: str, filename: str) -> tuple[int, str]:
    haystack = _collapse_space(text).lower()
    if not haystack:
        return 0, ""
    score = 0
    best_index = -1
    for term in query_terms:
        index = haystack.find(term)
        if index >= 0:
            best_index = index if best_index < 0 else min(best_index, index)
            score += 10 + haystack.count(term)
    if not query_terms and haystack:
        best_index = 0
        score = 1
    if any(term in filename.lower() for term in query_terms):
        score += 3
    return score, _snippet_from_index(haystack, best_index)


def _snippet_from_index(text: str, index: int) -> str:
    if not text:
        return ""
    limits = load_search_limits()
    if index < 0:
        return text[: limits.max_context_chars].strip()
    start = max(0, index - limits.max_context_chars // 2)
    end = min(len(text), index + limits.max_context_chars // 2)
    return text[start:end].strip()


def _extract_text(record: dict[str, Any], *, limits) -> tuple[str, str, bool, dict[str, Any] | None, float]:
    return extract_text_for_search(record, limits=limits)


def _discover_documents(include_legacy: bool) -> list[dict[str, Any]]:
    paths = get_document_paths()
    records = list(iter_live_documents(paths))
    if include_legacy:
        records.extend(list(iter_legacy_documents(paths)))
    return records


def _result_from_record(
    record: dict[str, Any],
    *,
    score: int,
    snippet: str,
    match_mode: str,
    cache_hit: bool,
    structured: dict[str, Any] | None,
) -> dict[str, Any]:
    page = None
    sheet = None
    slide = None
    if structured:
        pages = structured.get("pages")
        sheets = structured.get("sheets")
        slides = structured.get("slides")
        if isinstance(pages, list) and pages:
            page = pages[0].get("page")
        if isinstance(sheets, list) and sheets:
            sheet = sheets[0].get("sheet")
        if isinstance(slides, list) and slides:
            slide = slides[0].get("slide")

    return {
        "document_id": record.get("document_id"),
        "relative_path": record.get("relative_path") or record.get("original_filename"),
        "file_type": record.get("file_type"),
        "match_mode": match_mode,
        "snippet": snippet,
        "page": page,
        "sheet": sheet,
        "slide": slide,
        "cache_hit": cache_hit,
        "score": score,
        "source": "legacy_wiki" if str(record.get("status")) == "legacy" else "corp_docs_live",
    }


def search_documents(
    *,
    query: str,
    top: int = 5,
    include_legacy: bool = True,
) -> dict[str, Any]:
    started_at = perf_counter()
    limits = load_search_limits()
    query = str(query or "").strip()
    terms = _query_terms(query)
    if not query:
        return {"status": "error", "error": "query_required", "results": []}

    discovered = _discover_documents(include_legacy=include_legacy)
    results: list[dict[str, Any]] = []
    scanned = 0
    backend_counts: dict[str, int] = {}
    cache_hits = 0
    total_parse_duration_ms = 0.0
    extraction_failures: list[dict[str, Any]] = []
    normalization_missing_count = 0

    for record in discovered:
        if scanned >= limits.max_documents:
            break
        scanned += 1
        try:
            text, match_mode, cache_hit, structured, parse_duration_ms = _extract_text(record, limits=limits)
        except Exception as exc:
            parse_duration_ms = 0.0
            match_mode = "error"
            text = ""
            cache_hit = False
            structured = None
            backend_counts[match_mode] = backend_counts.get(match_mode, 0) + 1
            failure = {
                "document_id": record.get("document_id"),
                "relative_path": record.get("relative_path") or record.get("original_filename"),
                "file_type": record.get("file_type"),
                "error_type": type(exc).__name__,
                "error": str(exc)[:200],
            }
            if len(extraction_failures) < 10:
                extraction_failures.append(failure)
            logger.warning("doc_search extraction failed for %s: %s", failure["relative_path"], failure["error"])
            continue
        total_parse_duration_ms += parse_duration_ms
        backend_counts[match_mode] = backend_counts.get(match_mode, 0) + 1
        if match_mode == "normalization_missing":
            normalization_missing_count += 1
        if cache_hit:
            cache_hits += 1
        if not text:
            continue
        score, snippet = _score_text(terms, text, str(record.get("relative_path") or record.get("original_filename") or ""))
        if score <= 0:
            continue
        results.append(
            _result_from_record(
                record,
                score=score,
                snippet=snippet,
                match_mode=match_mode,
                cache_hit=cache_hit,
                structured=structured,
            )
        )

    results.sort(key=lambda item: (-int(item.get("score", 0)), str(item.get("relative_path") or "")))
    selected = results[: max(1, min(top, limits.max_results))]
    duration_ms = round((perf_counter() - started_at) * 1000, 2)
    if selected:
        status = "success"
    elif normalization_missing_count > 0:
        status = "normalization_missing"
    else:
        status = "empty"
    return {
        "status": status,
        "query": query,
        "result_count": len(selected),
        "results": selected,
        "scanned_documents": scanned,
        "duration_ms": duration_ms,
        "parse_duration_ms": round(total_parse_duration_ms, 2),
        "backend_counts": backend_counts,
        "cache_hit_count": cache_hits,
        "normalization_missing_count": normalization_missing_count,
        "extraction_failure_count": len(extraction_failures),
        "extraction_failures": extraction_failures,
        "search_substrate": "parsed_sidecars",
        "selected_source": "doc_search",
        "include_legacy": include_legacy,
    }
