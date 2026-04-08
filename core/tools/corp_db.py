"""Corporate DB tool executor.

Core executes corp_db_search by calling tools-api over internal network.
No database credentials are stored in core or sandbox.
"""

from __future__ import annotations

import asyncio
import aiohttp
import json
import logging
import os
from time import perf_counter

from models import ToolResult, ToolContext
from observability import REQUEST_ID as OBS_REQUEST_ID
from opentelemetry import trace
from tool_output_policy import (
    RUNTIME_PAYLOAD_FORMAT_FULL_JSON,
    build_output_contract_metadata,
    serialize_runtime_json,
)


logger = logging.getLogger(__name__)

COMPANY_FACT_QUERY_HINTS = (
    "сайт", "адрес", "офис", "контакт", "телефон", "email", "e-mail", "почт",
    "реквизит", "инн", "кпп", "огрн", "соцсет", "телеграм", "telegram",
    "youtube", "ютуб", "vk", "вконтакте", "канал", "год основания",
    "основан", "основана", "сколько лет компании", "о компании", "гаранти",
    "сервис", "консультац",
)
BENCH_ARTIFACT_LIST_LIMIT = 5
BENCH_ARTIFACT_STRING_LIMIT = 320
COMPANY_FACT_RESULT_LIMIT = 5


def _timeout_budget_seconds() -> dict[str, float]:
    connect = float(os.getenv("CORP_DB_SEARCH_TIMEOUT_CONNECT_S", "5"))
    read = float(os.getenv("CORP_DB_SEARCH_TIMEOUT_READ_S", "40"))
    total = float(os.getenv("CORP_DB_SEARCH_TIMEOUT_TOTAL_S", "45"))
    if total < max(connect, read):
        total = max(connect, read)
    return {
        "connect": connect,
        "read": read,
        "total": total,
    }


def _aiohttp_timeout(budget: dict[str, float]) -> aiohttp.ClientTimeout:
    return aiohttp.ClientTimeout(
        total=budget["total"],
        connect=budget["connect"],
        sock_connect=budget["connect"],
        sock_read=budget["read"],
    )


def _format_corp_db_exception(exc: Exception, budget: dict[str, float]) -> str:
    exc_name = type(exc).__name__
    budget_text = (
        f"timeout_budget={{connect:{budget['connect']}s,read:{budget['read']}s,total:{budget['total']}s}}"
    )
    if isinstance(exc, asyncio.TimeoutError):
        return f"corp_db_search error: {exc_name}: request timed out; {budget_text}"
    detail = str(exc).strip() or repr(exc)
    return f"corp_db_search error: {exc_name}: {detail}; {budget_text}"


def _get_tracer():
    return trace.get_tracer("core.tools.corp_db")


def _normalize_text(value: object) -> str:
    return " ".join(str(value or "").lower().split())


