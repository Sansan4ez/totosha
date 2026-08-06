import importlib.util
import logging
import sys
import types
import unittest
from pathlib import Path

_MODULE_PATH = Path(__file__).resolve().parents[1] / "observability.py"
_SPEC = importlib.util.spec_from_file_location("core_observability_test_module", _MODULE_PATH)
assert _SPEC and _SPEC.loader
observability = importlib.util.module_from_spec(_SPEC)


class _DummySpanContext:
    is_valid = False
    trace_id = 0
    span_id = 0


class _DummySpan:
    def get_span_context(self):
        return _DummySpanContext()

    def set_attribute(self, *args, **kwargs):
        return None


class _DummyMetric:
    def __init__(self, *args, **kwargs):
        self.labelnames = tuple(kwargs.get("labelnames", ()))
        self.label_calls = []

    def labels(self, *args, **kwargs):
        self.label_calls.append(args)
        return self

    def inc(self, *args, **kwargs):
        return None

    def observe(self, *args, **kwargs):
        return None


_stub_modules = {
    "fastapi": types.SimpleNamespace(FastAPI=object, Request=object),
    "fastapi.responses": types.SimpleNamespace(Response=object),
    "opentelemetry": types.SimpleNamespace(trace=types.SimpleNamespace(get_current_span=lambda: _DummySpan())),
    "opentelemetry.trace": types.SimpleNamespace(Status=object, StatusCode=types.SimpleNamespace(ERROR="ERROR")),
    "opentelemetry._logs": types.SimpleNamespace(set_logger_provider=lambda *args, **kwargs: None),
    "opentelemetry.exporter.otlp.proto.http._log_exporter": types.SimpleNamespace(OTLPLogExporter=object),
    "opentelemetry.exporter.otlp.proto.http.trace_exporter": types.SimpleNamespace(OTLPSpanExporter=object),
    "opentelemetry.propagate": types.SimpleNamespace(extract=lambda *args, **kwargs: {}, inject=lambda *args, **kwargs: None),
    "opentelemetry.sdk._logs": types.SimpleNamespace(LoggerProvider=object, LoggingHandler=object),
    "opentelemetry.sdk._logs.export": types.SimpleNamespace(BatchLogRecordProcessor=object),
    "opentelemetry.sdk.resources": types.SimpleNamespace(Resource=types.SimpleNamespace(create=lambda *args, **kwargs: None)),
    "opentelemetry.sdk.trace": types.SimpleNamespace(TracerProvider=object),
    "opentelemetry.sdk.trace.export": types.SimpleNamespace(BatchSpanProcessor=object),
    "prometheus_client": types.SimpleNamespace(
        CONTENT_TYPE_LATEST="text/plain",
        CollectorRegistry=_DummyMetric,
        Counter=_DummyMetric,
        GCCollector=lambda *args, **kwargs: None,
        Histogram=_DummyMetric,
        PlatformCollector=lambda *args, **kwargs: None,
        ProcessCollector=lambda *args, **kwargs: None,
        generate_latest=lambda *args, **kwargs: b"",
    ),
}
_saved_modules = {name: sys.modules.get(name) for name in _stub_modules}
try:
    sys.modules.update(_stub_modules)
    _SPEC.loader.exec_module(observability)
finally:
    for name, original in _saved_modules.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


class Rfc027ObservabilityTests(unittest.TestCase):
    def test_request_context_filter_populates_rfc027_route_identity_fields(self):
        observability.update_correlation_context(
            request_source="bot",
            selected_route_id="corp_db.certificate_by_lamp_name",
            selected_route_family="corp_db.documents_by_lamp_name",
            selected_business_family_id="documents",
            selected_leaf_route_id="certificate_by_lamp_name",
            route_stage="stage3_optimized",
            route_arg_validation_status="ok",
            selected_route_kind="corp_table",
            selected_source="corp_db",
            route_selector_status="valid",
            route_selector_confidence="high",
            used_fallback_scope="family_local",
            used_fallback_route_id="corp_db.documents_by_lamp_name",
            fallback_family_id="documents",
            finalizer_mode="llm",
        )
        record = logging.LogRecord(
            name="test.observability",
            level=logging.INFO,
            pathname=__file__,
            lineno=1,
            msg="hello",
            args=(),
            exc_info=None,
        )
        request_filter = observability._RequestContextFilter()
        self.assertTrue(request_filter.filter(record))

        self.assertEqual(record.selected_business_family_id, "documents")
        self.assertEqual(record.selected_leaf_route_id, "certificate_by_lamp_name")
        self.assertEqual(record.route_stage, "stage3_optimized")
        self.assertEqual(record.route_arg_validation_status, "ok")
        self.assertEqual(record.route_selector_confidence, "high")
        self.assertEqual(record.used_fallback_scope, "family_local")
        self.assertEqual(record.fallback_family_id, "documents")
        self.assertEqual(record.finalizer_mode, "llm")

    def test_correlation_context_defaults_expose_new_rfc027_fields(self):
        context = observability.get_correlation_context()
        for key in (
            "selected_business_family_id",
            "selected_leaf_route_id",
            "route_stage",
            "route_arg_validation_status",
            "route_selector_confidence",
            "used_fallback_scope",
            "fallback_family_id",
            "finalizer_mode",
        ):
            self.assertIn(key, context)

    def test_bounded_label_preserves_known_value(self):
        self.assertEqual(
            observability._bounded_label(
                "corp_kb.company_common",
                observability.KNOWN_KNOWLEDGE_ROUTE_IDS,
            ),
            "corp_kb.company_common",
        )

    def test_bounded_label_collapses_unknown_value(self):
        self.assertEqual(
            observability._bounded_label(
                "corp_kb.user_supplied_route",
                observability.KNOWN_KNOWLEDGE_ROUTE_IDS,
            ),
            "other",
        )

    def test_high_cardinality_document_id_is_not_a_metric_label(self):
        metrics = (
            observability.RETRIEVAL_ROUTE_REQUESTS_TOTAL,
            observability.RETRIEVAL_ROUTE_DURATION_MS,
            observability.RETRIEVAL_GUARDRAIL_BLOCKS_TOTAL,
            observability.TOOL_EXECUTIONS_TOTAL,
            observability.TOOL_EXECUTION_DURATION_MS,
        )
        for metric in metrics:
            self.assertNotIn("document_id", metric.labelnames)
            self.assertIn("knowledge_route_id", metric.labelnames)


if __name__ == "__main__":
    unittest.main()
