"""Bounded multiformat document search executor."""

from __future__ import annotations

import logging
import re
from time import perf_counter
from typing import Any

from .normalize import extract_text_for_search, load_search_limits
from .storage import (
    get_document_paths,
    iter_live_documents,
)


logger = logging.getLogger(__name__)

WORD_RE = re.compile(r"[\wА-Яа-яЁё]+", re.UNICODE)
SEARCH_STOPWORDS = {
    "а",
    "без",
    "бы",
    "в",
    "во",
    "где",
    "дай",
    "для",
    "до",
    "если",
    "есть",
    "же",
    "и",
    "из",
    "или",
    "какая",
    "какие",
    "каких",
    "какой",
    "как",
    "компания",
    "компании",
    "когда",
    "коротко",
    "ладзавод",
    "ли",
    "мне",
    "на",
    "о",
    "об",
    "от",
    "по",
    "под",
    "покажи",
    "покажите",
    "прямую",
    "прямые",
    "прямой",
    "про",
    "с",
    "со",
    "светотехники",
    "светильник",
    "светильники",
    "светильников",
    "ссылка",
    "ссылки",
    "то",
    "у",
    "чем",
}


def _query_terms(query: str) -> list[str]:
    return [term.lower() for term in WORD_RE.findall(query or "") if term.strip()]


def _collapse_space(text: str) -> str:
    return re.sub(r"\s+", " ", text or "").strip()


def _normalized_query_terms(query_terms: list[str]) -> list[str]:
    seen: set[str] = set()
    normalized: list[str] = []
    for raw_term in query_terms:
        term = str(raw_term or "").strip().lower()
        if not term or term in SEARCH_STOPWORDS:
            continue
        if len(term) <= 1:
            continue
        if term in seen:
            continue
        seen.add(term)
        normalized.append(term)
    return normalized


def _query_phrases(query_terms: list[str]) -> list[str]:
    phrases: list[str] = []
    seen: set[str] = set()
    max_window = min(3, len(query_terms))
    for window in range(max_window, 1, -1):
        for index in range(0, len(query_terms) - window + 1):
            phrase = " ".join(query_terms[index : index + window]).strip()
            if len(phrase) < 5 or phrase in seen:
                continue
            seen.add(phrase)
            phrases.append(phrase)
    return phrases


