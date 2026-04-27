"""Shared observability primitives for FastAPI services."""

from __future__ import annotations

import importlib
import logging
import os
import uuid
from contextlib import contextmanager
from contextvars import ContextVar
from time import perf_counter
from typing import Any, Iterator, MutableMapping

from fastapi import FastAPI, Request
from fastapi.responses import Response
from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract, inject
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor
from opentelemetry.trace import Status, StatusCode
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    GCCollector,
    Histogram,
    PlatformCollector,
    ProcessCollector,
    generate_latest,
)


REQUEST_ID: ContextVar[str] = ContextVar("request_id", default="-")
CORRELATION_CONTEXT: ContextVar[dict[str, str] | None] = ContextVar("correlation_context", default=None)
ACTIVE_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "service")
SERVICE_NAMESPACE = os.getenv("OTEL_SERVICE_NAMESPACE", "totosha")
DEPLOYMENT_ENVIRONMENT = os.getenv("OTEL_DEPLOYMENT_ENVIRONMENT", "local")
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")
INITIALIZED = False
LATENCY_BUCKETS_MS = (
    5,
    10,
    25,
    50,
    100,
    250,
    500,
    1000,
    2500,
    5000,
    10000,
    15000,
    20000,
    30000,
    45000,
    60000,
)
CORRELATION_FIELDS = (
    "request_source",
    "selected_route_id",
    "selected_route_family",
    "selected_route_kind",
    "selected_source",
    "knowledge_route_id",
    "document_id",
    "tool_name",
    "tool_call_id",
    "tool_call_seq",
    "tool_status",
    "retrieval_phase",
    "retrieval_evidence_status",
    "retrieval_close_reason",
    "application_recovery_outcome",
    "route_selector_status",
    "routing_catalog_version",
    "routing_guardrail_hits",
    "guardrail_blocked_tool",
    "finalizer_mode",
)
CORRELATION_FIELD_DEFAULTS = {
    "request_source": "-",
    "selected_route_id": "-",
    "selected_route_family": "-",
    "selected_route_kind": "-",
    "selected_source": "unknown",
    "knowledge_route_id": "-",
    "document_id": "-",
    "tool_name": "-",
    "tool_call_id": "-",
    "tool_call_seq": "-",
    "tool_status": "-",
    "retrieval_phase": "-",
    "retrieval_evidence_status": "-",
    "retrieval_close_reason": "-",
    "application_recovery_outcome": "-",
    "route_selector_status": "-",
    "routing_catalog_version": "-",
    "routing_guardrail_hits": "0",
    "guardrail_blocked_tool": "-",
    "finalizer_mode": "-",
}
SPAN_ATTRIBUTE_NAMES = {
    "request_source": "request_source",
    "selected_route_id": "selected_route_id",
    "selected_route_family": "selected_route_family",
    "selected_route_kind": "selected_route_kind",
    "selected_source": "selected_source",
    "knowledge_route_id": "knowledge_route_id",
    "document_id": "document_id",
    "tool_name": "tool_name",
    "tool_call_id": "tool_call_id",
    "tool_call_seq": "tool_call_seq",
    "tool_status": "tool_status",
    "retrieval_phase": "retrieval_phase",
    "retrieval_evidence_status": "retrieval_evidence_status",
    "retrieval_close_reason": "retrieval_close_reason",
    "application_recovery_outcome": "application_recovery_outcome",
    "route_selector_status": "route_selector_status",
    "routing_catalog_version": "routing_catalog_version",
    "routing_guardrail_hits": "routing_guardrail_hits",
    "guardrail_blocked_tool": "guardrail_blocked_tool",
    "finalizer_mode": "finalizer_mode",
}

REGISTRY = CollectorRegistry()
ProcessCollector(registry=REGISTRY)
PlatformCollector(registry=REGISTRY)
GCCollector(registry=REGISTRY)

