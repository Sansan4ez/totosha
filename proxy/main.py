"""
API Proxy - isolates secrets from agent container
Reads secrets from /run/secrets/ (Docker Secrets)
Agent sees only http://proxy:3200, no API keys
"""

import os
import asyncio
import aiohttp
from aiohttp import web
import logging
import hashlib
import math
import re
import time
from dataclasses import dataclass
from typing import Any

from prometheus_client import Counter

from observability import (
    REGISTRY,
    REQUEST_ID,
    metrics_handler,
    observability_middleware,
    setup_observability,
)

setup_observability("proxy")
log = logging.getLogger(__name__)

PORT = int(os.getenv("PROXY_PORT", "3200"))
LOCAL_EMBEDDING_MODEL = "local-hash-embedding-1536"
LOCAL_EMBEDDING_DIMENSIONS = 1536
EMBEDDING_TOKEN_RE = re.compile(r"[0-9A-Za-zА-Яа-я]+")
READINESS_CACHE_TTL_SECONDS = 5.0
_readiness_cache: dict[str, tuple[float, bool, str]] = {}
UPSTREAM_REQUEST_ID_HEADERS = (
    "x-request-id",
    "request-id",
    "x-openai-request-id",
    "openai-request-id",
)
DOWNSTREAM_CLOSE_MARKERS = (
    "cannot write to closing transport",
    "connection lost",
    "client connection is closing",
)
RETRYABLE_UPSTREAM_MARKERS = (
    "server disconnected",
    "connection reset",
    "upstream disconnected",
    "stream disconnected before completion",
    "stream closed before response.completed",
    "connection closed",
)
PROXY_UPSTREAM_EVENTS_TOTAL = Counter(
    "proxy_upstream_events_total",
    "Proxy upstream lifecycle events grouped by path, phase, and outcome.",
    labelnames=("path", "phase", "outcome", "retryable"),
    registry=REGISTRY,
)


@dataclass(frozen=True)
class ProxyRuntimeConfig:
    llm_base_url: str
    llm_api_key: str
    zai_api_key: str
    model_name: str


def _float_env(name: str, default: float, *, minimum: float) -> float:
    try:
        value = float(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(minimum, value)


def _int_env(name: str, default: int, *, minimum: int) -> int:
    try:
        value = int(os.getenv(name, str(default)))
    except ValueError:
        return default
    return max(minimum, value)


def _llm_upstream_timeout_s() -> float:
    # Keep the proxy timeout below core's default 120s so proxy can emit a structured
    # timeout instead of writing a late upstream response into a closed downstream transport.
    return _float_env("PROXY_LLM_UPSTREAM_TIMEOUT_S", 115.0, minimum=1.0)


def _llm_retry_attempts() -> int:
    return _int_env("PROXY_LLM_RETRY_ATTEMPTS", 2, minimum=1)


def _llm_retry_delay_s(attempt: int) -> float:
    base = _float_env("PROXY_LLM_RETRY_BASE_DELAY_S", 0.25, minimum=0.0)
    return base * max(0, attempt - 1)


def read_secret(name: str) -> str | None:
    """Read secret from file (Docker Secrets mount at /run/secrets/)"""
    paths = [
        f"/run/secrets/{name}",
        f"/run/secrets/{name}.txt",
        f"./secrets/{name}.txt",
        f"/app/secrets/{name}.txt",
    ]
    
    for path in paths:
        try:
            with open(path, 'r') as f:
                value = f.read().strip()
                if value:
                    return value
        except (FileNotFoundError, PermissionError):
            continue
    
    # Fallback to env (insecure)
    env_name = name.upper()
    if os.getenv(env_name):
        return os.getenv(env_name)
    return None


def load_runtime_config() -> ProxyRuntimeConfig:
    return ProxyRuntimeConfig(
        llm_base_url=(read_secret("base_url") or "").rstrip("/"),
        llm_api_key=(read_secret("api_key") or "").strip(),
        zai_api_key=(read_secret("zai_api_key") or "").strip(),
        model_name=(read_secret("model_name") or "gpt-4").strip(),
    )


def _resolve_target_url(base_url: str, path: str, query_string: str = "") -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions") and path == "chat/completions":
        target_url = base
    elif base.endswith("/v1"):
        target_url = base + "/" + path
    else:
        target_url = base.rstrip("/v1").rstrip("/") + "/v1/" + path
    if query_string:
        target_url += "?" + query_string
    return target_url


def _resolve_transcribe_target_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        base = base[: -len("/chat/completions")]
    if base.endswith("/v1"):
        base = base[: -len("/v1")]
    elif "/v1/" in base:
        base = base.split("/v1/", 1)[0]
    return base.rstrip("/") + "/transcribe"


def _probe_url(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/v1"):
        return base + "/models"
    return base


async def _probe_llm_ready(config: ProxyRuntimeConfig) -> tuple[bool, str]:
    if not config.llm_base_url:
        return False, "missing_base_url"

    cache_key = hashlib.sha256(
        f"{config.llm_base_url}|{bool(config.llm_api_key)}".encode("utf-8")
    ).hexdigest()
    cached = _readiness_cache.get(cache_key)
    now = time.monotonic()
    if cached and (now - cached[0]) < READINESS_CACHE_TTL_SECONDS:
        return cached[1], cached[2]

    headers = {}
    if config.llm_api_key:
        headers["Authorization"] = f"Bearer {config.llm_api_key}"

    probe_url = _probe_url(config.llm_base_url)
    try:
        async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=5)) as session:
            async with session.get(probe_url, headers=headers, allow_redirects=False) as resp:
                ready = resp.status < 500 or resp.status in {401, 403, 404, 405}
                reason = f"http_{resp.status}"
    except Exception as exc:
        ready = False
        reason = exc.__class__.__name__

    _readiness_cache[cache_key] = (now, ready, reason)
    return ready, reason


