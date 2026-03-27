"""Shared observability primitives for FastAPI services."""

from __future__ import annotations

import importlib
import logging
import os
import uuid
from contextvars import ContextVar
from time import perf_counter

from fastapi import FastAPI, Request
from fastapi.responses import Response
from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.propagate import extract
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
ACTIVE_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "service")
SERVICE_NAMESPACE = os.getenv("OTEL_SERVICE_NAMESPACE", "totosha")
DEPLOYMENT_ENVIRONMENT = os.getenv("OTEL_DEPLOYMENT_ENVIRONMENT", "local")
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")
INITIALIZED = False

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
    buckets=(5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000),
)


class _RequestContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.service_name = ACTIVE_SERVICE_NAME
        record.request_id = REQUEST_ID.get("-")
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
        "span_id=%(span_id)s %(name)s: %(message)s"
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

    INITIALIZED = True


def instrument_fastapi(app: FastAPI) -> None:
    tracer = trace.get_tracer(f"{ACTIVE_SERVICE_NAME}.http")

    @app.middleware("http")
    async def _middleware(request: Request, call_next):
        request_id = request.headers.get("X-Request-Id", uuid.uuid4().hex)
        token = REQUEST_ID.set(request_id)
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
                logging.getLogger(f"{ACTIVE_SERVICE_NAME}.http").info(
                    "HTTP request completed method=%s route=%s status=%s duration_ms=%.2f",
                    method,
                    route_label,
                    status,
                    duration_ms,
                )
                REQUEST_ID.reset(token)

        if response is not None:
            response.headers["X-Request-Id"] = request_id
            return response
        raise RuntimeError("response was not created")

    @app.get("/metrics", include_in_schema=False)
    async def metrics() -> Response:
        return Response(content=generate_latest(REGISTRY), headers={"Content-Type": CONTENT_TYPE_LATEST})