HTTP_SERVER_REQUESTS_TOTAL = Counter(
    "http_server_requests_total",
    "Total HTTP requests handled by the service.",
    labelnames=("service", "method", "route", "status"),
    registry=REGISTRY,
)
HTTP_SERVER_DURATION_MS = Histogram(
    "http_server_duration_milliseconds",
    "HTTP request duration in milliseconds.",
    labelnames=("service", "method", "route", "status"),
    registry=REGISTRY,
    buckets=LATENCY_BUCKETS_MS,
)
CHAT_CHANNEL_REQUESTS_TOTAL = Counter(
    "chat_channel_requests_total",
    "Chat requests grouped by logical channel source and status.",
    labelnames=("service", "request_source", "status"),
    registry=REGISTRY,
)
CHAT_CHANNEL_DURATION_MS = Histogram(
    "chat_channel_duration_milliseconds",
    "Chat request duration grouped by logical channel source and status.",
    labelnames=("service", "request_source", "status"),
    registry=REGISTRY,
    buckets=LATENCY_BUCKETS_MS,
)
RETRIEVAL_ROUTE_REQUESTS_TOTAL = Counter(
    "retrieval_route_requests_total",
    "Requests grouped by selected route and retrieval identifiers.",
    labelnames=(
        "service",
        "status",
        "selected_route_id",
        "selected_route_family",
        "selected_route_kind",
        "selected_source",
        "knowledge_route_id",
        "document_id",
        "retrieval_phase",
        "retrieval_evidence_status",
        "finalizer_mode",
    ),
    registry=REGISTRY,
)
RETRIEVAL_ROUTE_DURATION_MS = Histogram(
    "retrieval_route_duration_milliseconds",
    "HTTP request duration grouped by selected route and retrieval identifiers.",
    labelnames=(
        "service",
        "status",
        "selected_route_id",
        "selected_route_family",
        "selected_route_kind",
        "selected_source",
        "knowledge_route_id",
        "document_id",
        "retrieval_phase",
        "retrieval_evidence_status",
        "finalizer_mode",
    ),
    registry=REGISTRY,
    buckets=LATENCY_BUCKETS_MS,
)
RETRIEVAL_GUARDRAIL_BLOCKS_TOTAL = Counter(
    "retrieval_guardrail_blocks_total",
    "Guardrail block count grouped by selected route and blocked tool.",
    labelnames=(
        "service",
        "selected_route_id",
        "selected_route_family",
        "selected_route_kind",
        "selected_source",
        "knowledge_route_id",
        "document_id",
        "blocked_tool",
    ),
    registry=REGISTRY,
)
TOOL_EXECUTIONS_TOTAL = Counter(
    "tool_executions_total",
    "Tool executions grouped by tool status and retrieval identifiers.",
    labelnames=(
        "service",
        "tool_name",
        "tool_status",
        "selected_route_id",
        "selected_route_family",
        "selected_route_kind",
        "selected_source",
        "knowledge_route_id",
        "document_id",
        "retrieval_phase",
    ),
    registry=REGISTRY,
)
TOOL_EXECUTION_DURATION_MS = Histogram(
    "tool_execution_duration_milliseconds",
    "Tool execution duration grouped by tool status and retrieval identifiers.",
    labelnames=(
        "service",
        "tool_name",
        "tool_status",
        "selected_route_id",
        "selected_route_family",
        "selected_route_kind",
        "selected_source",
        "knowledge_route_id",
        "document_id",
        "retrieval_phase",
    ),
    registry=REGISTRY,
    buckets=LATENCY_BUCKETS_MS,
)
LLM_CONTEXT_PRETRIM_CHARS = Histogram(
    "llm_context_pretrim_characters",
    "Estimated LLM context size before trimming, grouped by call stage.",
    labelnames=("service", "purpose", "hard_stop"),
    registry=REGISTRY,
    buckets=(256, 512, 1024, 2048, 4096, 8192, 12000, 16000, 24000, 32000, 40000, 50000, 65000, 80000),
)
LLM_CONTEXT_POSTTRIM_CHARS = Histogram(
    "llm_context_posttrim_characters",
    "Estimated LLM context size after trimming, grouped by call stage.",
    labelnames=("service", "purpose", "hard_stop"),
    registry=REGISTRY,
    buckets=(256, 512, 1024, 2048, 4096, 8192, 12000, 16000, 24000, 32000, 40000, 50000, 65000, 80000),
)
LLM_CONTEXT_REMOVED_MESSAGES = Histogram(
    "llm_context_removed_messages",
    "Number of messages removed while fitting context to budget.",
    labelnames=("service", "purpose", "hard_stop"),
    registry=REGISTRY,
    buckets=(0, 1, 2, 3, 5, 8, 13, 21, 34),
)
LLM_CONTEXT_TRIM_HARD_STOPS_TOTAL = Counter(
    "llm_context_trim_hard_stops_total",
    "Count of LLM requests that could not be brought under the context budget.",
    labelnames=("service", "purpose"),
    registry=REGISTRY,
)