def _tokenize_for_embedding(text: str) -> list[str]:
    return [token.lower() for token in EMBEDDING_TOKEN_RE.findall(text)]


def _hash_embedding(text: str, dimensions: int) -> list[float]:
    tokens = _tokenize_for_embedding(text)
    if not tokens:
        vector = [0.0] * dimensions
        vector[0] = 1.0
        return vector

    terms = tokens[:128]
    bigrams = [f"{left}_{right}" for left, right in zip(terms, terms[1:])][:64]
    vector = [0.0] * dimensions
    for term in [*terms, *bigrams]:
        weight = 1.0 if "_" not in term else 0.5
        for salt in range(3):
            digest = hashlib.sha256(f"{salt}:{term}".encode("utf-8")).digest()
            index = int.from_bytes(digest[:4], "big") % dimensions
            sign = -1.0 if (digest[4] & 1) else 1.0
            vector[index] += sign * weight / (salt + 1)

    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0.0:
        vector[0] = 1.0
        return vector
    return [round(value / norm, 8) for value in vector]


def _coerce_embedding_inputs(payload: dict[str, Any]) -> list[str]:
    raw_input = payload.get("input")
    if isinstance(raw_input, list):
        return [str(item) for item in raw_input]
    if raw_input is None:
        return [""]
    return [str(raw_input)]


def _local_embeddings_response(payload: dict[str, Any]) -> dict[str, Any]:
    dimensions = int(payload.get("dimensions") or LOCAL_EMBEDDING_DIMENSIONS)
    if dimensions < 1 or dimensions > LOCAL_EMBEDDING_DIMENSIONS:
        raise ValueError(f"dimensions must be between 1 and {LOCAL_EMBEDDING_DIMENSIONS}")

    inputs = _coerce_embedding_inputs(payload)
    data = []
    prompt_tokens = 0
    for index, text in enumerate(inputs):
        prompt_tokens += max(1, len(_tokenize_for_embedding(text)))
        data.append(
            {
                "object": "embedding",
                "index": index,
                "embedding": _hash_embedding(text, dimensions),
            }
        )

    return {
        "object": "list",
        "data": data,
        "model": payload.get("model") or LOCAL_EMBEDDING_MODEL,
        "usage": {
            "prompt_tokens": prompt_tokens,
            "total_tokens": prompt_tokens,
        },
        "embedding_backend": "local_hash_fallback",
    }


async def health(request: web.Request) -> web.Response:
    """Health check endpoint"""
    config = load_runtime_config()
    llm_ready, llm_reason = await _probe_llm_ready(config)
    return web.json_response({
        "status": "ok",
        "llm": bool(config.llm_base_url),
        "llm_ready": llm_ready,
        "llm_reason": llm_reason,
        "embeddings_ready": True,
        "embeddings_backend": LOCAL_EMBEDDING_MODEL,
        "zai": bool(config.zai_api_key)
    })


