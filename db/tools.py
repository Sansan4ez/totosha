import logging
from time import perf_counter
from typing import Any

from opentelemetry import metrics, trace

from db import hybrid_search

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)
meter = metrics.get_meter(__name__)
search_duration = meter.create_histogram(
    "tool_search_knowledge_base_duration_ms",
    unit="ms",
    description="End-to-end duration of the ADK KB search tool",
)
search_calls = meter.create_counter(
    "tool_search_knowledge_base_calls",
    description="Total invocations of the ADK KB search tool",
)


async def search_knowledge_base(query: str) -> dict[str, Any]:
    """Search the knowledge base and return structured results for the agent."""
    started_at = perf_counter()
    with tracer.start_as_current_span("tool.search_knowledge_base") as span:
        span.set_attribute("tool.name", "search_knowledge_base")
        span.set_attribute("kb.match_count", 3)
        search_calls.add(1, {"tool.name": "search_knowledge_base"})

        try:
            results = await hybrid_search(query, match_count=3)
        except Exception as exc:
            span.record_exception(exc)
            logger.exception("Knowledge base search failed")
            search_duration.record(
                (perf_counter() - started_at) * 1000,
                {
                    "tool.name": "search_knowledge_base",
                    "status": "error",
                },
            )
            return {
                "status": "error",
                "query": query,
                "results": [],
                "message": "Knowledge base is currently unavailable.",
            }

        if not results:
            search_duration.record(
                (perf_counter() - started_at) * 1000,
                {
                    "tool.name": "search_knowledge_base",
                    "status": "empty",
                },
            )
            return {
                "status": "empty",
                "query": query,
                "results": [],
            }

        span.set_attribute("kb.result_count", len(results))
        search_duration.record(
            (perf_counter() - started_at) * 1000,
            {
                "tool.name": "search_knowledge_base",
                "status": "success",
            },
        )
        return {
            "status": "success",
            "query": query,
            "results": results,
        }
