import asyncio
import json
import os
import sys
import unittest
import importlib.util
from pathlib import Path
import types
from unittest.mock import patch
from contextvars import ContextVar

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

sys.modules.setdefault("aiohttp", types.ModuleType("aiohttp"))
sys.modules.setdefault(
    "observability",
    types.SimpleNamespace(
        REQUEST_ID=ContextVar("request_id", default="-"),
        get_correlation_context=lambda: {},
        inject_trace_context=lambda headers=None, request_id=None: dict(headers or {}),
        update_correlation_context=lambda *args, **kwargs: {},
    ),
)


class _DummySpan:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def set_attribute(self, *args, **kwargs):
        return None

    def record_exception(self, *args, **kwargs):
        return None


class _DummyTracer:
    def start_as_current_span(self, *args, **kwargs):
        return _DummySpan()


sys.modules.setdefault(
    "opentelemetry",
    types.SimpleNamespace(trace=types.SimpleNamespace(get_tracer=lambda *args, **kwargs: _DummyTracer())),
)

_MODULE_PATH = Path(__file__).resolve().parents[1] / "tools" / "corp_db.py"
_SPEC = importlib.util.spec_from_file_location("corp_db_tool_module", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
_serialize_runtime_payload = _MODULE._serialize_runtime_payload
tool_corp_db_search = _MODULE.tool_corp_db_search

from models import ToolContext


class _FakeTimeout:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeResponse:
    def __init__(self, status: int, body: str):
        self.status = status
        self._body = body

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self):
        return self._body


class _FakeSession:
    def __init__(self, timeout, response: _FakeResponse):
        self.timeout = timeout
        self._response = response
        self.last_post_kwargs = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, *args, **kwargs):
        self.last_post_kwargs = kwargs
        return self._response


def _aiohttp_stub_for_payload(payload: object, *, status: int = 200):
    body = json.dumps(payload, ensure_ascii=False)
    state = types.SimpleNamespace(last_session=None)

    def _client_session(timeout):
        session = _FakeSession(timeout, _FakeResponse(status, body))
        state.last_session = session
        return session

    return types.SimpleNamespace(
        ClientTimeout=_FakeTimeout,
        ClientSession=_client_session,
        _state=state,
    )