async def ready(request: web.Request) -> web.Response:
    """Readiness endpoint: proxy is usable for LLM traffic."""
    config = load_runtime_config()
    llm_ready, llm_reason = await _probe_llm_ready(config)
    status = 200 if llm_ready else 503
    return web.json_response(
        {
            "status": "ready" if llm_ready else "not_ready",
            "llm": bool(config.llm_base_url),
            "llm_ready": llm_ready,
            "llm_reason": llm_reason,
            "embeddings_ready": True,
            "embeddings_backend": LOCAL_EMBEDDING_MODEL,
        },
        status=status,
    )


import json

LOG_RAW = os.getenv("LOG_RAW", "false").lower() == "true"

def pretty_json(data: bytes) -> str:
    """Pretty print JSON with UTF-8"""
    try:
        obj = json.loads(data)
        return json.dumps(obj, indent=2, ensure_ascii=False)
    except:
        return data.decode('utf-8', errors='replace')


def _parse_json_payload(body: bytes) -> dict[str, Any] | None:
    if not body:
        return None
    try:
        parsed = json.loads(body.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _filter_proxy_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        key: value
        for key, value in headers.items()
        if key.lower() not in ("transfer-encoding", "content-encoding")
    }


def _extract_upstream_request_id(headers: Any) -> str:
    getter = getattr(headers, "get", None)
    if getter is None:
        return ""
    for key in UPSTREAM_REQUEST_ID_HEADERS:
        value = getter(key)
        if value:
            return str(value)
    return ""


def _is_streaming_llm_request(path: str, payload: dict[str, Any] | None) -> bool:
    return path == "chat/completions" and bool((payload or {}).get("stream"))


def _is_safe_retryable_llm_request(method: str, path: str, payload: dict[str, Any] | None) -> bool:
    if method.upper() == "GET":
        return True
    if method.upper() != "POST":
        return False
    if path != "chat/completions":
        return False
    return not _is_streaming_llm_request(path, payload)


def _should_buffer_llm_response(path: str, payload: dict[str, Any] | None) -> bool:
    return path == "chat/completions" and not _is_streaming_llm_request(path, payload)


def _is_downstream_transport_closing(exc: Exception) -> bool:
    normalized = str(exc or "").lower()
    return any(marker in normalized for marker in DOWNSTREAM_CLOSE_MARKERS)


def _is_retryable_upstream_exception(exc: Exception) -> bool:
    if isinstance(exc, (aiohttp.ClientError, asyncio.TimeoutError, ConnectionResetError)):
        return True
    normalized = str(exc or "").lower()
    return any(marker in normalized for marker in RETRYABLE_UPSTREAM_MARKERS)


def _record_upstream_event(path: str, phase: str, outcome: str, retryable: bool) -> None:
    PROXY_UPSTREAM_EVENTS_TOTAL.labels(path, phase, outcome, str(bool(retryable)).lower()).inc()


def _proxy_error_payload(
    *,
    code: str,
    message: str,
    path: str,
    phase: str,
    retryable: bool,
    attempt: int,
    upstream_status: int | None = None,
    upstream_request_id: str = "",
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "error": "Proxy error",
        "code": code,
        "message": message[:500],
        "path": path,
        "phase": phase,
        "retryable": retryable,
        "attempt": attempt,
        "request_id": REQUEST_ID.get("-"),
    }
    if upstream_status is not None:
        payload["upstream_status"] = upstream_status
    if upstream_request_id:
        payload["upstream_request_id"] = upstream_request_id
    return payload


def _log_upstream_failure(
    *,
    path: str,
    phase: str,
    attempt: int,
    max_attempts: int,
    exc: Exception,
    retryable: bool,
    upstream_status: int | None = None,
    upstream_request_id: str = "",
) -> None:
    log.warning(
        "LLM upstream failure path=%s phase=%s attempt=%s/%s retryable=%s upstream_status=%s upstream_request_id=%s error=%s",
        path,
        phase,
        attempt,
        max_attempts,
        retryable,
        upstream_status if upstream_status is not None else "-",
        upstream_request_id or "-",
        exc,
    )

