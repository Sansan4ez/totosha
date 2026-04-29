"""FastAPI HTTP API"""

import os
import aiohttp
from fastapi import FastAPI, Response
from opentelemetry import trace
from pydantic import BaseModel
from time import perf_counter
from typing import Optional

from config import CONFIG, get_model, get_temperature, get_max_iterations
from logger import api_logger, log_request, log_response
from models import ChatResponsePayload
from observability import (
    REQUEST_ID,
    correlation_scope,
    inject_trace_context,
    instrument_fastapi,
    observe_chat_request,
    update_correlation_context,
)
from agent import run_agent, sessions
from run_meta import run_meta_reset, run_meta_set
from tool_output_policy import EXECUTION_MODE_RUNTIME, normalize_execution_mode
from tools.scheduler import scheduler
from admin_api import router as admin_router, load_config as load_admin_config
from web_artifacts import extract_ui_artifact


app = FastAPI(title="Core Agent API")
instrument_fastapi(app)
app.include_router(admin_router)
SUPPORTED_CHAT_SOURCES = {"bot", "userbot", "web"}


def _trace_meta() -> tuple[str, str]:
    span_context = trace.get_current_span().get_span_context()
    if span_context and span_context.is_valid:
        return format(span_context.trace_id, "032x"), format(span_context.span_id, "016x")
    return "-", "-"


def _build_runtime_info() -> dict[str, str]:
    return {
        "git_sha": str(os.getenv("BUILD_GIT_SHA", "unknown") or "unknown"),
        "build_time": str(os.getenv("BUILD_TIME", "unknown") or "unknown"),
        "route_selector_enabled": "true" if os.getenv("ROUTE_SELECTOR_ENABLED", "true").strip().lower() not in {"0", "false", "no", "off"} else "false",
    }


class ChatRequest(BaseModel):
    user_id: int
    chat_id: int
    message: str
    username: Optional[str] = ""
    chat_type: Optional[str] = "private"
    source: Optional[str] = "bot"
    return_meta: Optional[bool] = False
    execution_mode: Optional[str] = EXECUTION_MODE_RUNTIME


class ClearRequest(BaseModel):
    user_id: int
    chat_id: int


class WebSessionReclaimRequest(BaseModel):
    user_id: int
    chat_id: int


class SchedulerCallbackRequest(BaseModel):
    chat_id: int
    text: str


def _build_run_meta(*, execution_mode: str) -> dict:
    return {
        "execution_mode": normalize_execution_mode(execution_mode),
        "request_id": REQUEST_ID.get("-"),
        "request_source": "-",
        "trace_id": "-",
        "span_id": "-",
        "model": get_model(),
        "temperature": get_temperature(),
        "max_iterations": get_max_iterations(),
        "llm_calls": 0,
        "llm_time_ms": 0.0,
        "llm_usage": None,
        "llm_models": [],
        "context_trim_events": 0,
        "context_trim_pre_chars_max": 0,
        "context_trim_post_chars_max": 0,
        "context_trim_removed_messages_total": 0,
        "context_trim_truncated_messages_total": 0,
        "context_trim_hard_stops": 0,
        "context_trim_last_stage": "",
        "context_trim_last_pre_chars": 0,
        "context_trim_last_post_chars": 0,
        "context_trim_last_removed_messages": 0,
        "context_trim_last_truncated_messages": 0,
        "context_trim_last_hard_stop": False,
        "context_trim_last_reason": "",
        "tools_used": [],
        "tool_stats": {},
        "tools_time_ms": 0.0,
        "had_search_tool": False,
        "tool_errors": 0,
        "retrieval_intent": "",
        "retrieval_selected_source": "unknown",
        "retrieval_route_id": "",
        "retrieval_route_source": "",
        "retrieval_selected_route_kind": "",
        "retrieval_candidate_route_ids": [],
        "retrieval_route_family": "",
        "retrieval_phase": "",
        "retrieval_evidence_status": "",
        "retrieval_retry_count": 0,
        "retrieval_close_reason": "",
        "retrieval_validated_arg_keys": [],
        "retrieval_validation_errors": [],
        "retrieval_fallback_route_ids": [],
        "route_selector_status": "",
        "route_selector_model": "",
        "route_selector_latency_ms": 0.0,
        "route_selector_confidence": "",
        "route_selector_reason": "",
        "route_selector_repair_attempted": False,
        "route_selector_repair_status": "",
        "route_selector_validation_error_code": "",
        "route_selector_validation_error": "",
        "routing_catalog_version": "",
        "routing_catalog_origin": "",
        "routing_schema_version": 0,
        "knowledge_route_id": "",
        "document_id": "",
        "source_file_scope": [],
        "topic_facets": [],
        "finalizer_mode": "",
        "retrieval_explicit_wiki_request": False,
        "routing_guardrail_hits": 0,
        "company_fact_intent_type": "",
        "company_fact_payload_relevant": False,
        "company_fact_finalizer_mode": "",
        "company_fact_runtime_payload_format": "",
        "company_fact_bench_payload_format": "",
        "tool_runtime_output_formats": {},
        "tool_bench_output_formats": {},
        "bench_artifacts": [],
        "primary_artifact": None,
        "bench_artifacts_total_bytes": 0,
        "bench_artifacts_dropped": 0,
    }