def _normalize_context_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (list, tuple, set)):
        return ",".join(str(item).strip() for item in value if str(item).strip())
    return str(value).strip()


def get_correlation_context() -> dict[str, str]:
    current = dict(CORRELATION_CONTEXT.get() or {})
    context = dict(CORRELATION_FIELD_DEFAULTS)
    context.update({key: value for key, value in current.items() if value})
    return context


def _apply_context_to_span(context: dict[str, str]) -> None:
    span = trace.get_current_span()
    for key, attribute_name in SPAN_ATTRIBUTE_NAMES.items():
        value = context.get(key, CORRELATION_FIELD_DEFAULTS.get(key, ""))
        if key == "routing_guardrail_hits":
            try:
                span.set_attribute(attribute_name, int(value or "0"))
            except Exception:
                span.set_attribute(attribute_name, 0)
            continue
        span.set_attribute(attribute_name, value or CORRELATION_FIELD_DEFAULTS.get(key, "-"))


def update_correlation_context(**fields: Any) -> dict[str, str]:
    updated = dict(CORRELATION_CONTEXT.get() or {})
    for key, value in fields.items():
        if key not in CORRELATION_FIELD_DEFAULTS:
            continue
        normalized = _normalize_context_value(value)
        if normalized:
            updated[key] = normalized
        else:
            updated.pop(key, None)
    CORRELATION_CONTEXT.set(updated)
    _apply_context_to_span(get_correlation_context())
    return get_correlation_context()


@contextmanager
def correlation_scope(**fields: Any) -> Iterator[None]:
    token = CORRELATION_CONTEXT.set(dict(CORRELATION_CONTEXT.get() or {}))
    try:
        update_correlation_context(**fields)
        yield
    finally:
        CORRELATION_CONTEXT.reset(token)
        _apply_context_to_span(get_correlation_context())


def record_span_event(name: str, **fields: Any) -> None:
    span = trace.get_current_span()
    attributes: dict[str, Any] = {}
    for key, value in fields.items():
        if key not in CORRELATION_FIELD_DEFAULTS:
            continue
        normalized = _normalize_context_value(value)
        if not normalized:
            continue
        attributes[SPAN_ATTRIBUTE_NAMES.get(key, key)] = (
            int(normalized) if key == "routing_guardrail_hits" and normalized.isdigit() else normalized
        )
    try:
        span.add_event(name, attributes=attributes)
    except Exception:
        return None


def _metric_label(context: dict[str, str], key: str, *, default: str = "none") -> str:
    value = context.get(key, "").strip()
    if value in {"", "-"}:
        return default
    return value


def observe_request_correlation(duration_ms: float, status: str) -> None:
    context = get_correlation_context()
    if (
        context["selected_route_id"] == "-"
        and context["knowledge_route_id"] == "-"
        and context["document_id"] == "-"
        and context["selected_source"] == "unknown"
    ):
        return
    labels = (
        ACTIVE_SERVICE_NAME,
        status,
        _metric_label(context, "selected_route_id"),
        _metric_label(context, "selected_route_family"),
        _metric_label(context, "selected_route_kind"),
        _metric_label(context, "selected_source", default="unknown"),
        _metric_label(context, "knowledge_route_id"),
        _metric_label(context, "document_id"),
        _metric_label(context, "retrieval_phase"),
        _metric_label(context, "retrieval_evidence_status"),
        _metric_label(context, "finalizer_mode"),
    )
    RETRIEVAL_ROUTE_REQUESTS_TOTAL.labels(*labels).inc()
    RETRIEVAL_ROUTE_DURATION_MS.labels(*labels).observe(duration_ms)
    guardrail_hits = 0
    try:
        guardrail_hits = int(context.get("routing_guardrail_hits", "0") or "0")
    except ValueError:
        guardrail_hits = 0
    if guardrail_hits > 0:
        RETRIEVAL_GUARDRAIL_BLOCKS_TOTAL.labels(
            ACTIVE_SERVICE_NAME,
            _metric_label(context, "selected_route_id"),
            _metric_label(context, "selected_route_family"),
            _metric_label(context, "selected_route_kind"),
            _metric_label(context, "selected_source", default="unknown"),
            _metric_label(context, "knowledge_route_id"),
            _metric_label(context, "document_id"),
            _metric_label(context, "guardrail_blocked_tool"),
        ).inc(guardrail_hits)