async def proxy_llm(request: web.Request) -> web.StreamResponse:
    """Proxy /v1/* requests to LLM API with auth"""
    config = load_runtime_config()
    path = request.match_info.get("path", "")
    if path == "embeddings":
        return await proxy_embeddings(request, config)
    if not config.llm_base_url:
        return web.json_response({"error": "LLM not configured"}, status=503)
    
    target_url = _resolve_target_url(config.llm_base_url, path, request.query_string)
    
    log.info(f"LLM: {request.method} /v1/{path}")
    
    # Forward headers (except host and connection)
    headers = dict(request.headers)
    headers.pop("Host", None)
    headers.pop("Connection", None)
    if config.llm_api_key:
        headers["Authorization"] = f"Bearer {config.llm_api_key}"

    body = await request.read()
    payload = _parse_json_payload(body)
    should_buffer = _should_buffer_llm_response(path, payload)
    max_attempts = _llm_retry_attempts() if _is_safe_retryable_llm_request(request.method, path, payload) else 1
    timeout = aiohttp.ClientTimeout(total=_llm_upstream_timeout_s())

    # Log raw request if enabled
    if LOG_RAW and body:
        log.info("=" * 80)
        log.info("RAW REQUEST JSON:")
        print(pretty_json(body))
        log.info("=" * 80)

    for attempt in range(1, max_attempts + 1):
        upstream_status: int | None = None
        upstream_request_id = ""
        try:
            async with aiohttp.ClientSession(timeout=timeout) as session:
                async with session.request(
                    method=request.method,
                    url=target_url,
                    headers=headers,
                    data=body,
                ) as resp:
                    upstream_status = resp.status
                    upstream_request_id = _extract_upstream_request_id(resp.headers)
                    response_headers = _filter_proxy_headers(dict(resp.headers))
                    if upstream_request_id:
                        response_headers["X-Upstream-Request-Id"] = upstream_request_id

                    if should_buffer:
                        raw = await resp.read()
                        if LOG_RAW and raw:
                            log.info("=" * 80)
                            log.info("RAW RESPONSE JSON:")
                            print(pretty_json(raw))
                            log.info("=" * 80)
                        _record_upstream_event(path, "buffered_response", "success", retryable=False)
                        return web.Response(
                            status=resp.status,
                            body=raw,
                            headers=response_headers,
                        )

                    response = web.StreamResponse(status=resp.status, headers=response_headers)
                    iterator = resp.content.iter_any().__aiter__()
                    first_chunk = b""
                    try:
                        first_chunk = await iterator.__anext__()
                    except StopAsyncIteration:
                        first_chunk = b""

                    await response.prepare(request)

                    response_chunks = []
                    try:
                        if first_chunk:
                            if LOG_RAW:
                                response_chunks.append(first_chunk)
                            await response.write(first_chunk)
                        async for chunk in iterator:
                            if LOG_RAW:
                                response_chunks.append(chunk)
                            await response.write(chunk)

                        await response.write_eof()
                    except Exception as exc:
                        if _is_downstream_transport_closing(exc):
                            _record_upstream_event(path, "downstream_transport", "closed", retryable=False)
                            log.info(
                                "Downstream transport closed during streaming path=%s attempt=%s/%s upstream_status=%s upstream_request_id=%s",
                                path,
                                attempt,
                                max_attempts,
                                upstream_status if upstream_status is not None else "-",
                                upstream_request_id or "-",
                            )
                            return response
                        raise

                    if LOG_RAW and response_chunks:
                        full_response = b"".join(response_chunks)
                        log.info("=" * 80)
                        log.info("RAW RESPONSE JSON:")
                        print(pretty_json(full_response))
                        log.info("=" * 80)

                    _record_upstream_event(path, "streaming_response", "success", retryable=False)
                    return response

        except asyncio.TimeoutError as exc:
            retryable = attempt < max_attempts
            _record_upstream_event(path, "upstream_timeout", "error", retryable)
            _log_upstream_failure(
                path=path,
                phase="upstream_timeout",
                attempt=attempt,
                max_attempts=max_attempts,
                exc=exc,
                retryable=retryable,
                upstream_status=upstream_status,
                upstream_request_id=upstream_request_id,
            )
            if retryable:
                delay = _llm_retry_delay_s(attempt)
                if delay > 0:
                    await asyncio.sleep(delay)
                continue
            return web.json_response(
                _proxy_error_payload(
                    code="upstream_timeout",
                    message="LLM upstream timed out",
                    path=path,
                    phase="upstream_timeout",
                    retryable=False,
                    attempt=attempt,
                    upstream_status=upstream_status,
                    upstream_request_id=upstream_request_id,
                ),
                status=504,
            )
        except Exception as exc:
            if _is_downstream_transport_closing(exc):
                _record_upstream_event(path, "downstream_transport", "closed", retryable=False)
                log.info(
                    "Downstream transport closed while proxying path=%s attempt=%s/%s upstream_status=%s upstream_request_id=%s",
                    path,
                    attempt,
                    max_attempts,
                    upstream_status if upstream_status is not None else "-",
                    upstream_request_id or "-",
                )
                return web.Response(status=204)

            retryable = _is_retryable_upstream_exception(exc) and attempt < max_attempts
            _record_upstream_event(path, "upstream_disconnect", "error", retryable)
            _log_upstream_failure(
                path=path,
                phase="upstream_disconnect",
                attempt=attempt,
                max_attempts=max_attempts,
                exc=exc,
                retryable=retryable,
                upstream_status=upstream_status,
                upstream_request_id=upstream_request_id,
            )
            if retryable:
                delay = _llm_retry_delay_s(attempt)
                if delay > 0:
                    await asyncio.sleep(delay)
                continue
            return web.json_response(
                _proxy_error_payload(
                    code="upstream_disconnect",
                    message=str(exc),
                    path=path,
                    phase="upstream_disconnect",
                    retryable=False,
                    attempt=attempt,
                    upstream_status=upstream_status,
                    upstream_request_id=upstream_request_id,
                ),
                status=502,
            )

    return web.json_response(
        _proxy_error_payload(
            code="upstream_retry_exhausted",
            message="LLM request failed after retries",
            path=path,
            phase="retry_budget_exhausted",
            retryable=False,
            attempt=max_attempts,
        ),
        status=502,
    )