def _build_chat_payload(
    *,
    response: Optional[str],
    source: str,
    ui_artifact: Optional[dict] = None,
    disabled: bool = False,
    access_denied: bool = False,
    error: Optional[str] = None,
    meta: Optional[dict] = None,
    extra: Optional[dict] = None,
) -> dict:
    payload = {"response": response}
    if disabled:
        payload["disabled"] = True
    if access_denied:
        payload["access_denied"] = True
    if meta is not None:
        payload["meta"] = meta
    if extra:
        payload.update(extra)
    if source == "web":
        web_payload = ChatResponsePayload(
            response=response,
            source="web",
            disabled=disabled,
            access_denied=access_denied,
            ui_artifact=ui_artifact,
            conversation={"persisted": False},
            error=error,
            meta=meta,
        ).__dict__.copy()
        payload["source"] = web_payload["source"]
        payload["ui_artifact"] = web_payload["ui_artifact"]
        payload["conversation"] = web_payload["conversation"]
        if error is not None:
            payload["error"] = error
    return payload


def _resolve_source(source: Optional[str]) -> str:
    resolved = str(source or "bot").strip().lower() or "bot"
    if resolved not in SUPPORTED_CHAT_SOURCES:
        raise ValueError(f"Unsupported source: {resolved}")
    return resolved


def _is_channel_enabled(access: dict, source: str) -> bool:
    if source == "bot":
        return access.get("bot_enabled", True)
    if source == "userbot":
        return access.get("userbot_enabled", True)
    if source == "web":
        return access.get("web_enabled", CONFIG.web_enabled)
    return False


def _apply_meta_correlation(meta: dict, source: str) -> None:
    update_correlation_context(
        request_source=source,
        selected_route_id=str(meta.get("retrieval_route_id") or ""),
        selected_route_family=str(meta.get("retrieval_route_family") or ""),
        selected_route_kind=str(meta.get("retrieval_selected_route_kind") or ""),
        selected_source=str(meta.get("retrieval_selected_source") or "unknown"),
        knowledge_route_id=str(meta.get("knowledge_route_id") or ""),
        document_id=str(meta.get("document_id") or ""),
        retrieval_phase=str(meta.get("retrieval_phase") or ""),
        retrieval_evidence_status=str(meta.get("retrieval_evidence_status") or ""),
        retrieval_close_reason=str(meta.get("retrieval_close_reason") or ""),
        route_selector_status=str(meta.get("route_selector_status") or ""),
        routing_catalog_version=str(meta.get("routing_catalog_version") or ""),
        routing_guardrail_hits=int(meta.get("routing_guardrail_hits") or 0),
        finalizer_mode=str(meta.get("finalizer_mode") or ""),
    )


# --- Callbacks for scheduler ---

async def send_to_bot(chat_id: int, text: str):
    """Send message via bot"""
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{CONFIG.bot_url}/send",
                json={"chat_id": chat_id, "text": text},
                headers=inject_trace_context(),
                timeout=aiohttp.ClientTimeout(total=10)
            )
        api_logger.info(f"Sent to bot: chat={chat_id}")
    except Exception as e:
        api_logger.error(f"Failed to send to bot: {e}")


async def send_to_userbot(chat_id: int, text: str):
    """Send message via userbot"""
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{CONFIG.userbot_url}/send",
                json={"chat_id": chat_id, "text": text},
                headers=inject_trace_context(),
                timeout=aiohttp.ClientTimeout(total=10)
            )
        api_logger.info(f"Sent to userbot: chat={chat_id}")
    except Exception as e:
        api_logger.error(f"Failed to send to userbot: {e}")


async def run_scheduled_agent(user_id: int, chat_id: int, prompt: str, source: str):
    """Run agent for scheduled task"""
    api_logger.info(f"Running scheduled agent: user={user_id}, source={source}")
    response = await run_agent(user_id, chat_id, prompt, "", "private", source)
    
    if source == "userbot":
        await send_to_userbot(chat_id, response)
    else:
        await send_to_bot(chat_id, response)


# --- API Endpoints ---

@app.on_event("startup")
async def startup():
    api_logger.info(f"Core API starting on port {CONFIG.api_port}")
    api_logger.info(f"Proxy: {CONFIG.proxy_url}")
    api_logger.info(f"Bot URL: {CONFIG.bot_url}")
    api_logger.info(f"Userbot URL: {CONFIG.userbot_url}")
    
    # Configure scheduler callbacks
    scheduler.set_callbacks(
        send_message=send_to_bot,
        send_userbot=send_to_userbot,
        run_agent=run_scheduled_agent
    )
    
    # Start scheduler
    import asyncio
    asyncio.create_task(scheduler.start())


