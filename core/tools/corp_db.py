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


logger = logging.getLogger(__name__)


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


def _format_result_payload(data: object) -> str:
    """Return the full tools-api payload without truncation or field loss."""
    return json.dumps(data, ensure_ascii=False, indent=2)


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
                        return ToolResult(True, output=_format_result_payload(data))
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
