import asyncio
import importlib.util
import os
import sys
import types
import unittest
from contextvars import ContextVar
from pathlib import Path
from unittest.mock import AsyncMock, patch


class _DummyLogger:
    def debug(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


_MODULE_PATH = Path(__file__).resolve().parents[1] / "agent.py"
_SPEC = importlib.util.spec_from_file_location("core_agent_module", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)

_stub_modules = {
    "aiohttp": types.SimpleNamespace(ClientTimeout=lambda **kwargs: None, ClientSession=None, ClientError=RuntimeError),
    "config": types.SimpleNamespace(
        CONFIG=types.SimpleNamespace(proxy_url="http://proxy:3200"),
        get_model=lambda: "gpt-5.4",
        get_temperature=lambda: 0.7,
        get_max_iterations=lambda: 30,
    ),
    "logger": types.SimpleNamespace(
        agent_logger=_DummyLogger(),
        log_agent_step=lambda *args, **kwargs: None,
    ),
    "observability": types.SimpleNamespace(REQUEST_ID=ContextVar("request_id", default="-")),
    "run_meta": types.SimpleNamespace(run_meta_update_llm=lambda **kwargs: None),
    "tools": types.SimpleNamespace(
        execute_tool=lambda *args, **kwargs: None,
        filter_tools_for_session=lambda *args, **kwargs: [],
    ),
    "models": types.SimpleNamespace(ToolContext=object),
}
_saved_modules = {name: sys.modules.get(name) for name in _stub_modules}
try:
    sys.modules.update(_stub_modules)
    _SPEC.loader.exec_module(_MODULE)
finally:
    for name, original in _saved_modules.items():
        if original is None:
            sys.modules.pop(name, None)
        else:
            sys.modules[name] = original


class _FakeTimeout:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeResponse:
    def __init__(self, *, status: int, payload: dict | None = None, body: str | None = None):
        self.status = status
        self._payload = payload
        self._body = body if body is not None else ""

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def text(self):
        return self._body

    async def json(self):
        if self._payload is None:
            raise ValueError("No JSON payload configured")
        return self._payload


class _FakeSession:
    def __init__(self, timeout, outcome):
        self.timeout = timeout
        self.outcome = outcome

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, *args, **kwargs):
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class _SessionFactory:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def __call__(self, timeout=None):
        outcome = self.outcomes[self.calls]
        self.calls += 1
        return _FakeSession(timeout, outcome)


class CallLlmRetryTests(unittest.TestCase):
    def test_call_llm_retries_transient_408_and_succeeds(self):
        factory = _SessionFactory(
            [
                _FakeResponse(
                    status=408,
                    body='{"error":{"message":"stream error: stream disconnected before completion: stream closed before response.completed","type":"invalid_request_error"}}',
                ),
                _FakeResponse(
                    status=200,
                    payload={
                        "id": "chatcmpl-test",
                        "model": "gpt-5.4",
                        "choices": [{"message": {"content": "PONG"}, "finish_reason": "stop"}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
                    },
                ),
            ]
        )
        aiohttp_stub = types.SimpleNamespace(
            ClientTimeout=_FakeTimeout,
            ClientSession=factory,
            ClientError=RuntimeError,
        )

        with patch.object(_MODULE, "aiohttp", aiohttp_stub), patch.object(_MODULE.asyncio, "sleep", AsyncMock()), patch.dict(
            os.environ,
            {"LLM_MAX_ATTEMPTS": "3", "LLM_RETRY_BASE_DELAY_S": "0"},
            clear=False,
        ):
            result = asyncio.run(_MODULE.call_llm([{"role": "user", "content": "ping"}], [], ""))

        self.assertEqual(factory.calls, 2)
        self.assertEqual(result["choices"][0]["message"]["content"], "PONG")

    def test_call_llm_returns_error_after_retry_budget_exhausted(self):
        error_body = '{"error":{"message":"stream error: stream disconnected before completion: stream closed before response.completed","type":"invalid_request_error"}}'
        factory = _SessionFactory(
            [
                _FakeResponse(status=408, body=error_body),
                _FakeResponse(status=408, body=error_body),
                _FakeResponse(status=408, body=error_body),
            ]
        )
        aiohttp_stub = types.SimpleNamespace(
            ClientTimeout=_FakeTimeout,
            ClientSession=factory,
            ClientError=RuntimeError,
        )

        with patch.object(_MODULE, "aiohttp", aiohttp_stub), patch.object(_MODULE.asyncio, "sleep", AsyncMock()), patch.dict(
            os.environ,
            {"LLM_MAX_ATTEMPTS": "3", "LLM_RETRY_BASE_DELAY_S": "0"},
            clear=False,
        ):
            result = asyncio.run(_MODULE.call_llm([{"role": "user", "content": "ping"}], [], ""))

        self.assertEqual(factory.calls, 3)
        self.assertIn("LLM error 408", result["error"])


if __name__ == "__main__":
    unittest.main()
