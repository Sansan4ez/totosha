"""Canonical multiformat document search tool."""

from __future__ import annotations

import json
import logging
from time import perf_counter

try:
    from opentelemetry import trace
except Exception:  # pragma: no cover - local fallback
    class _NoopSpan:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def set_attribute(self, *args, **kwargs):
            return None

        def record_exception(self, *args, **kwargs):
            return None

    class _NoopTracer:
        def start_as_current_span(self, *args, **kwargs):
            return _NoopSpan()

    class _NoopTrace:
        @staticmethod
        def get_tracer(*args, **kwargs):
            return _NoopTracer()

    trace = _NoopTrace()

try:
    from prometheus_client import Counter, Histogram
except Exception:  # pragma: no cover - local fallback
    class _NoopMetric:
        def labels(self, *args, **kwargs):
            return self

        def inc(self, *args, **kwargs):
            return None

        def observe(self, *args, **kwargs):
            return None

    def Counter(*args, **kwargs):  # type: ignore[misc]
        return _NoopMetric()

    def Histogram(*args, **kwargs):  # type: ignore[misc]
        return _NoopMetric()

from documents.search import search_documents
from documents.usage import append_usage_stat
from models import ToolContext, ToolResult
from tool_output_policy import (
    RUNTIME_PAYLOAD_FORMAT_FULL_JSON,
    build_output_contract_metadata,
    serialize_runtime_json,
)


logger = logging.getLogger(__name__)
BENCH_ARTIFACT_RESULTS_LIMIT = 5
BENCH_ARTIFACT_PREVIEW_LIMIT = 600

DOC_SEARCH_REQUESTS_TOTAL = Counter(
    "doc_search_requests_total",
    "Number of doc_search requests grouped by status, top backend, and top file type.",
    ["status", "match_mode", "file_type", "cache_hit"],
)
DOC_SEARCH_DURATION_MS = Histogram(
    "doc_search_duration_milliseconds",
    "End-to-end doc_search duration in milliseconds.",
    buckets=(5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000),
)
DOC_SEARCH_PARSE_DURATION_MS = Histogram(
    "doc_search_parse_duration_milliseconds",
    "Cumulative document parsing duration within one doc_search request.",
    buckets=(1, 5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000),
)
DOC_SEARCH_RESULTS_TOTAL = Histogram(
    "doc_search_result_count",
    "Number of search results returned by doc_search.",
    buckets=(0, 1, 2, 3, 5, 8, 10, 15, 20),
)


def _get_tracer():
    return trace.get_tracer("core.tools.doc_search")


def _observe_metrics(payload: dict) -> None:
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    top_result = results[0] if results else {}
    DOC_SEARCH_REQUESTS_TOTAL.labels(
        str(payload.get("status") or "unknown"),
        str(top_result.get("match_mode") or "none"),
        str(top_result.get("file_type") or "none"),
        "true" if top_result.get("cache_hit") else "false",
    ).inc()
    duration = payload.get("duration_ms")
    if isinstance(duration, (int, float)):
        DOC_SEARCH_DURATION_MS.observe(float(duration))
    parse_duration = payload.get("parse_duration_ms")
    if isinstance(parse_duration, (int, float)):
        DOC_SEARCH_PARSE_DURATION_MS.observe(float(parse_duration))
    result_count = payload.get("result_count")
    if isinstance(result_count, int):
        DOC_SEARCH_RESULTS_TOTAL.observe(result_count)


def _truncate_text(value: object, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _build_bench_artifact(payload: dict, *, tool_name: str, alias_for: str | None = None) -> dict:
    results = payload.get("results") if isinstance(payload.get("results"), list) else []
    compact_results: list[dict[str, object]] = []
    for row in results[:BENCH_ARTIFACT_RESULTS_LIMIT]:
        if not isinstance(row, dict):
            continue
        compact_results.append(
            {
                "title": _truncate_text(row.get("title") or row.get("document_title"), 200),
                "document_title": _truncate_text(row.get("document_title"), 200),
                "path": row.get("path"),
                "relative_path": row.get("relative_path"),
                "url": row.get("url"),
                "document_id": row.get("document_id"),
                "source": row.get("source"),
                "file_type": row.get("file_type"),
                "match_mode": row.get("match_mode"),
                "source_type": row.get("source_type"),
                "score": row.get("score"),
                "preview": _truncate_text(row.get("preview") or row.get("snippet"), BENCH_ARTIFACT_PREVIEW_LIMIT),
            }
        )

    compact_payload = {
        "status": payload.get("status"),
        "query": payload.get("query"),
        "result_count": payload.get("result_count"),
        "requested_top": payload.get("requested_top"),
        "search_substrate": payload.get("search_substrate") or "parsed_sidecars",
        "normalization_missing_count": payload.get("normalization_missing_count"),
        "backend_counts": payload.get("backend_counts"),
        "results": compact_results,
    }
    if alias_for:
        compact_payload["alias_for"] = alias_for
    return {
        "tool": tool_name,
        "success": True,
        "kind": "doc_search",
        "captured_from": "tool_result_metadata",
        "payload": compact_payload,
    }


async def _run_doc_search_tool(
    args: dict,
    ctx: ToolContext,
    *,
    tool_name: str,
    alias_for: str | None = None,
) -> ToolResult:
    query = str(args.get("query") or "").strip()
    top = int(args.get("top", 5) or 5)

    if not query:
        return ToolResult(False, error="Query is required")

    started_at = perf_counter()
    with _get_tracer().start_as_current_span(f"tool.{tool_name}") as span:
        span.set_attribute("doc_search.tool_name", tool_name)
        if alias_for:
            span.set_attribute("doc_search.alias_for", alias_for)
        span.set_attribute("doc_search.top", top)
        try:
            payload = search_documents(query=query, top=top)
            payload["requested_top"] = top
            payload["tool_name"] = tool_name
            if alias_for:
                payload["alias_for"] = alias_for
            append_usage_stat(
                query=query,
                payload=payload,
                intent_class=str(args.get("intent_class") or "unknown"),
                answer_success=args.get("answer_success"),
                selected_result_rank=args.get("selected_result_rank"),
            )
            _observe_metrics(payload)

            results = payload.get("results") if isinstance(payload.get("results"), list) else []
            span.set_attribute("doc_search.status", str(payload.get("status") or "unknown"))
            span.set_attribute("doc_search.result_count", len(results))
            if results:
                span.set_attribute("doc_search.top_match_mode", str(results[0].get("match_mode") or ""))
                span.set_attribute("doc_search.top_file_type", str(results[0].get("file_type") or ""))
                span.set_attribute("doc_search.cache_hit", bool(results[0].get("cache_hit")))
            metadata = build_output_contract_metadata(
                bench_artifact=_build_bench_artifact(payload, tool_name=tool_name, alias_for=alias_for),
                runtime_payload_format=RUNTIME_PAYLOAD_FORMAT_FULL_JSON,
                bench_payload_format="compact_doc_search_artifact_v1",
            )
            return ToolResult(True, output=serialize_runtime_json(payload), metadata=metadata)
        except Exception as exc:
            duration_ms = round((perf_counter() - started_at) * 1000, 2)
            logger.exception("doc_search failed after %sms", duration_ms)
            span.record_exception(exc)
            span.set_attribute("doc_search.status", "error")
            return ToolResult(False, error=f"doc_search failed: {type(exc).__name__}: {exc}")


async def tool_doc_search(args: dict, ctx: ToolContext) -> ToolResult:
    return await _run_doc_search_tool(args, ctx, tool_name="doc_search")