def _truncate_text(value: object, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _is_company_fact_kb_search(args: dict | None, data: object) -> bool:
    if not isinstance(args, dict) or not isinstance(data, dict):
        return False
    if str(args.get("kind") or "") != "hybrid_search":
        return False
    if str(args.get("profile") or "") != "kb_search":
        return False

    entity_types = args.get("entity_types") or []
    if isinstance(entity_types, list) and any(str(item).lower() == "company" for item in entity_types):
        return True

    query = _normalize_text(args.get("query"))
    return any(token in query for token in COMPANY_FACT_QUERY_HINTS)


def _compact_company_fact_payload(data: dict) -> dict:
    results = data.get("results") if isinstance(data.get("results"), list) else []
    compact_results: list[dict] = []

    for row in results[:COMPANY_FACT_RESULT_LIMIT]:
        if not isinstance(row, dict):
            continue
        metadata = row.get("metadata") if isinstance(row.get("metadata"), dict) else {}
        compact_results.append(
            {
                "entity_type": row.get("entity_type"),
                "document_title": row.get("document_title") or metadata.get("document_title"),
                "heading": row.get("heading") or row.get("title"),
                "preview": _truncate_text(row.get("preview"), 280),
                "source_file": metadata.get("source_file"),
                "score": row.get("score"),
            }
        )

    return {
        "status": data.get("status"),
        "kind": data.get("kind"),
        "query": data.get("query"),
        "filters": data.get("filters") or {},
        "result_count": len(results),
        "result_format": "compact_company_fact_v1",
        "results": compact_results,
    }


def _serialize_runtime_payload(data: object) -> str:
    """Runtime path always receives full-fidelity JSON."""
    return serialize_runtime_json(data)


def _compact_bench_value(value: object, depth: int = 0) -> object:
    if depth >= 4:
        return _truncate_text(value, BENCH_ARTIFACT_STRING_LIMIT)
    if isinstance(value, dict):
        compact: dict[str, object] = {}
        for key, item in value.items():
            if item in (None, "", [], {}):
                continue
            compact[str(key)] = _compact_bench_value(item, depth + 1)
        return compact
    if isinstance(value, list):
        return [_compact_bench_value(item, depth + 1) for item in value[:BENCH_ARTIFACT_LIST_LIMIT]]
    if isinstance(value, str):
        return _truncate_text(value, BENCH_ARTIFACT_STRING_LIMIT)
    return value


def _build_bench_artifact(args: dict | None, data: object) -> dict | None:
    if not isinstance(data, dict):
        return None
    kind = str((args or {}).get("kind") or data.get("kind") or "")
    payload = _compact_company_fact_payload(data) if _is_company_fact_kb_search(args, data) else _compact_bench_value(data)
    return {
        "tool": "corp_db_search",
        "success": True,
        "kind": kind or None,
        "captured_from": "tool_result_metadata",
        "payload": payload,
    }


async def tool_corp_db_search(args: dict, ctx: ToolContext) -> ToolResult:
    tools_api_url = os.getenv("TOOLS_API_URL", "http://tools-api:8100")
    budget = _timeout_budget_seconds()

    request_id = OBS_REQUEST_ID.get("-")
    headers = {
        "X-User-Id": str(ctx.user_id),
        "X-Chat-Type": str(ctx.chat_type),
    }
    if request_id and request_id != "-":
        headers["X-Request-Id"] = request_id

    started_at = perf_counter()
    with _get_tracer().start_as_current_span("tool.corp_db_search") as span:
        span.set_attribute("corp_db.kind", str(args.get("kind") or "unknown"))
        span.set_attribute("corp_db.timeout.connect_s", budget["connect"])
        span.set_attribute("corp_db.timeout.read_s", budget["read"])
        span.set_attribute("corp_db.timeout.total_s", budget["total"])
        if request_id and request_id != "-":
            span.set_attribute("request_id", request_id)

        try:
            timeout = _aiohttp_timeout(budget)
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.post(
                    f"{tools_api_url}/corp-db/search",
                    json=args,
                    headers=headers,
                ) as resp:
                    text = await resp.text()
                    span.set_attribute("http.status_code", resp.status)

                    if resp.status != 200:
                        error = f"corp_db_search failed: {resp.status}: {text[:300]}"
                        logger.warning("%s", error)
                        span.set_attribute("corp_db.status", "http_error")
                        return ToolResult(False, error=error)

                    try:
                        data = json.loads(text)
                        span.set_attribute("corp_db.status", str(data.get("status", "success")) if isinstance(data, dict) else "success")
                        bench_payload_format = "compact_company_fact_v1" if _is_company_fact_kb_search(args, data) else "compact_bench_value_v1"
                        span.set_attribute("corp_db.runtime_payload_format", RUNTIME_PAYLOAD_FORMAT_FULL_JSON)
                        span.set_attribute("corp_db.bench_payload_format", bench_payload_format)
                        metadata = build_output_contract_metadata(
                            bench_artifact=_build_bench_artifact(args, data),
                            runtime_payload_format=RUNTIME_PAYLOAD_FORMAT_FULL_JSON,
                            bench_payload_format=bench_payload_format,
                        )
                        return ToolResult(True, output=_serialize_runtime_payload(data), metadata=metadata)
                    except Exception:
                        span.set_attribute("corp_db.status", "success")
                        return ToolResult(True, output=text)
        except Exception as exc:
            duration_ms = (perf_counter() - started_at) * 1000
            error = _format_corp_db_exception(exc, budget)
            logger.warning(
                "corp_db_search transport failure kind=%s duration_ms=%.2f error=%s",
                args.get("kind"),
                duration_ms,
                error,
            )
            span.record_exception(exc)
            span.set_attribute("corp_db.status", "transport_error")
            span.set_attribute("corp_db.duration_ms", duration_ms)
            return ToolResult(False, error=error)