async def proxy_transcribe(request: web.Request) -> web.Response:
    """Proxy /transcribe requests to the internal CLIProxyAPI transcription endpoint."""
    config = load_runtime_config()
    if not config.llm_base_url:
        return web.json_response({"error": "LLM not configured"}, status=503)

    target_url = _resolve_transcribe_target_url(config.llm_base_url)
    headers = dict(request.headers)
    headers.pop("Host", None)
    headers.pop("Connection", None)
    if config.llm_api_key:
        headers["Authorization"] = f"Bearer {config.llm_api_key}"

    try:
        body = await request.read()
        async with aiohttp.ClientSession() as session:
            async with session.post(
                target_url,
                headers=headers,
                data=body,
                timeout=aiohttp.ClientTimeout(total=300),
            ) as resp:
                raw = await resp.read()
                return web.Response(
                    status=resp.status,
                    body=raw,
                    headers={
                        key: value
                        for key, value in resp.headers.items()
                        if key.lower() not in ("transfer-encoding", "content-encoding")
                    },
                )
    except asyncio.TimeoutError:
        return web.json_response({"error": "Transcribe request timeout"}, status=504)
    except Exception as e:
        log.error(f"Transcribe proxy error: {e}")
        return web.json_response({"error": "Proxy error", "message": str(e)}, status=502)


async def proxy_embeddings(request: web.Request, config: ProxyRuntimeConfig) -> web.Response:
    """Serve embeddings via upstream when available, else via local hash fallback."""
    try:
        body = await request.read()
        payload = json.loads(body.decode("utf-8") or "{}")
    except json.JSONDecodeError:
        return web.json_response({"error": "Invalid JSON"}, status=400)

    if config.llm_base_url:
        target_url = _resolve_target_url(config.llm_base_url, "embeddings", request.query_string)
        headers = dict(request.headers)
        headers.pop("Host", None)
        headers.pop("Connection", None)
        if config.llm_api_key:
            headers["Authorization"] = f"Bearer {config.llm_api_key}"

        try:
            async with aiohttp.ClientSession() as session:
                async with session.post(
                    target_url,
                    headers=headers,
                    data=body,
                    timeout=aiohttp.ClientTimeout(total=60),
                ) as resp:
                    if 200 <= resp.status < 300:
                        raw = await resp.read()
                        return web.Response(
                            status=resp.status,
                            body=raw,
                            headers={
                                key: value
                                for key, value in resp.headers.items()
                                if key.lower() not in ("transfer-encoding", "content-encoding")
                            },
                        )
                    log.warning(
                        "Embeddings upstream unavailable (status=%s), using local fallback",
                        resp.status,
                    )
        except Exception as exc:
            log.warning("Embeddings upstream probe failed, using local fallback: %s", exc)

    try:
        return web.json_response(_local_embeddings_response(payload))
    except ValueError as exc:
        return web.json_response({"error": str(exc)}, status=400)


# ============ ZAI SEARCH CONFIG ============

SEARCH_CONFIG_FILE = "/data/search_config.json"

DEFAULT_SEARCH_CONFIG = {
    "mode": "coding",          # "coding" or "legacy"
    "model": "glm-4.7-flash",  # model for coding mode
    "count": 10,               # number of results
    "recency_filter": "noLimit",  # oneDay, oneWeek, oneMonth, oneYear, noLimit
    "timeout": 120,
    "response_model": ""       # model for final response after search (empty = use main model)
}


