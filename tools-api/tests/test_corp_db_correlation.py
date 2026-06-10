import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path


class _Metric:
    def labels(self, *args, **kwargs):
        return self

    def inc(self, *args, **kwargs):
        return None

    def observe(self, *args, **kwargs):
        return None


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


class _FakeRouter:
    def __init__(self, *args, **kwargs):
        self.routes = []

    def post(self, *args, **kwargs):
        def _decorator(func):
            return func

        return _decorator


class _FakeHTTPException(Exception):
    pass


class _FakeRequest:
    def __init__(self, headers: dict[str, str] | None = None):
        self.headers = headers or {}


class _FakeBaseModel:
    def __init__(self, **kwargs):
        annotations = getattr(self.__class__, "__annotations__", {})
        for field_name in annotations:
            if field_name in kwargs:
                value = kwargs[field_name]
            else:
                value = getattr(self.__class__, field_name, None)
            setattr(self, field_name, value)

    def copy(self, update=None):
        data = dict(self.__dict__)
        data.update(update or {})
        return self.__class__(**data)

    def model_copy(self, update=None):
        return self.copy(update=update)


def _fake_field(*, default=None, **kwargs):
    return default


def _load_route_module(*, update_recorder):
    fastapi_module = types.ModuleType("fastapi")
    fastapi_module.APIRouter = _FakeRouter
    fastapi_module.HTTPException = _FakeHTTPException
    fastapi_module.Request = _FakeRequest
    sys.modules["fastapi"] = fastapi_module
    sys.modules["openai"] = types.SimpleNamespace(AsyncOpenAI=object)
    sys.modules["asyncpg"] = types.SimpleNamespace(Connection=object, Pool=object)
    sys.modules["pgvector"] = types.ModuleType("pgvector")
    sys.modules["pgvector.asyncpg"] = types.SimpleNamespace(register_vector=lambda *args, **kwargs: None)
    sys.modules["pydantic"] = types.SimpleNamespace(BaseModel=_FakeBaseModel, Field=_fake_field)
    sys.modules["prometheus_client"] = types.SimpleNamespace(Counter=lambda *args, **kwargs: _Metric(), Histogram=lambda *args, **kwargs: _Metric())
    sys.modules["opentelemetry"] = types.SimpleNamespace(trace=types.SimpleNamespace(get_tracer=lambda *args, **kwargs: _DummyTracer()))

    src_pkg = types.ModuleType("src")
    src_pkg.__path__ = []
    routes_pkg = types.ModuleType("src.routes")
    routes_pkg.__path__ = []
    sys.modules["src"] = src_pkg
    sys.modules["src.routes"] = routes_pkg
    sys.modules["src.observability"] = types.SimpleNamespace(
        REGISTRY=object(),
        REQUEST_ID=types.SimpleNamespace(get=lambda default="-": "req-tools"),
        get_correlation_context=lambda: {},
        record_span_event=lambda *args, **kwargs: None,
        update_correlation_context=update_recorder,
    )

    module_path = Path(__file__).resolve().parents[1] / "src" / "routes" / "corp_db.py"
    spec = importlib.util.spec_from_file_location("src.routes.corp_db", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["src.routes.corp_db"] = module
    spec.loader.exec_module(module)
    return module


class _UpdateRecorder:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs


class _DummyPoolAcquire:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, tb):
        return False


class _DummyPool:
    def acquire(self):
        return _DummyPoolAcquire()


class ToolsApiCorrelationTests(unittest.TestCase):
    def test_route_updates_correlation_context_with_tool_call_headers(self):
        update_recorder = _UpdateRecorder()
        module = _load_route_module(update_recorder=update_recorder)

        async def _fake_get_pool():
            return _DummyPool()

        async def _fake_lamp_filters(conn, req, limit, offset):
            return {"status": "success", "kind": "lamp_filters", "results": [], "filters": {}}

        module._get_pool = _fake_get_pool
        module._lamp_filters = _fake_lamp_filters

        req = module.CorpDbSearchRequest(kind="lamp_filters")
        request = _FakeRequest(headers={"X-Tool-Call-Id": "call-9", "X-Tool-Call-Seq": "2"})

        response = asyncio.run(module.corp_db_search(req, request))

        self.assertEqual(response["status"], "success")
        self.assertGreaterEqual(len(update_recorder.calls), 1)
        self.assertEqual(update_recorder.calls[0]["tool_call_id"], "call-9")
        self.assertEqual(update_recorder.calls[0]["tool_call_seq"], "2")
        self.assertEqual(update_recorder.calls[0]["tool_name"], "corp_db_search")
