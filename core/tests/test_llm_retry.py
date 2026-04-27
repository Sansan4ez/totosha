import asyncio
import importlib.util
import json
import os
import sys
import types
import unittest
from contextvars import ContextVar
from pathlib import Path
from unittest.mock import AsyncMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


class _DummyLogger:
    def debug(self, *args, **kwargs):
        return None

    def info(self, *args, **kwargs):
        return None

    def warning(self, *args, **kwargs):
        return None

    def error(self, *args, **kwargs):
        return None


class _DummySpan:
    def set_attribute(self, *args, **kwargs):
        return None


class _DummyTrace:
    @staticmethod
    def get_current_span():
        return _DummySpan()


class _DummySession:
    pass


class _DummySessionManager:
    def __init__(self):
        self.sessions = {}

    def get(self, *args, **kwargs):
        return _DummySession()

    def clear(self, *args, **kwargs):
        return None


_MODULE_PATH = Path(__file__).resolve().parents[1] / "agent.py"
_SPEC = importlib.util.spec_from_file_location("core_agent_module", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)

_stub_modules = {
    "aiohttp": types.SimpleNamespace(ClientTimeout=lambda **kwargs: None, ClientSession=None, ClientError=RuntimeError),
    "config": types.SimpleNamespace(
        CONFIG=types.SimpleNamespace(proxy_url="http://proxy:3200", workspace="/tmp"),
        get_model=lambda: "gpt-5.4",
        get_temperature=lambda: 0.7,
        get_max_iterations=lambda: 30,
    ),
    "logger": types.SimpleNamespace(
        agent_logger=_DummyLogger(),
        log_agent_step=lambda *args, **kwargs: None,
    ),
    "observability": types.SimpleNamespace(
        REQUEST_ID=ContextVar("request_id", default="-"),
        inject_trace_context=lambda headers=None, request_id=None: dict(headers or {}),
        record_span_event=lambda *args, **kwargs: None,
        update_correlation_context=lambda *args, **kwargs: {},
    ),
    "run_meta": types.SimpleNamespace(
        run_meta_get=lambda: None,
        run_meta_update_llm=lambda **kwargs: None,
        run_meta_append_artifact=lambda *args, **kwargs: False,
    ),
    "tools": types.SimpleNamespace(
        execute_tool=lambda *args, **kwargs: None,
        filter_tools_for_session=lambda *args, **kwargs: [],
    ),
    "models": types.SimpleNamespace(ToolContext=object, ToolResult=object),
    "opentelemetry": types.SimpleNamespace(trace=_DummyTrace()),
    "session_manager": types.SimpleNamespace(Session=_DummySession, SessionManager=_DummySessionManager),
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
        self.last_post_kwargs = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, *args, **kwargs):
        self.last_post_kwargs = kwargs
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class _SessionFactory:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.last_session = None

    def __call__(self, timeout=None):
        outcome = self.outcomes[self.calls]
        self.calls += 1
        self.last_session = _FakeSession(timeout, outcome)
        return self.last_session


def _tool_call(call_id: str, name: str = "demo_tool") -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": "{}"},
    }