def load_search_config() -> dict:
    """Load search config from shared volume"""
    try:
        if os.path.exists(SEARCH_CONFIG_FILE):
            with open(SEARCH_CONFIG_FILE) as f:
                saved = json.load(f)
                return {**DEFAULT_SEARCH_CONFIG, **saved}
    except Exception as e:
        log.warning(f"Failed to load search config: {e}")
    return DEFAULT_SEARCH_CONFIG.copy()


def save_search_config(config: dict):
    """Save search config to shared volume"""
    os.makedirs(os.path.dirname(SEARCH_CONFIG_FILE), exist_ok=True)
    with open(SEARCH_CONFIG_FILE, "w") as f:
        json.dump(config, f, indent=2)


async def zai_search_coding(query: str, config: dict, api_key: str) -> tuple[int, dict]:
    """ZAI search via Coding Plan (Chat Completions + tools)"""
    url = "https://api.z.ai/api/coding/paas/v4/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    body = {
        "model": config.get("model", "glm-4.7-flash"),
        "messages": [{"role": "user", "content": query}],
        "stream": False,
        "tools": [{
            "type": "web_search",
            "web_search": {
                "enable": True,
                "search_engine": "search-prime",
                "search_result": True,
                "count": config.get("count", 10),
                "search_recency_filter": config.get("recency_filter", "noLimit")
            }
        }]
    }
    timeout = aiohttp.ClientTimeout(total=config.get("timeout", 120))
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, headers=headers, timeout=timeout) as resp:
            try:
                data = await resp.json()
            except:
                raw = await resp.text()
                log.error(f"ZAI coding: failed to parse JSON, status={resp.status}, raw={raw[:200]}")
                data = {"raw": raw}
            
            log.info(f"ZAI coding: status={resp.status}, has_choices={'choices' in data}, has_web_search={'web_search' in data}, results={len(data.get('web_search', []))}")
            
            # Normalize response to match what core/tools/web.py expects
            if resp.status == 200 and "choices" in data:
                web_results = data.get("web_search", [])
                normalized = []
                for r in web_results:
                    normalized.append({
                        "title": r.get("title", ""),
                        "link": r.get("link", ""),
                        "content": r.get("content", ""),
                        "refer": r.get("refer", "")
                    })
                return resp.status, {
                    "search_result": normalized,
                    "ai_summary": data["choices"][0]["message"].get("content", ""),
                    "usage": data.get("usage", {})
                }
            return resp.status, data


async def zai_search_legacy(query: str, config: dict, api_key: str) -> tuple[int, dict]:
    """ZAI search via legacy separate endpoint"""
    url = "https://api.z.ai/api/paas/v4/web_search"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {api_key}"
    }
    body = {
        "search_engine": "search-prime",
        "search_query": query,
        "count": config.get("count", 10)
    }
    timeout = aiohttp.ClientTimeout(total=config.get("timeout", 60))
    
    async with aiohttp.ClientSession() as session:
        async with session.post(url, json=body, headers=headers, timeout=timeout) as resp:
            try:
                data = await resp.json()
            except:
                data = {"raw": await resp.text()}
            return resp.status, data


async def zai_search(request: web.Request) -> web.Response:
    """Z.AI Web Search: /zai/search?q=..."""
    runtime = load_runtime_config()
    if not runtime.zai_api_key:
        return web.json_response({"error": "ZAI not configured"}, status=500)
    
    query = request.query.get("q", "")
    search_config = load_search_config()
    mode = search_config.get("mode", "coding")
    
    log.info(f'ZAI search ({mode}): "{query[:50]}..."')
    
    try:
        if mode == "coding":
            status, data = await zai_search_coding(query, search_config, runtime.zai_api_key)
        else:
            status, data = await zai_search_legacy(query, search_config, runtime.zai_api_key)
        return web.json_response(data, status=status)
    except asyncio.TimeoutError:
        log.error("ZAI search timeout")
        return web.json_response({"error": "Search timeout"}, status=504)
    except Exception as e:
        log.error(f"ZAI error: {e}")
        return web.json_response({"error": "ZAI request failed", "message": str(e)}, status=502)