def _line_score(line_text: str, query_terms: list[str], query_phrases: list[str]) -> int:
    line = _collapse_space(line_text).lower()
    if not line:
        return 0
    score = 0
    matched_terms = 0
    for phrase in query_phrases:
        if phrase in line:
            score += 18 + phrase.count(" ") * 4
    for term in query_terms:
        occurrences = line.count(term)
        if occurrences <= 0:
            continue
        matched_terms += 1
        score += 6 + min(occurrences, 2) * 2 + min(len(term), 12) // 3
    if "сертификат" in query_terms and "сертификат" not in line:
        score -= 12
    if any(term in query_terms for term in ("закаленное", "закалённое", "стекло")) and not any(
        term in line for term in ("закаленное", "закалённое", "стекло")
    ):
        score -= 12
    if matched_terms >= 2:
        score += matched_terms * 3
    if len(line) > 180:
        score -= min(20, len(line) // 30)
    return score


def _matched_query_terms(line_text: str, query_terms: list[str]) -> set[str]:
    line = _collapse_space(line_text).lower()
    if not line:
        return set()
    return {term for term in query_terms if term in line}


def _best_matching_lines(text: str, query_terms: list[str], query_phrases: list[str]) -> tuple[int, str]:
    limits = load_search_limits()
    snippet_limit = max(limits.max_context_chars, 480)
    scored_lines: list[tuple[int, str, int, set[str]]] = []
    for index, raw_line in enumerate((text or "").splitlines()):
        compact = _collapse_space(raw_line)
        if not compact:
            continue
        score = _line_score(compact, query_terms, query_phrases)
        if score <= 0:
            continue
        matched_terms = _matched_query_terms(compact, query_terms)
        scored_lines.append((score, compact, index, matched_terms))

    if not scored_lines:
        return 0, ""

    scored_lines.sort(key=lambda item: (-item[0], item[2]))
    chosen: list[str] = []
    seen_lines: set[str] = set()
    total_score = 0
    remaining = list(scored_lines)
    uncovered_terms = set(query_terms)
    while remaining and len(chosen) < 4:
        best_idx = 0
        best_rank: tuple[int, int, int] | None = None
        for idx, (score, line, line_index, matched_terms) in enumerate(remaining):
            if line in seen_lines:
                continue
            new_terms = len(uncovered_terms.intersection(matched_terms))
            rank = (new_terms, score, -line_index)
            if best_rank is None or rank > best_rank:
                best_rank = rank
                best_idx = idx
        score, line, _line_index, matched_terms = remaining.pop(best_idx)
        if line in seen_lines:
            continue
        seen_lines.add(line)
        chosen.append(line)
        total_score += score
        uncovered_terms.difference_update(matched_terms)
    snippet = " | ".join(chosen)
    if len(snippet) > snippet_limit:
        snippet = snippet[: max(0, snippet_limit - 1)].rstrip() + "…"
    return total_score, snippet


def _score_text(query_terms: list[str], text: str, filename: str) -> tuple[int, str]:
    haystack = _collapse_space(text).lower()
    if not haystack:
        return 0, ""
    normalized_terms = _normalized_query_terms(query_terms)
    if not normalized_terms:
        normalized_terms = _normalized_query_terms([term for term in query_terms if len(term) > 1])
    phrases = _query_phrases(normalized_terms)
    line_score, line_snippet = _best_matching_lines(text, normalized_terms, phrases)
    score = line_score
    best_index = -1
    for term in normalized_terms:
        index = haystack.find(term)
        if index >= 0:
            best_index = index if best_index < 0 else min(best_index, index)
            score += 2
    if not query_terms and haystack:
        best_index = 0
        score = 1
    if any(term in filename.lower() for term in normalized_terms):
        score += 3
    if line_snippet:
        return score, line_snippet
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


def _discover_documents() -> list[dict[str, Any]]:
    paths = get_document_paths()
    return list(iter_live_documents(paths))


def _preferred_document_matches(record: dict[str, Any], preferred_document_ids: set[str]) -> bool:
    candidates = {
        str(record.get("document_id") or "").strip(),
        str(record.get("relative_path") or "").strip(),
        str(record.get("original_filename") or "").strip(),
    }
    for alias in record.get("aliases") or []:
        if not isinstance(alias, dict):
            continue
        candidates.add(str(alias.get("relative_path") or "").strip())
        candidates.add(str(alias.get("name") or "").strip())
    normalized = {item.lower() for item in candidates if item}
    return bool(normalized.intersection(preferred_document_ids))


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
        "preview": snippet,
        "page": page,
        "sheet": sheet,
        "slide": slide,
        "cache_hit": cache_hit,
        "score": score,
        "source": "corp_docs_live",
    }


def search_documents(
    *,
    query: str,
    top: int = 5,
    preferred_document_ids: list[str] | None = None,
) -> dict[str, Any]:
    started_at = perf_counter()
    limits = load_search_limits()
    query = str(query or "").strip()
    terms = _query_terms(query)
    if not query:
        return {"status": "error", "error": "query_required", "results": []}

    preferred_ids = {
        str(item or "").strip().lower()
        for item in (preferred_document_ids or [])
        if str(item or "").strip()
    }
    discovered = _discover_documents()
    results: list[dict[str, Any]] = []
    scanned = 0
    backend_counts: dict[str, int] = {}
    cache_hits = 0
    total_parse_duration_ms = 0.0
    extraction_failures: list[dict[str, Any]] = []
    normalization_missing_count = 0

    for record in discovered:
        if preferred_ids and not _preferred_document_matches(record, preferred_ids):
            continue
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
        "preferred_document_ids": sorted(preferred_ids),
    }
