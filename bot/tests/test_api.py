import asyncio
import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import patch


_MODULE_PATH = Path(__file__).resolve().parents[1] / "api.py"
_SPEC = importlib.util.spec_from_file_location("bot_api_module", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)

_stub_modules = {
    "aiohttp": types.SimpleNamespace(ClientTimeout=lambda **kwargs: None, ClientSession=None),
    "config": types.SimpleNamespace(CORE_URL="http://core:4000"),
    "observability": types.SimpleNamespace(inject_trace_context=lambda: {}),
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
    def __init__(self, *, status: int, payload: dict):
        self.status = status
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def json(self):
        return self._payload


class _FakeSession:
    def __init__(self, timeout, response):
        self.timeout = timeout
        self.response = response
        self.last_post_kwargs = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def post(self, *args, **kwargs):
        self.last_post_kwargs = kwargs
        return self.response


class _SessionFactory:
    def __init__(self, response):
        self.response = response
        self.last_session = None

    def __call__(self, timeout=None):
        self.last_session = _FakeSession(timeout, self.response)
        return self.last_session


class BotApiTests(unittest.TestCase):
    def test_call_core_propagates_trace_headers(self):
        factory = _SessionFactory(
            _FakeResponse(
                status=200,
                payload={"response": "pong", "disabled": False, "access_denied": False},
            )
        )
        aiohttp_stub = types.SimpleNamespace(ClientTimeout=_FakeTimeout, ClientSession=factory)
        injected_headers = {
            "X-Request-Id": "req-789",
            "traceparent": "00-cccccccccccccccccccccccccccccccc-dddddddddddddddd-01",
            "tracestate": "vendor=test",
        }

        with patch.object(_MODULE, "aiohttp", aiohttp_stub), patch.object(
            _MODULE,
            "inject_trace_context",
            return_value=injected_headers,
        ) as inject_mock:
            result = asyncio.run(_MODULE.call_core(1, 2, "ping", "user", "private"))

        self.assertEqual(result.response, "pong")
        self.assertEqual(factory.last_session.last_post_kwargs["headers"], injected_headers)
        inject_mock.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
