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
sys.modules.setdefault("observability", types.SimpleNamespace(REQUEST_ID=ContextVar("request_id", default="-")))


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
_format_result_payload = _MODULE._format_result_payload
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

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, *args, **kwargs):
        return self._response


def _aiohttp_stub_for_payload(payload: object, *, status: int = 200):
    body = json.dumps(payload, ensure_ascii=False)
    return types.SimpleNamespace(
        ClientTimeout=_FakeTimeout,
        ClientSession=lambda timeout: _FakeSession(timeout, _FakeResponse(status, body)),
    )


class CorpDbToolFormattingTests(unittest.TestCase):
    def test_format_result_payload_preserves_all_rows_and_fields(self):
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

        payload = json.loads(_format_result_payload(data))

        self.assertEqual(len(payload["results"]), 6)
        self.assertEqual(len(payload["results"][0]["facts"]), 8)
        self.assertEqual(payload["results"][5]["title"], "Lamp 5")

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