@app.get("/health")
async def health(response: Response):
    from documents import routing_catalog_health

    catalog_health = routing_catalog_health()
    runtime = _build_runtime_info()
    if catalog_health.get("status") == "unavailable":
        response.status_code = 503
        return {"status": "unavailable", "service": "core", "build": runtime, "routing_catalog": catalog_health}
    return {"status": "ok", "service": "core", "build": runtime, "routing_catalog": catalog_health}


@app.get("/health/routing")
async def routing_health(response: Response):
    from documents import routing_catalog_health

    catalog_health = routing_catalog_health()
    if catalog_health.get("status") != "ok":
        response.status_code = 503
    return catalog_health


@app.post("/api/chat")
async def chat(req: ChatRequest):
    # Check access control
    admin_config = load_admin_config()
    access = admin_config.get("access", {})
    try:
        source = _resolve_source(req.source)
    except ValueError as exc:
        api_logger.info("Unsupported chat source %s", req.source)
        return _build_chat_payload(
            response=None,
            source="bot",
            extra={"unsupported_source": True, "error": str(exc)},
        )
    user_id = req.user_id

    with correlation_scope(request_source=source):
        # Check access mode
        mode = access.get("mode", "admin_only")
        admin_id = access.get("admin_id", int(os.getenv("ADMIN_USER_ID", "0")))
        allowlist = access.get("allowlist", [])

        if not _is_channel_enabled(access, source):
            api_logger.info("%s access disabled, rejecting request from %s", source, user_id)
            observe_chat_request(source, "disabled", 0.0)
            return _build_chat_payload(response=None, source=source, disabled=True)

        has_access = False
        if mode == "public":
            has_access = True
        elif mode == "admin_only":
            has_access = (user_id == admin_id)
        elif mode == "allowlist":
            has_access = (user_id == admin_id) or (user_id in allowlist)

        if not has_access:
            api_logger.info(f"Access denied for {user_id} (mode={mode})")
            observe_chat_request(source, "access_denied", 0.0)
            return _build_chat_payload(
                response=None,
                source=source,
                access_denied=True,
                extra={"mode": mode},
            )

        log_request(req.user_id, req.chat_id, req.username or "", source, req.message)

        execution_mode = normalize_execution_mode(req.execution_mode)
        meta = _build_run_meta(execution_mode=execution_mode)
        meta["request_source"] = source
        meta["conversation_persisted"] = source != "web"
        token = run_meta_set(meta)
        started = perf_counter()

        try:
            response = await run_agent(
                user_id=req.user_id,
                chat_id=req.chat_id,
                message=req.message,
                username=req.username or "",
                chat_type=req.chat_type or "private",
                source=source,
                execution_mode=execution_mode,
            )

            response, ui_artifact = extract_ui_artifact(response, source)
            log_response(response)
            meta["trace_id"], meta["span_id"] = _trace_meta()
            meta["duration_ms"] = (perf_counter() - started) * 1000
            meta["iterations"] = int(meta.get("llm_calls", 0))
            meta["final_response_chars"] = len(response or "")
            meta["ui_artifact_type"] = (
                str(ui_artifact.get("type") or "")
                if isinstance(ui_artifact, dict)
                else ""
            )
            meta["status"] = "ok"
            _apply_meta_correlation(meta, source)
            observe_chat_request(source, "ok", meta["duration_ms"])
            return _build_chat_payload(
                response=response,
                source=source,
                ui_artifact=ui_artifact,
                meta=meta if req.return_meta else None,
            )

        except Exception as e:
            api_logger.error(f"Chat error: {e}")
            meta["trace_id"], meta["span_id"] = _trace_meta()
            meta["duration_ms"] = (perf_counter() - started) * 1000
            meta["status"] = "error"
            meta["error"] = str(e)
            _apply_meta_correlation(meta, source)
            observe_chat_request(source, "error", meta["duration_ms"])
            return _build_chat_payload(
                response=f"Error: {e}",
                source=source,
                error=str(e),
                meta=meta if req.return_meta else None,
            )
        finally:
            run_meta_reset(token)


@app.post("/api/clear")
async def clear(req: ClearRequest):
    sessions.clear(req.user_id, req.chat_id)
    api_logger.info(f"Session cleared: {req.user_id}_{req.chat_id}")
    return {"status": "cleared"}


@app.post("/api/web/session/reclaim")
async def reclaim_web_session(req: WebSessionReclaimRequest):
    reclaimed = sessions.reclaim(req.user_id, req.chat_id, source="web")
    api_logger.info(f"Web session reclaim requested: {req.user_id}_{req.chat_id}, reclaimed={reclaimed}")
    return {"status": "ok", "reclaimed": reclaimed}
