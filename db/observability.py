"""Observability helpers for corp-db worker flows."""

from __future__ import annotations

import importlib
import logging
import os

from opentelemetry import trace
from opentelemetry._logs import set_logger_provider
from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
from opentelemetry.sdk.resources import Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor


ACTIVE_SERVICE_NAME = os.getenv("OTEL_SERVICE_NAME", "corp-db-worker")
SERVICE_NAMESPACE = os.getenv("OTEL_SERVICE_NAMESPACE", "totosha")
DEPLOYMENT_ENVIRONMENT = os.getenv("OTEL_DEPLOYMENT_ENVIRONMENT", "local")
OTLP_ENDPOINT = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").rstrip("/")
INITIALIZED = False


class _ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.service_name = ACTIVE_SERVICE_NAME
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
        "[%(service_name)s] trace_id=%(trace_id)s span_id=%(span_id)s %(name)s: %(message)s"
    )
    context_filter = _ContextFilter()
    for handler in root.handlers:
        handler.setFormatter(formatter)
        handler.addFilter(context_filter)

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
            "opentelemetry.instrumentation.httpx",
            "HTTPXClientInstrumentor",
        )

    INITIALIZED = True