def observe_tool_execution(tool_name: str, tool_status: str, duration_ms: float) -> None:
    context = get_correlation_context()
    labels = (
        ACTIVE_SERVICE_NAME,
        tool_name,
        tool_status,
        _metric_label(context, "selected_route_id"),
        _metric_label(context, "selected_route_family"),
        _metric_label(context, "selected_route_kind"),
        _metric_label(context, "selected_source", default="unknown"),
        _metric_label(context, "knowledge_route_id"),
        _metric_label(context, "document_id"),
        _metric_label(context, "retrieval_phase"),
    )
    TOOL_EXECUTIONS_TOTAL.labels(*labels).inc()
    TOOL_EXECUTION_DURATION_MS.labels(*labels).observe(duration_ms)


def observe_context_trim(
    *,
    purpose: str,
    pre_chars: int,
    post_chars: int,
    removed_messages: int,
    hard_stop: bool,
) -> None:
    purpose_label = (purpose or "agent_loop").strip() or "agent_loop"
    hard_stop_label = "true" if hard_stop else "false"
    labels = (ACTIVE_SERVICE_NAME, purpose_label, hard_stop_label)
    LLM_CONTEXT_PRETRIM_CHARS.labels(*labels).observe(max(0, int(pre_chars)))
    LLM_CONTEXT_POSTTRIM_CHARS.labels(*labels).observe(max(0, int(post_chars)))
    LLM_CONTEXT_REMOVED_MESSAGES.labels(*labels).observe(max(0, int(removed_messages)))
    if hard_stop:
        LLM_CONTEXT_TRIM_HARD_STOPS_TOTAL.labels(ACTIVE_SERVICE_NAME, purpose_label).inc()


def observe_chat_request(request_source: str, status: str, duration_ms: float) -> None:
    source = (request_source or "unknown").strip() or "unknown"
    CHAT_CHANNEL_REQUESTS_TOTAL.labels(ACTIVE_SERVICE_NAME, source, status).inc()
    CHAT_CHANNEL_DURATION_MS.labels(ACTIVE_SERVICE_NAME, source, status).observe(duration_ms)


class _RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.service_name = ACTIVE_SERVICE_NAME
        record.request_id = REQUEST_ID.get("-")
        context = get_correlation_context()
        for key in CORRELATION_FIELDS:
            setattr(record, key, context.get(key, CORRELATION_FIELD_DEFAULTS[key]))
        span = trace.get_current_span()
        span_context = span.get_span_context()
        if span_context and span_context.is_valid:
            record.trace_id = format(span_context.trace_id, "032x")
            record.span_id = format(span_context.span_id, "016x")
        else:
            record.trace_id = "-"
            record.span_id = "-"
        return True


def _instrument_optional(module_name: str, class_name: str) -> None:
    try:
        module = importlib.import_module(module_name)
        instrumentor = getattr(module, class_name)
        instrumentor().instrument()
    except Exception:
        pass


