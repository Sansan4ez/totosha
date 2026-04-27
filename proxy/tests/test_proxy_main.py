import asyncio
import importlib.util
import os
import sys
import types
import unittest
from contextvars import ContextVar
from pathlib import Path
from unittest.mock import patch


class _DummyCounter:
    def labels(self, *args, **kwargs):
        return self

    def inc(self, amount: float = 1.0):
        return None


class _FakeTimeout:
    def __init__(self, **kwargs):
        self.kwargs = kwargs


class _FakeResponse:
    def __init__(self, *, status: int = 200, body: bytes = b"", headers: dict | None = None):
        self.status = status
        self.body = body
        self.headers = headers or {}
        self.payload = None


class _FakeStreamResponse(_FakeResponse):
    def __init__(self, *, status: int = 200, headers: dict | None = None):
        super().__init__(status=status, headers=headers)
        self.chunks: list[bytes] = []
        self.prepared = False
        self.eof = False

    async def prepare(self, request):
        self.prepared = True
        return self

    async def write(self, chunk: bytes):
        self.chunks.append(chunk)

    async def write_eof(self):
        self.eof = True


def _json_response(payload: dict, status: int = 200):
    response = _FakeResponse(status=status)
    response.payload = payload
    response.body = payload
    return response


_web_stub = types.SimpleNamespace(
    Request=object,
    Response=_FakeResponse,
    StreamResponse=_FakeStreamResponse,
    json_response=_json_response,
    Application=object,
    middleware=lambda fn: fn,
    run_app=lambda *args, **kwargs: None,
)

_MODULE_PATH = Path(__file__).resolve().parents[1] / "main.py"
_SPEC = importlib.util.spec_from_file_location("proxy_main_module", _MODULE_PATH)
assert _SPEC and _SPEC.loader
_MODULE = importlib.util.module_from_spec(_SPEC)