async def zai_read(request: web.Request) -> web.Response:
    """Z.AI Web Reader: /zai/read?url=..."""
    config = load_runtime_config()
    if not config.zai_api_key:
        return web.json_response({"error": "ZAI not configured"}, status=500)
    
    page_url = request.query.get("url", "")
    log.info(f'ZAI read: "{page_url[:50]}..."')
    
    try:
        url = "https://api.z.ai/api/paas/v4/reader"
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {config.zai_api_key}"
        }
        body = {
            "url": page_url,
            "return_format": "markdown",
            "retain_images": False,
            "timeout": 30
        }
        async with aiohttp.ClientSession() as session:
            async with session.post(url, json=body, headers=headers, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                try:
                    data = await resp.json()
                except:
                    data = {"raw": await resp.text()}
                return web.json_response(data, status=resp.status)
    except Exception as e:
        log.error(f"ZAI error: {e}")
        return web.json_response({"error": "ZAI request failed", "message": str(e)}, status=502)


async def classify_response(request: web.Request) -> web.Response:
    """
    LLM-based classifier: should the userbot respond to this message?
    Uses structured output to get a simple yes/no decision with reasoning.
    """
    config = load_runtime_config()
    if not config.llm_base_url:
        return web.json_response({"error": "LLM not configured"}, status=503)
    
    try:
        data = await request.json()
    except:
        return web.json_response({"error": "Invalid JSON"}, status=400)
    
    messages = data.get("messages", [])  # Last N messages for context
    current_message = data.get("current_message", "")
    sender_name = data.get("sender_name", "user")
    chat_type = data.get("chat_type", "group")  # "private" or "group"
    bot_username = data.get("bot_username", "")
    is_reply_to_bot = data.get("is_reply_to_bot", False)
    is_mention = data.get("is_mention", False)
    
    # Build context string from recent messages
    context_lines = []
    for msg in messages[-10:]:  # Last 10 messages
        author = msg.get("author", "unknown")
        text = msg.get("text", "")[:200]  # Truncate long messages
        context_lines.append(f"{author}: {text}")
    
    context = "\n".join(context_lines) if context_lines else "(no previous context)"
    
    # Classifier prompt
    classifier_prompt = f"""You are a response classifier for a Telegram userbot. 
Analyze the conversation and decide if the bot should respond to the latest message.

CONTEXT (recent messages):
{context}

CURRENT MESSAGE from {sender_name}:
"{current_message}"

METADATA:
- Chat type: {chat_type}
- Bot username: @{bot_username}
- Is reply to bot: {is_reply_to_bot}
- Is @mention of bot: {is_mention}

RESPOND with JSON only:
{{"should_respond": true/false, "confidence": 0.0-1.0, "reason": "brief explanation"}}

GUIDELINES for should_respond=true:
- Direct questions or requests for help
- Technical discussions where bot can add value
- When explicitly mentioned or replied to
- Interesting conversations where bot has relevant knowledge

GUIDELINES for should_respond=false:
- Casual chat between humans (greetings, jokes, small talk)
- Messages not directed at anyone specific
- Spam, ads, or off-topic content
- When someone else is clearly being addressed
- Very short messages like "ok", "lol", "да", "+1"
- Bot already responded recently to similar topic

Respond ONLY with valid JSON, no other text."""

    # Make fast LLM call with low tokens
    llm_payload = {
        "model": data.get("model", config.model_name),
        "messages": [
            {"role": "system", "content": "You are a response classifier. Output only valid JSON."},
            {"role": "user", "content": classifier_prompt}
        ],
        "max_tokens": 200,
        "temperature": 0.1,  # Low temperature for consistent decisions
    }
    
    # Note: response_format=json_object not always supported, relying on prompt instead
    
    base = config.llm_base_url.rstrip("/")
    if base.endswith("/chat/completions"):
        target_url = base
    elif base.endswith("/v1"):
        target_url = base + "/chat/completions"
    else:
        target_url = base.rstrip("/v1").rstrip("/") + "/v1/chat/completions"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.llm_api_key}"
    }
    
    log.info(f"Classifier: {chat_type} from {sender_name}: {current_message[:50]}...")
    
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                target_url,
                json=llm_payload,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=10)  # Fast timeout
            ) as resp:
                if resp.status != 200:
                    error_text = await resp.text()
                    log.error(f"Classifier LLM error: {resp.status} - {error_text[:200]}")
                    # Fallback: respond if mentioned or replied to
                    return web.json_response({
                        "should_respond": is_mention or is_reply_to_bot,
                        "confidence": 0.5,
                        "reason": "LLM error, using fallback",
                        "fallback": True
                    })
                
                result = await resp.json()
                
                # Debug log
                log.info(f"LLM response: {str(result)[:500]}")
                
                # Extract content from various response formats
                content = None
                if "choices" in result and result["choices"]:
                    choice = result["choices"][0]
                    if "message" in choice and choice["message"]:
                        content = choice["message"].get("content")
                    elif "text" in choice:
                        content = choice["text"]
                
                if not content:
                    # Fallback for unusual response formats
                    log.warning(f"No content in LLM response, using fallback")
                    return web.json_response({
                        "should_respond": is_mention or is_reply_to_bot,
                        "confidence": 0.5,
                        "reason": "No content in LLM response",
                        "fallback": True
                    })
                
                # Parse JSON response
                try:
                    # Clean content - remove markdown code blocks if present
                    clean_content = content.strip()
                    if clean_content.startswith("```"):
                        # Remove ```json and ``` markers
                        lines = clean_content.split("\n")
                        clean_content = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])
                    
                    decision = json.loads(clean_content)
                    should_respond = decision.get("should_respond", False)
                    confidence = decision.get("confidence", 0.5)
                    reason = decision.get("reason", "no reason")
                    
                    log.info(f"Classifier decision: {should_respond} ({confidence:.0%}) - {reason}")
                    
                    return web.json_response({
                        "should_respond": should_respond,
                        "confidence": confidence,
                        "reason": reason
                    })
                except json.JSONDecodeError as e:
                    # Try to extract yes/no from text
                    log.warning(f"JSON parse error: {e}, content: {content[:200]}")
                    content_lower = content.lower()
                    should_respond = "true" in content_lower or "\"should_respond\": true" in content_lower
                    return web.json_response({
                        "should_respond": should_respond,
                        "confidence": 0.5,
                        "reason": f"Parsed from text: {content[:80]}...",
                        "parse_fallback": True
                    })
                    
    except asyncio.TimeoutError:
        log.warning("Classifier timeout, using fallback")
        return web.json_response({
            "should_respond": is_mention or is_reply_to_bot,
            "confidence": 0.5,
            "reason": "Timeout, using fallback",
            "fallback": True
        })
    except Exception as e:
        log.error(f"Classifier error: {e}")
        return web.json_response({
            "should_respond": is_mention or is_reply_to_bot,
            "confidence": 0.5,
            "reason": f"Error: {e}",
            "fallback": True
        })