class CorpDbToolFormattingTests(unittest.TestCase):
    def test_runtime_payload_preserves_all_rows_and_fields(self):
        data = {
            "status": "success",
            "kind": "hybrid_search",
            "results": [
                {
                    "entity_type": "lamp",
                    "title": f"Lamp {index}",
                    "metadata": {"lamp_id": index},
                    "facts": {f"fact_{fact}": {"label": f"F{fact}", "text": str(fact)} for fact in range(8)},
                }
                for index in range(6)
            ],
        }

        payload = json.loads(_serialize_runtime_payload(data))

        self.assertEqual(len(payload["results"]), 6)
        self.assertEqual(len(payload["results"][0]["facts"]), 8)
        self.assertEqual(payload["results"][5]["title"], "Lamp 5")

    def test_runtime_payload_keeps_full_company_fact_rows(self):
        data = {
            "status": "success",
            "kind": "hybrid_search",
            "query": "сайт компании ЛАДзавод светотехники",
            "results": [
                {
                    "entity_type": "kb_chunk",
                    "title": "О компании",
                    "document_title": "Общая информация о компании ЛАДзавод светотехники",
                    "heading": "О компании",
                    "score": 0.48,
                    "metadata": {
                        "source_file": "common_information_about_company.md",
                        "document_title": "Общая информация о компании ЛАДзавод светотехники",
                        "source_hash": "abc123",
                    },
                    "preview": "Мы занимаем одно из ведущих мест на рынке промышленного светотехнического оборудования в России." * 4,
                },
                {
                    "entity_type": "kb_chunk",
                    "title": "Контакты",
                    "document_title": "Общая информация о компании ЛАДзавод светотехники",
                    "heading": "Контакты",
                    "score": 0.31,
                    "metadata": {
                        "source_file": "common_information_about_company.md",
                        "document_title": "Общая информация о компании ЛАДзавод светотехники",
                        "source_hash": "def456",
                    },
                    "preview": "Телефон +7 (351) 239-18-11, email lad@ladled.ru.",
                },
            ],
        }

        payload = json.loads(_serialize_runtime_payload(data))

        self.assertEqual(payload["status"], "success")
        self.assertEqual(payload["kind"], "hybrid_search")
        self.assertEqual(len(payload["results"]), 2)
        self.assertIn("metadata", payload["results"][0])
        self.assertTrue(payload["results"][0]["preview"].endswith("России."))

    def test_tool_preserves_full_lamp_filters_payload(self):
        ctx = ToolContext(cwd="/tmp", user_id=42, chat_id=42, chat_type="private")
        payload = {
            "status": "success",
            "kind": "lamp_filters",
            "results": [
                {
                    "name": "NL Nova30-N-O",
                    "preview": "NL Nova30 | 15 Вт | 2019 лм | 5000 K | Ra 80",
                    "agent_summary": "Светильник NL Nova30-N-O. Мощность 15 Вт.",
                    "facts": {
                        "power_w": {"label": "Мощность", "text": "15 Вт"},
                        "color_rendering_index_ra": {"label": "Индекс цветопередачи", "text": "Ra 80"},
                    },
                }
            ],
        }

        with patch.object(_MODULE, "aiohttp", _aiohttp_stub_for_payload(payload)):
            result = asyncio.run(tool_corp_db_search({"kind": "lamp_filters", "power_w_min": 15}, ctx))

        self.assertTrue(result.success)
        decoded = json.loads(result.output)
        self.assertEqual(decoded["kind"], "lamp_filters")
        self.assertEqual(decoded["results"][0]["name"], "NL Nova30-N-O")
        self.assertEqual(decoded["results"][0]["facts"]["color_rendering_index_ra"]["text"], "Ra 80")

    def test_tool_returns_full_company_fact_runtime_payload_and_compact_artifact(self):
        ctx = ToolContext(cwd="/tmp", user_id=42, chat_id=42, chat_type="private")
        payload = {
            "status": "success",
            "kind": "hybrid_search",
            "query": "контакты компании ЛАДзавод светотехники",
            "results": [
                {
                    "entity_type": "kb_chunk",
                    "title": "Контакты",
                    "document_title": "Общая информация о компании ЛАДзавод светотехники",
                    "heading": "Контакты",
                    "score": 0.39,
                    "metadata": {
                        "source_file": "common_information_about_company.md",
                        "document_title": "Общая информация о компании ЛАДзавод светотехники",
                    },
                    "preview": "Телефон +7 (351) 239-18-11, email lad@ladled.ru. " * 10,
                }
            ],
        }

        with patch.object(_MODULE, "aiohttp", _aiohttp_stub_for_payload(payload)):
            result = asyncio.run(
                tool_corp_db_search(
                    {"kind": "hybrid_search", "profile": "kb_search", "query": "контакты компании ЛАДзавод светотехники"},
                    ctx,
                )
            )

        self.assertTrue(result.success)
        decoded = json.loads(result.output)
        self.assertEqual(decoded["status"], "success")
        self.assertEqual(decoded["kind"], "hybrid_search")
        self.assertEqual(decoded["results"][0]["metadata"]["source_file"], "common_information_about_company.md")
        self.assertTrue(decoded["results"][0]["preview"].endswith("lad@ladled.ru. "))
        self.assertIsInstance(result.metadata, dict)
        self.assertEqual(result.metadata.get("runtime_payload_format"), "full_json")
        self.assertEqual(result.metadata.get("bench_payload_format"), "compact_company_fact_v1")
        artifact = result.metadata.get("bench_artifact")
        self.assertEqual(artifact["tool"], "corp_db_search")
        self.assertEqual(artifact["kind"], "hybrid_search")
        self.assertEqual(artifact["payload"]["result_format"], "compact_company_fact_v1")
        self.assertTrue(artifact["payload"]["results"][0]["preview"].endswith("…"))

    def test_tool_preserves_route_aware_kb_args(self):
        ctx = ToolContext(cwd="/tmp", user_id=42, chat_id=42, chat_type="private")
        payload = {
            "status": "success",
            "kind": "hybrid_search",
            "filters": {
                "knowledge_route_id": "corp_kb.luxnet",
                "source_file_scope": ["about_Luxnet.md"],
                "topic_facets": ["definition"],
            },
            "results": [
                {
                    "entity_type": "kb_chunk",
                    "title": "Что такое Luxnet",
                    "document_title": "О Luxnet",
                    "heading": "Что такое Luxnet",
                    "metadata": {"source_file": "about_Luxnet.md"},
                    "preview": "Luxnet — это система управления освещением.",
                }
            ],
        }

        aiohttp_stub = _aiohttp_stub_for_payload(payload)
        with patch.object(_MODULE, "aiohttp", aiohttp_stub):
            result = asyncio.run(
                tool_corp_db_search(
                    {
                        "kind": "hybrid_search",
                        "profile": "kb_route_lookup",
                        "knowledge_route_id": "corp_kb.luxnet",
                        "source_files": ["about_Luxnet.md"],
                        "topic_facets": ["definition"],
                        "query": "что такое luxnet",
                    },
                    ctx,
                )
            )

        self.assertTrue(result.success)
        sent = aiohttp_stub._state.last_session.last_post_kwargs["json"]
        self.assertEqual(sent["knowledge_route_id"], "corp_kb.luxnet")
        self.assertEqual(sent["source_files"], ["about_Luxnet.md"])
        self.assertEqual(sent["topic_facets"], ["definition"])

    def test_tool_preserves_structured_fields_for_sku_by_code(self):
        ctx = ToolContext(cwd="/tmp", user_id=42, chat_id=42, chat_type="private")
        payload = {
            "status": "success",
            "kind": "sku_by_code",
            "results": [
                {
                    "sku_id": 501,
                    "name": "LAD LED R500-9-30-6-650LZD",
                    "etm_code": "1234567",
                    "oracl_code": "OR-9988",
                    "url": "https://ladzavod.ru/example",
                }
            ],
        }

        with patch.object(_MODULE, "aiohttp", _aiohttp_stub_for_payload(payload)):
            result = asyncio.run(tool_corp_db_search({"kind": "sku_by_code", "etm": "1234567"}, ctx))

        self.assertTrue(result.success)
        decoded = json.loads(result.output)
        self.assertEqual(decoded["results"][0]["etm_code"], "1234567")
        self.assertEqual(decoded["results"][0]["oracl_code"], "OR-9988")

    def test_tool_propagates_trace_headers_to_tools_api(self):
        ctx = ToolContext(cwd="/tmp", user_id=42, chat_id=42, chat_type="private")
        payload = {"status": "success", "kind": "hybrid_search", "results": []}
        aiohttp_stub = _aiohttp_stub_for_payload(payload)
        injected_headers = {
            "X-User-Id": "42",
            "X-Chat-Type": "private",
            "X-Request-Id": "req-456",
            "traceparent": "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01",
            "tracestate": "vendor=test",
        }
        token = _MODULE.OBS_REQUEST_ID.set("req-456")
        try:
            with patch.object(_MODULE, "aiohttp", aiohttp_stub), patch.object(
                _MODULE,
                "inject_trace_context",
                return_value=injected_headers,
            ) as inject_mock:
                result = asyncio.run(tool_corp_db_search({"kind": "hybrid_search", "query": "ip67"}, ctx))
        finally:
            _MODULE.OBS_REQUEST_ID.reset(token)

        self.assertTrue(result.success)
        self.assertEqual(aiohttp_stub._state.last_session.last_post_kwargs["headers"], injected_headers)
        inject_mock.assert_called_once_with(
            {"X-User-Id": "42", "X-Chat-Type": "private"},
            request_id="req-456",
        )

    def test_tool_propagates_tool_call_headers_to_tools_api(self):
        ctx = ToolContext(cwd="/tmp", user_id=42, chat_id=42, chat_type="private")
        payload = {"status": "success", "kind": "hybrid_search", "results": []}
        aiohttp_stub = _aiohttp_stub_for_payload(payload)

        with patch.object(_MODULE, "aiohttp", aiohttp_stub), patch.object(
            _MODULE,
            "get_correlation_context",
            return_value={"tool_call_id": "call-7", "tool_call_seq": "3"},
        ), patch.object(
            _MODULE,
            "inject_trace_context",
            side_effect=lambda headers=None, request_id=None: dict(headers or {}),
        ):
            result = asyncio.run(tool_corp_db_search({"kind": "hybrid_search", "query": "ip67"}, ctx))

        self.assertTrue(result.success)
        self.assertEqual(
            aiohttp_stub._state.last_session.last_post_kwargs["headers"],
            {
                "X-User-Id": "42",
                "X-Chat-Type": "private",
                "X-Tool-Call-Id": "call-7",
                "X-Tool-Call-Seq": "3",
            },
        )

    def test_tool_attaches_bench_artifact_for_application_recommendation(self):
        ctx = ToolContext(cwd="/tmp", user_id=42, chat_id=42, chat_type="private")
        payload = {
            "status": "success",
            "kind": "application_recommendation",
            "resolved_application": {"application_key": "sports_high_power"},
            "recommended_lamps": [
                {"name": "LAD LED R500-12-30-6-850LZD", "url": "https://ladzavod.ru/catalog/r500-12"}
            ],
            "portfolio_examples": [
                {"name": "Освещение стадиона", "url": "https://ladzavod.ru/portfolio/stadium"}
            ],
            "follow_up_question": "Уточните высоту установки?",
        }

        with patch.object(_MODULE, "aiohttp", _aiohttp_stub_for_payload(payload)):
            result = asyncio.run(tool_corp_db_search({"kind": "application_recommendation", "query": "стадион"}, ctx))

        self.assertTrue(result.success)
        artifact = result.metadata.get("bench_artifact")
        self.assertEqual(artifact["kind"], "application_recommendation")
        self.assertEqual(artifact["payload"]["resolved_application"]["application_key"], "sports_high_power")
        self.assertEqual(artifact["payload"]["recommended_lamps"][0]["url"], "https://ladzavod.ru/catalog/r500-12")

    def test_tool_preserves_structured_fields_for_category_mountings(self):
        ctx = ToolContext(cwd="/tmp", user_id=42, chat_id=42, chat_type="private")
        payload = {
            "status": "success",
            "kind": "category_mountings",
            "results": [
                {
                    "category_id": 68,
                    "category_name": "LAD LED R500-9 LZD",
                    "mounting_type_name": "Лира",
                    "mark": "LR",
                }
            ],
        }

        with patch.object(_MODULE, "aiohttp", _aiohttp_stub_for_payload(payload)):
            result = asyncio.run(tool_corp_db_search({"kind": "category_mountings", "category": "LAD LED R500-9 LZD"}, ctx))

        self.assertTrue(result.success)
        decoded = json.loads(result.output)
        self.assertEqual(decoded["results"][0]["mounting_type_name"], "Лира")
        self.assertEqual(decoded["results"][0]["mark"], "LR")

    def test_tool_preserves_specialized_payload_for_portfolio_examples_by_lamp(self):
        ctx = ToolContext(cwd="/tmp", user_id=42, chat_id=42, chat_type="private")
        payload = {
            "status": "success",
            "kind": "portfolio_examples_by_lamp",
            "filters": {"lamp_match": "exact", "portfolio_count": 2},
            "lamp": {
                "lamp_id": 2014,
                "name": "LAD LED R500-9-30-6-650LZD",
                "category_id": 68,
                "category_name": "LAD LED R500-9 LZD",
            },
            "spheres": [
                {"sphere_id": 4, "sphere_name": "Нефтегазовый комплекс"},
            ],
            "portfolio_examples": [
                {
                    "portfolio_id": 102,
                    "name": "Освещение резервуарного парка",
                    "sphere_id": 4,
                    "sphere_name": "Нефтегазовый комплекс",
                }
            ],
            "results": [
                {
                    "portfolio_id": 102,
                    "name": "Освещение резервуарного парка",
                    "sphere_id": 4,
                    "sphere_name": "Нефтегазовый комплекс",
                }
            ],
        }

        with patch.object(_MODULE, "aiohttp", _aiohttp_stub_for_payload(payload)):
            result = asyncio.run(tool_corp_db_search({"kind": "portfolio_examples_by_lamp", "name": "R500-9-30-6-650LZD"}, ctx))

        self.assertTrue(result.success)
        decoded = json.loads(result.output)
        self.assertEqual(decoded["kind"], "portfolio_examples_by_lamp")
        self.assertEqual(decoded["lamp"]["name"], "LAD LED R500-9-30-6-650LZD")
        self.assertEqual(decoded["spheres"][0]["sphere_name"], "Нефтегазовый комплекс")
        self.assertEqual(decoded["portfolio_examples"][0]["portfolio_id"], 102)

    def test_tool_preserves_specialized_payload_for_application_recommendation(self):
        ctx = ToolContext(cwd="/tmp", user_id=42, chat_id=42, chat_type="private")
        payload = {
            "status": "success",
            "kind": "application_recommendation",
            "filters": {"application_key": "sports_high_power", "resolution_strategy": "synonym_map"},
            "resolved_application": {
                "status": "resolved",
                "application_key": "sports_high_power",
                "sphere_name": "Спортивное и освещение высокой мощности",
                "confidence": 0.91,
                "resolution_strategy": "synonym_map",
            },
            "categories": [
                {
                    "category_id": 68,
                    "category_name": "LAD LED R500-9 LZD",
                    "url": "https://ladzavod.ru/catalog/r500-9-lzd",
                    "image_url": "https://ladzavod.ru/storage/app/uploads/public/r500-9.png",
                    "lamp_count": 4,
                }
            ],
            "recommended_lamps": [
                {
                    "lamp_id": 2014,
                    "name": "LAD LED R500-9-30-6-650LZD",
                    "url": "https://ladzavod.ru/catalog/r500-9-lzd/ladled-r500-9-30-6-650lzd",
                    "image_url": "https://ladzavod.ru/storage/app/uploads/public/r500-9-30.png",
                    "recommendation_reason": "высокая мощность для стадионного света",
                }
            ],
            "portfolio_examples": [
                {
                    "portfolio_id": 302,
                    "name": "Освещение стадиона",
                    "url": "https://ladzavod.ru/portfolio/stadium",
                    "image_url": "https://ladzavod.ru/storage/app/uploads/public/stadium.png",
                }
            ],
            "follow_up_question": "Уточните высоту установки и нужен общий заливочный свет или узконаправленные прожекторы?",
            "results": [
                {
                    "lamp_id": 2014,
                    "name": "LAD LED R500-9-30-6-650LZD",
                    "url": "https://ladzavod.ru/catalog/r500-9-lzd/ladled-r500-9-30-6-650lzd",
                }
            ],
        }

        with patch.object(_MODULE, "aiohttp", _aiohttp_stub_for_payload(payload)):
            result = asyncio.run(
                tool_corp_db_search(
                    {"kind": "application_recommendation", "query": "подбери освещение для спортивного стадиона"},
                    ctx,
                )
            )

        self.assertTrue(result.success)
        decoded = json.loads(result.output)
        self.assertEqual(decoded["kind"], "application_recommendation")
        self.assertEqual(decoded["resolved_application"]["application_key"], "sports_high_power")
        self.assertEqual(decoded["categories"][0]["image_url"], "https://ladzavod.ru/storage/app/uploads/public/r500-9.png")
        self.assertEqual(decoded["recommended_lamps"][0]["recommendation_reason"], "высокая мощность для стадионного света")
        self.assertIn("Уточните высоту установки", decoded["follow_up_question"])

    def test_tool_reports_timeout_error_with_budget_and_class(self):
        class FakeTimeout:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class FakeSession:
            def __init__(self, timeout):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def post(self, *args, **kwargs):
                raise asyncio.TimeoutError()

        aiohttp_stub = types.SimpleNamespace(
            ClientTimeout=FakeTimeout,
            ClientSession=lambda timeout: FakeSession(timeout),
        )
        ctx = ToolContext(cwd="/tmp", user_id=42, chat_id=42, chat_type="private")

        with patch.object(_MODULE, "aiohttp", aiohttp_stub), patch.dict(
            os.environ,
            {
                "CORP_DB_SEARCH_TIMEOUT_CONNECT_S": "3",
                "CORP_DB_SEARCH_TIMEOUT_READ_S": "17",
                "CORP_DB_SEARCH_TIMEOUT_TOTAL_S": "21",
            },
            clear=False,
        ):
            result = asyncio.run(tool_corp_db_search({"kind": "hybrid_search", "query": "ip67"}, ctx))

        self.assertFalse(result.success)
        self.assertIn("TimeoutError", result.error)
        self.assertIn("request timed out", result.error)
        self.assertIn("connect:3.0s", result.error)
        self.assertIn("read:17.0s", result.error)
        self.assertIn("total:21.0s", result.error)

    def test_tool_reports_transport_error_class_and_detail(self):
        class FakeTimeout:
            def __init__(self, **kwargs):
                self.kwargs = kwargs

        class FakeSession:
            def __init__(self, timeout):
                self.timeout = timeout

            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            def post(self, *args, **kwargs):
                raise RuntimeError("upstream disconnected")

        aiohttp_stub = types.SimpleNamespace(
            ClientTimeout=FakeTimeout,
            ClientSession=lambda timeout: FakeSession(timeout),
        )
        ctx = ToolContext(cwd="/tmp", user_id=42, chat_id=42, chat_type="private")

        with patch.object(_MODULE, "aiohttp", aiohttp_stub), patch.dict(os.environ, {}, clear=False):
            result = asyncio.run(tool_corp_db_search({"kind": "hybrid_search", "query": "ip67"}, ctx))

        self.assertFalse(result.success)
        self.assertIn("RuntimeError", result.error)
        self.assertIn("upstream disconnected", result.error)
        self.assertIn("timeout_budget=", result.error)


if __name__ == "__main__":
    unittest.main()
