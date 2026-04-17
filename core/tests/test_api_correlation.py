import asyncio
import importlib.util
import os
import sys
import types
import unittest
from pathlib import Path


sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


class _ObserveRecorder:
    def __init__(self):
        self.calls: list[tuple[tuple, dict]] = []

    def __call__(self, *args, **kwargs):
        self.calls.append((args, kwargs))


class _UpdateRecorder:
    def __init__(self):
        self.calls: list[dict] = []

    def __call__(self, **kwargs):
        self.calls.append(kwargs)
        return kwargs


class _DummyScheduler:
    def set_callbacks(self, **kwargs):
        return None

    async def start(self):
        return None


class _FakeFastAPI:
    def __init__(self, *args, **kwargs):
        self.routes = []

    def include_router(self, router):
        return None

    def on_event(self, *args, **kwargs):
        def _decorator(func):
            return func

        return _decorator

    def get(self, *args, **kwargs):
        def _decorator(func):
            return func

        return _decorator

    def post(self, *args, **kwargs):
        def _decorator(func):
            return func

        return _decorator


class _FakeBaseModel:
    def __init__(self, **kwargs):
        annotations = getattr(self.__class__, "__annotations__", {})
        for field_name in annotations:
            if field_name in kwargs:
                value = kwargs[field_name]
            else:
                value = getattr(self.__class__, field_name, None)
            setattr(self, field_name, value)


def _load_api_module(*, run_agent_impl):
    observe_recorder = _ObserveRecorder()
    update_recorder = _UpdateRecorder()
    run_meta_tokens: list[dict] = []

    async def _run_agent(*args, **kwargs):
        return await run_agent_impl(*args, **kwargs)

    def _run_meta_set(meta):
        run_meta_tokens.append(meta)
        return object()

    def _run_meta_reset(token):
        return None

    sys.modules["config"] = types.SimpleNamespace(
        CONFIG=types.SimpleNamespace(api_port=4000, proxy_url="http://proxy", bot_url="http://bot", userbot_url="http://userbot"),
        get_model=lambda: "test-model",
        get_temperature=lambda: 0.1,
        get_max_iterations=lambda: 4,
    )
    sys.modules["logger"] = types.SimpleNamespace(
        api_logger=types.SimpleNamespace(info=lambda *args, **kwargs: None, error=lambda *args, **kwargs: None),
        log_request=lambda *args, **kwargs: None,
        log_response=lambda *args, **kwargs: None,
    )
    sys.modules["observability"] = types.SimpleNamespace(
        REQUEST_ID=types.SimpleNamespace(get=lambda default="-": "req-test"),
        inject_trace_context=lambda headers=None, request_id=None: dict(headers or {}),
        instrument_fastapi=lambda app: None,
        observe_request_correlation=observe_recorder,
        update_correlation_context=update_recorder,
    )
    sys.modules["agent"] = types.SimpleNamespace(
        run_agent=_run_agent,
        sessions=types.SimpleNamespace(clear=lambda *args, **kwargs: None),
    )
    sys.modules["run_meta"] = types.SimpleNamespace(
        run_meta_set=_run_meta_set,
        run_meta_reset=_run_meta_reset,
    )
    sys.modules["tools.scheduler"] = types.SimpleNamespace(scheduler=_DummyScheduler())
    sys.modules["admin_api"] = types.SimpleNamespace(
        router=types.SimpleNamespace(routes=[]),
        load_config=lambda: {
            "access": {
                "mode": "public",
                "admin_id": 1,
                "allowlist": [],
                "bot_enabled": True,
                "userbot_enabled": True,
            }
        },
    )
    sys.modules["aiohttp"] = types.SimpleNamespace(
        ClientSession=object,
        ClientTimeout=lambda **kwargs: kwargs,
    )
    sys.modules["fastapi"] = types.SimpleNamespace(FastAPI=_FakeFastAPI)
    sys.modules["pydantic"] = types.SimpleNamespace(BaseModel=_FakeBaseModel)
    sys.modules["opentelemetry"] = types.SimpleNamespace(
        trace=types.SimpleNamespace(
            get_current_span=lambda: types.SimpleNamespace(
                get_span_context=lambda: types.SimpleNamespace(is_valid=False, trace_id=0, span_id=0)
            )
        )
    )

    module_path = Path(__file__).resolve().parents[1] / "api.py"
    spec = importlib.util.spec_from_file_location("core_api_correlation_module", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module, observe_recorder, update_recorder, run_meta_tokens


class CoreApiCorrelationTests(unittest.TestCase):
    def test_chat_success_does_not_record_request_correlation_in_handler(self):
        seen_kwargs: list[dict] = []

        async def _success(*args, **kwargs):
            seen_kwargs.append(kwargs)
            return "PONG"

        module, observe_recorder, update_recorder, _ = _load_api_module(run_agent_impl=_success)
        request = module.ChatRequest(
            user_id=1,
            chat_id=2,
            message="ping",
            username="tester",
            chat_type="private",
            source="bot",
            return_meta=True,
        )

        response = asyncio.run(module.chat(request))

        self.assertEqual(response["response"], "PONG")
        self.assertEqual(response["meta"]["execution_mode"], "runtime")
        self.assertEqual(seen_kwargs[0]["execution_mode"], "runtime")
        self.assertEqual(len(observe_recorder.calls), 0)
        self.assertEqual(len(update_recorder.calls), 1)
        self.assertEqual(update_recorder.calls[0]["selected_source"], "unknown")

    def test_chat_error_does_not_record_request_correlation_in_handler(self):
        seen_kwargs: list[dict] = []

        async def _failure(*args, **kwargs):
            seen_kwargs.append(kwargs)
            raise RuntimeError("boom")

        module, observe_recorder, update_recorder, _ = _load_api_module(run_agent_impl=_failure)
        request = module.ChatRequest(
            user_id=1,
            chat_id=2,
            message="ping",
            username="tester",
            chat_type="private",
            source="bot",
            return_meta=True,
        )

        response = asyncio.run(module.chat(request))

        self.assertEqual(response["response"], "Error: boom")
        self.assertEqual(response["meta"]["execution_mode"], "runtime")
        self.assertEqual(seen_kwargs[0]["execution_mode"], "runtime")
        self.assertEqual(len(observe_recorder.calls), 0)
        self.assertEqual(len(update_recorder.calls), 1)
        self.assertEqual(update_recorder.calls[0]["selected_source"], "unknown")

    def test_chat_passes_explicit_benchmark_execution_mode(self):
        seen_kwargs: list[dict] = []

        async def _success(*args, **kwargs):
            seen_kwargs.append(kwargs)
            return "PONG"

        module, observe_recorder, update_recorder, _ = _load_api_module(run_agent_impl=_success)
        request = module.ChatRequest(
            user_id=1,
            chat_id=2,
            message="ping",
            username="tester",
            chat_type="private",
            source="bot",
            return_meta=True,
            execution_mode="benchmark",
        )

        response = asyncio.run(module.chat(request))

        self.assertEqual(response["response"], "PONG")
        self.assertEqual(response["meta"]["execution_mode"], "benchmark")
        self.assertEqual(seen_kwargs[0]["execution_mode"], "benchmark")
        self.assertEqual(len(observe_recorder.calls), 0)
        self.assertEqual(len(update_recorder.calls), 1)