async def search_config_handler(request: web.Request) -> web.Response:
    """GET/PUT /zai/config - manage search configuration"""
    if request.method == "GET":
        return web.json_response(load_search_config())
    
    # PUT - update config
    try:
        body = await request.json()
        config = load_search_config()
        # Only allow known keys
        for key in ["mode", "model", "count", "recency_filter", "timeout", "response_model"]:
            if key in body:
                config[key] = body[key]
        # Validate mode
        if config["mode"] not in ("coding", "legacy"):
            return web.json_response({"error": "mode must be 'coding' or 'legacy'"}, status=400)
        save_search_config(config)
        log.info(f"Search config updated: {config}")
        return web.json_response({"success": True, **config})
    except Exception as e:
        return web.json_response({"error": str(e)}, status=400)


async def not_found(request: web.Request) -> web.Response:
    """Handle unknown routes"""
    return web.json_response({
        "error": "Not found",
        "routes": ["/v1/*", "/transcribe", "/zai/search?q=...", "/zai/read?url=...", "/classify", "/health", "/ready"]
    }, status=404)


def create_app() -> web.Application:
    """Create aiohttp application"""
    app = web.Application(middlewares=[observability_middleware])
    
    # Routes
    app.router.add_get("/health", health)
    app.router.add_get("/ready", ready)
    app.router.add_get("/metrics", metrics_handler)
    app.router.add_route("*", "/v1/{path:.*}", proxy_llm)
    app.router.add_post("/transcribe", proxy_transcribe)
    app.router.add_get("/zai/search", zai_search)
    app.router.add_get("/zai/read", zai_read)
    app.router.add_post("/classify", classify_response)
    app.router.add_route("*", "/zai/config", search_config_handler)
    
    # Catch-all for 404
    app.router.add_route("*", "/{path:.*}", not_found)
    
    return app


def main():
    config = load_runtime_config()
    log.info("Starting API proxy...")
    log.info(f"LLM endpoint: {'✓ configured' if config.llm_base_url else '✗ NOT SET'}")
    log.info(f"ZAI API: {'✓ configured' if config.zai_api_key else '✗ NOT SET'}")
    log.info("Embeddings backend: %s", LOCAL_EMBEDDING_MODEL)
    
    app = create_app()
    web.run_app(app, host="0.0.0.0", port=PORT, print=lambda x: log.info(x))


if __name__ == "__main__":
    main()