def setup_observability(service_name: str) -> None:
    global ACTIVE_SERVICE_NAME, INITIALIZED
    ACTIVE_SERVICE_NAME = service_name
    if INITIALIZED:
        return

    root = logging.getLogger()
    if not root.handlers:
        logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO").upper())

    formatter = logging.Formatter(
        "[%(service_name)s] request_id=%(request_id)s trace_id=%(trace_id)s "
        "span_id=%(span_id)s request_source=%(request_source)s selected_route_id=%(selected_route_id)s "
        "selected_route_family=%(selected_route_family)s selected_route_kind=%(selected_route_kind)s "
        "selected_source=%(selected_source)s knowledge_route_id=%(knowledge_route_id)s "
        "document_id=%(document_id)s tool_name=%(tool_name)s tool_call_id=%(tool_call_id)s "
        "tool_call_seq=%(tool_call_seq)s tool_status=%(tool_status)s retrieval_phase=%(retrieval_phase)s "
        "retrieval_evidence_status=%(retrieval_evidence_status)s retrieval_close_reason=%(retrieval_close_reason)s "
        "route_selector_status=%(route_selector_status)s routing_catalog_version=%(routing_catalog_version)s "
        "routing_guardrail_hits=%(routing_guardrail_hits)s guardrail_blocked_tool=%(guardrail_blocked_tool)s "
        "finalizer_mode=%(finalizer_mode)s %(name)s: %(message)s"
    )
    request_filter = _RequestContextFilter()
    for handler in root.handlers:
        handler.setFormatter(formatter)
        handler.addFilter(request_filter)

    logging.getLogger("opentelemetry").setLevel(logging.WARNING)

    if OTLP_ENDPOINT:
        resource = Resource.create(
            {
                "service.name": ACTIVE_SERVICE_NAME,
                "service.namespace": SERVICE_NAMESPACE,
                "deployment.environment": DEPLOYMENT_ENVIRONMENT,
            }
        )

        tracer_provider = TracerProvider(resource=resource)
        tracer_provider.add_span_processor(
            BatchSpanProcessor(OTLPSpanExporter(endpoint=f"{OTLP_ENDPOINT}/v1/traces"))
        )
        trace.set_tracer_provider(tracer_provider)

        logger_provider = LoggerProvider(resource=resource)
        logger_provider.add_log_record_processor(
            BatchLogRecordProcessor(OTLPLogExporter(endpoint=f"{OTLP_ENDPOINT}/v1/logs"))
        )
        set_logger_provider(logger_provider)
        root.addHandler(LoggingHandler(level=logging.INFO, logger_provider=logger_provider))

        _instrument_optional(
            "opentelemetry.instrumentation.aiohttp_client",
            "AioHttpClientInstrumentor",
        )
        _instrument_optional(
            "opentelemetry.instrumentation.httpx",
            "HTTPXClientInstrumentor",
        )

    INITIALIZED = True


def inject_trace_context(
    headers: MutableMapping[str, str] | None = None,
    *,
    request_id: str | None = None,
) -> dict[str, str]:
    carrier = dict(headers or {})
    inject(carrier)
    resolved_request_id = request_id or REQUEST_ID.get("-")
    if resolved_request_id and resolved_request_id != "-":
        carrier.setdefault("X-Request-Id", resolved_request_id)
    return carrier


def instrument_fastapi(app: FastAPI) -> None:
    tracer = trace.get_tracer(f"{ACTIVE_SERVICE_NAME}.http")

    @app.middleware("http")
    async def _middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-Id", uuid.uuid4().hex)
        token = REQUEST_ID.set(request_id)
        correlation_token = CORRELATION_CONTEXT.set({})
        started_at = perf_counter()
        route = request.scope.get("route")
        route_label = getattr(route, "path", request.url.path)
        method = request.method
        status_code = 500
        response = None

        with tracer.start_as_current_span("api.request", context=extract(dict(request.headers))) as span:
            span.set_attribute("http.method", method)
            span.set_attribute("http.route", route_label)
            span.set_attribute("http.target", request.url.path)
            span.set_attribute("request_id", request_id)

            try:
                response = await call_next(request)
                status_code = response.status_code
                span.set_attribute("http.status_code", status_code)
            except Exception as exc:
                span.record_exception(exc)
                span.set_status(Status(StatusCode.ERROR, str(exc)))
                logging.getLogger(f"{ACTIVE_SERVICE_NAME}.http").exception("HTTP request failed")
                raise
            finally:
                duration_ms = (perf_counter() - started_at) * 1000
                status = str(status_code)
                HTTP_SERVER_REQUESTS_TOTAL.labels(ACTIVE_SERVICE_NAME, method, route_label, status).inc()
                HTTP_SERVER_DURATION_MS.labels(ACTIVE_SERVICE_NAME, method, route_label, status).observe(duration_ms)
                observe_request_correlation(duration_ms, status)
                logging.getLogger(f"{ACTIVE_SERVICE_NAME}.http").info(
                    "HTTP request completed method=%s route=%s status=%s duration_ms=%.2f",
                    method,
                    route_label,
                    status,
                    duration_ms,
                )
                CORRELATION_CONTEXT.reset(correlation_token)
                REQUEST_ID.reset(token)

        if response is not None:
            response.headers["X-Request-Id"] = request_id
            return response
        raise RuntimeError("response was not created")

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(content=generate_latest(REGISTRY), headers={"Content-Type": CONTENT_TYPE_LATEST})