_stub_modules = {
    "aiohttp": types.SimpleNamespace(ClientTimeout=_FakeTimeout, ClientSession=None, ClientError=RuntimeError, web=_web_stub),
    "prometheus_client": types.SimpleNamespace(Counter=lambda *args, **kwargs: _DummyCounter()),
    "observability": types.SimpleNamespace(
        REGISTRY=object(),
        REQUEST_ID=ContextVar("request_id", default="-"),
        metrics_handler=lambda _: None,
        observability_middleware=lambda request, handler: handler,
        setup_observability=lambda _: None,
    ),
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


class _FakeContent:
    def __init__(self, chunks: list[bytes]):
        self._chunks = list(chunks)

    def iter_any(self):
        async def _iterator():
            for chunk in self._chunks:
                yield chunk

        return _iterator()


class _FakeUpstreamResponse:
    def __init__(
        self,
        *,
        status: int = 200,
        body: bytes = b"",
        headers: dict | None = None,
        read_exception: Exception | None = None,
        stream_chunks: list[bytes] | None = None,
    ):
        self.status = status
        self.headers = headers or {}
        self._body = body
        self._read_exception = read_exception
        self.content = _FakeContent(stream_chunks or [])

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def read(self):
        if self._read_exception is not None:
            raise self._read_exception
        return self._body


class _FakeSession:
    def __init__(self, timeout, outcome):
        self.timeout = timeout
        self.outcome = outcome
        self.last_request_kwargs = None

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    def request(self, *args, **kwargs):
        self.last_request_kwargs = kwargs
        if isinstance(self.outcome, Exception):
            raise self.outcome
        return self.outcome


class _SessionFactory:
    def __init__(self, outcomes: list[object]):
        self.outcomes = list(outcomes)
        self.calls = 0
        self.last_session = None

    def __call__(self, timeout=None):
        outcome = self.outcomes[self.calls]
        self.calls += 1
        self.last_session = _FakeSession(timeout, outcome)
        return self.last_session


class _FakeRequest:
    def __init__(self, *, body: bytes, path: str = "chat/completions", method: str = "POST", headers: dict | None = None):
        self._body = body
        self.match_info = {"path": path}
        self.method = method
        self.headers = headers or {}
        self.query_string = ""

    async def read(self):
        return self._body


class _ClosingStreamResponse(_FakeStreamResponse):
    async def write(self, chunk: bytes):
        raise RuntimeError("Cannot write to closing transport")


class ProxyHelpersTests(unittest.TestCase):
    def test_resolve_target_url_handles_v1_base(self):
        url = _MODULE._resolve_target_url("http://proxy.example/v1", "embeddings")
        self.assertEqual(url, "http://proxy.example/v1/embeddings")

    def test_safe_retryable_llm_request_excludes_streaming(self):
        self.assertTrue(
            _MODULE._is_safe_retryable_llm_request("POST", "chat/completions", {"stream": False})
        )
        self.assertFalse(
            _MODULE._is_safe_retryable_llm_request("POST", "chat/completions", {"stream": True})
        )

    def test_hash_embedding_is_deterministic(self):
        first = _MODULE._hash_embedding("нефтегаз ip65 100w", 16)
        second = _MODULE._hash_embedding("нефтегаз ip65 100w", 16)
        self.assertEqual(first, second)
        self.assertEqual(len(first), 16)

    def test_local_embeddings_response_supports_batch_input(self):
        payload = {"model": "text-embedding-3-large", "input": ["ip65", "5000k"], "dimensions": 8}
        response = _MODULE._local_embeddings_response(payload)
        self.assertEqual(response["embedding_backend"], "local_hash_fallback")
        self.assertEqual(len(response["data"]), 2)
        self.assertEqual(len(response["data"][0]["embedding"]), 8)

    def test_proxy_llm_retries_buffered_disconnect_before_first_byte(self):
        factory = _SessionFactory(
            [
                _FakeUpstreamResponse(
                    status=200,
                    headers={"x-request-id": "up-1"},
                    read_exception=RuntimeError("upstream disconnected before completion"),
                ),
                _FakeUpstreamResponse(
                    status=200,
                    headers={"x-request-id": "up-2"},
                    body=b'{"id":"chatcmpl-ok"}',
                ),
            ]
        )
        aiohttp_stub = types.SimpleNamespace(
            ClientTimeout=_FakeTimeout,
            ClientSession=factory,
            ClientError=RuntimeError,
            web=_MODULE.web,
        )
        request = _FakeRequest(body=b'{"model":"gpt-5.4","messages":[{"role":"user","content":"ping"}]}')
        config = _MODULE.ProxyRuntimeConfig(
            llm_base_url="http://upstream.example/v1",
            llm_api_key="",
            zai_api_key="",
            model_name="gpt-5.4",
        )

        with patch.object(_MODULE, "aiohttp", aiohttp_stub), patch.object(
            _MODULE, "load_runtime_config", return_value=config
        ), patch.dict(
            os.environ,
            {
                "PROXY_LLM_RETRY_ATTEMPTS": "2",
                "PROXY_LLM_RETRY_BASE_DELAY_S": "0",
                "PROXY_LLM_UPSTREAM_TIMEOUT_S": "115",
            },
            clear=False,
        ):
            result = asyncio.run(_MODULE.proxy_llm(request))

        self.assertEqual(factory.calls, 2)
        self.assertEqual(result.status, 200)
        self.assertEqual(result.body, b'{"id":"chatcmpl-ok"}')
        self.assertEqual(result.headers["X-Upstream-Request-Id"], "up-2")

    def test_proxy_llm_streaming_downstream_close_does_not_convert_to_502(self):
        factory = _SessionFactory(
            [
                _FakeUpstreamResponse(
                    status=200,
                    headers={"x-request-id": "up-stream"},
                    stream_chunks=[b'data: {"id":"chunk-1"}\n\n'],
                ),
            ]
        )
        aiohttp_stub = types.SimpleNamespace(
            ClientTimeout=_FakeTimeout,
            ClientSession=factory,
            ClientError=RuntimeError,
            web=_MODULE.web,
        )
        request = _FakeRequest(
            body=b'{"model":"gpt-5.4","messages":[{"role":"user","content":"ping"}],"stream":true}'
        )
        config = _MODULE.ProxyRuntimeConfig(
            llm_base_url="http://upstream.example/v1",
            llm_api_key="",
            zai_api_key="",
            model_name="gpt-5.4",
        )

        with patch.object(_MODULE, "aiohttp", aiohttp_stub), patch.object(
            _MODULE.web, "StreamResponse", _ClosingStreamResponse
        ), patch.object(_MODULE, "load_runtime_config", return_value=config):
            result = asyncio.run(_MODULE.proxy_llm(request))

        self.assertIsInstance(result, _ClosingStreamResponse)
        self.assertEqual(result.status, 200)
        self.assertIsNone(result.payload)


if __name__ == "__main__":
    unittest.main()