def _messages_have_valid_tool_flow(messages: list[dict]) -> bool:
    idx = 0
    while idx < len(messages):
        message = messages[idx]
        role = message.get("role")
        if role == "assistant" and message.get("tool_calls"):
            tool_calls = message.get("tool_calls") or []
            expected_ids = [item.get("id") for item in tool_calls if isinstance(item, dict) and item.get("id")]
            if len(expected_ids) != len(tool_calls):
                return False
            seen_ids: set[str] = set()
            idx += 1
            while idx < len(messages) and messages[idx].get("role") == "tool":
                tool_call_id = messages[idx].get("tool_call_id")
                if not tool_call_id or tool_call_id not in expected_ids or tool_call_id in seen_ids:
                    return False
                seen_ids.add(tool_call_id)
                idx += 1
            if seen_ids != set(expected_ids):
                return False
            continue
        if role == "tool":
            return False
        idx += 1
    return True


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

    def test_call_llm_propagates_trace_headers_to_proxy(self):
        factory = _SessionFactory(
            [
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
        injected_headers = {
            "X-Request-Id": "req-123",
            "traceparent": "00-11111111111111111111111111111111-2222222222222222-01",
            "tracestate": "vendor=test",
        }
        token = _MODULE.OBS_REQUEST_ID.set("req-123")
        try:
            with patch.object(_MODULE, "aiohttp", aiohttp_stub), patch.object(
                _MODULE,
                "inject_trace_context",
                return_value=injected_headers,
            ) as inject_mock:
                result = asyncio.run(_MODULE.call_llm([{"role": "user", "content": "ping"}], [], ""))
        finally:
            _MODULE.OBS_REQUEST_ID.reset(token)

        self.assertEqual(result["choices"][0]["message"]["content"], "PONG")
        self.assertEqual(factory.last_session.last_post_kwargs["headers"], injected_headers)
        inject_mock.assert_called_once_with(request_id="req-123")

    def test_enforce_context_budget_removes_tool_exchange_atomically_when_latest_user_is_protected(self):
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "", "tool_calls": [_tool_call("call-1")]},
            {"role": "tool", "tool_call_id": "call-1", "content": "X" * 900},
            {"role": "assistant", "content": "Most recent answer"},
            {"role": "user", "content": "Final question"},
        ]
        removable_block = messages[2:4]
        budget = _MODULE.estimate_context_size(messages) - _MODULE.estimate_context_size(removable_block) + 16

        result = _MODULE.enforce_context_budget(messages, budget)

        self.assertFalse(result.hard_stop)
        self.assertEqual(result.reason, "trimmed_to_budget")
        self.assertEqual(result.removed_messages, 2)
        self.assertLessEqual(result.post_chars, budget)
        self.assertEqual(result.messages[-1]["content"], "Final question")
        self.assertTrue(_messages_have_valid_tool_flow(result.messages))
        self.assertFalse(any(msg.get("tool_call_id") == "call-1" for msg in result.messages))
        self.assertFalse(
            any(
                any(tool_call.get("id") == "call-1" for tool_call in (msg.get("tool_calls") or []))
                for msg in result.messages
            )
        )

    def test_call_llm_trims_oversized_middle_messages_below_budget(self):
        factory = _SessionFactory(
            [
                _FakeResponse(
                    status=200,
                    payload={
                        "id": "chatcmpl-test",
                        "model": "gpt-5.4",
                        "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
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
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "First question"},
            {"role": "assistant", "content": "", "tool_calls": [_tool_call("call-1")]},
            {"role": "tool", "tool_call_id": "call-1", "content": "X" * 900},
            {"role": "assistant", "content": "Most recent answer"},
            {"role": "user", "content": "Final question"},
        ]

        with patch.object(_MODULE, "aiohttp", aiohttp_stub), patch.dict(
            os.environ,
            {"MAX_CONTEXT_CHARS": "600"},
            clear=False,
        ):
            result = asyncio.run(_MODULE.call_llm(messages, [], "", purpose="agent_loop"))

        self.assertEqual(result["choices"][0]["message"]["content"], "OK")
        posted_messages = factory.last_session.last_post_kwargs["json"]["messages"]
        self.assertLessEqual(_MODULE.estimate_context_size(posted_messages), 600)
        self.assertTrue(_messages_have_valid_tool_flow(posted_messages))
        self.assertNotIn("X" * 100, json.dumps(posted_messages, ensure_ascii=False))
        self.assertFalse(any(msg.get("tool_call_id") == "call-1" for msg in posted_messages))

    def test_call_llm_records_trim_telemetry_for_oversized_context(self):
        factory = _SessionFactory(
            [
                _FakeResponse(
                    status=200,
                    payload={
                        "id": "chatcmpl-test",
                        "model": "gpt-5.4",
                        "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
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
        meta = {
            "context_trim_events": 0,
            "context_trim_pre_chars_max": 0,
            "context_trim_post_chars_max": 0,
            "context_trim_removed_messages_total": 0,
            "context_trim_truncated_messages_total": 0,
            "context_trim_hard_stops": 0,
        }
        messages = [
            {"role": "system", "content": "System prompt"},
            {"role": "user", "content": "Question"},
            {"role": "assistant", "content": "", "tool_calls": [_tool_call("call-1")]},
            {"role": "tool", "tool_call_id": "call-1", "content": "Y" * 900},
            {"role": "user", "content": "Final question"},
        ]

        with patch.object(_MODULE, "aiohttp", aiohttp_stub), patch.object(_MODULE, "run_meta_get", return_value=meta), patch.dict(
            os.environ,
            {"MAX_CONTEXT_CHARS": "500"},
            clear=False,
        ):
            result = asyncio.run(_MODULE.call_llm(messages, [], "", purpose="finalizer"))

        self.assertEqual(result["choices"][0]["message"]["content"], "OK")
        posted_messages = factory.last_session.last_post_kwargs["json"]["messages"]
        self.assertTrue(_messages_have_valid_tool_flow(posted_messages))
        self.assertEqual(meta["context_trim_events"], 1)
        self.assertEqual(meta["context_trim_last_stage"], "finalizer")
        self.assertGreater(meta["context_trim_last_pre_chars"], 500)
        self.assertLessEqual(meta["context_trim_last_post_chars"], 500)
        self.assertGreaterEqual(meta["context_trim_removed_messages_total"], 2)
        self.assertFalse(meta["context_trim_last_hard_stop"])

    def test_call_llm_fails_fast_when_protected_context_still_exceeds_budget(self):
        messages = [
            {"role": "system", "content": "S" * 700},
            {"role": "user", "content": "U" * 700},
        ]

        with patch.dict(os.environ, {"MAX_CONTEXT_CHARS": "500"}, clear=False):
            result = asyncio.run(_MODULE.call_llm(messages, [], "", purpose="route_selector"))

        self.assertIn("cannot be trimmed safely", result["error"])

    def test_call_llm_uses_stage_specific_timeout_budget(self):
        factory = _SessionFactory(
            [
                _FakeResponse(
                    status=200,
                    payload={
                        "id": "chatcmpl-test",
                        "model": "gpt-5.4",
                        "choices": [{"message": {"content": "OK"}, "finish_reason": "stop"}],
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

        with patch.object(_MODULE, "aiohttp", aiohttp_stub), patch.dict(
            os.environ,
            {
                "LLM_TIMEOUT_S": "120",
                "LLM_ROUTE_SELECTOR_TIMEOUT_S": "9",
            },
            clear=False,
        ):
            result = asyncio.run(_MODULE.call_llm([{"role": "user", "content": "ping"}], [], "", purpose="route_selector"))

        self.assertEqual(result["choices"][0]["message"]["content"], "OK")
        self.assertEqual(factory.last_session.last_post_kwargs["timeout"].kwargs["total"], 9.0)


if __name__ == "__main__":
    unittest.main()
