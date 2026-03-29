"""FastAPI HTTP API"""

import os
import aiohttp
from fastapi import FastAPI
from pydantic import BaseModel
from time import perf_counter
from typing import Optional

from config import CONFIG, get_model, get_temperature, get_max_iterations
from logger import api_logger, log_request, log_response
from observability import REQUEST_ID, instrument_fastapi
from agent import run_agent, sessions
from run_meta import run_meta_reset, run_meta_set
from tools.scheduler import scheduler
from admin_api import router as admin_router, load_config as load_admin_config


app = FastAPI(title="Core Agent API")
instrument_fastapi(app)
app.include_router(admin_router)


class ChatRequest(BaseModel):
    user_id: int
    chat_id: int
    message: str
    username: Optional[str] = ""
    chat_type: Optional[str] = "private"
    source: Optional[str] = "bot"
    return_meta: Optional[bool] = False


class ClearRequest(BaseModel):
    user_id: int
    chat_id: int


class SchedulerCallbackRequest(BaseModel):
    chat_id: int
    text: str


# --- Callbacks for scheduler ---

async def send_to_bot(chat_id: int, text: str):
    """Send message via bot"""
    try:
        async with aiohttp.ClientSession() as session:
            await session.post(
                f"{CONFIG.bot_url}/send",
                json={"chat_id": chat_id, "text": text},
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
async def health():
    return {"status": "ok", "service": "core"}


@app.post("/api/chat")
async def chat(req: ChatRequest):
    # Check access control
    admin_config = load_admin_config()
    access = admin_config.get("access", {})
    source = req.source or "bot"
    user_id = req.user_id
    
    # Check if service is enabled
    if source == "bot" and not access.get("bot_enabled", True):
        api_logger.info(f"Bot access disabled, rejecting request from {user_id}")
        return {"response": None, "disabled": True}
    
    if source == "userbot" and not access.get("userbot_enabled", True):
        api_logger.info(f"Userbot access disabled, rejecting request from {user_id}")
        return {"response": None, "disabled": True}
    
    # Check access mode
    mode = access.get("mode", "admin_only")
    admin_id = access.get("admin_id", int(os.getenv("ADMIN_USER_ID", "0")))
    allowlist = access.get("allowlist", [])
    
    has_access = False
    if mode == "public":
        has_access = True
    elif mode == "admin_only":
        has_access = (user_id == admin_id)
    elif mode == "allowlist":
        has_access = (user_id == admin_id) or (user_id in allowlist)
    
    if not has_access:
        api_logger.info(f"Access denied for {user_id} (mode={mode})")
        return {"response": None, "access_denied": True, "mode": mode}
    
    log_request(req.user_id, req.chat_id, req.username or "", source, req.message)
    
    token = None
    meta = None
    started = perf_counter()
    if req.return_meta:
        meta = {
            "request_id": REQUEST_ID.get("-"),
            "model": get_model(),
            "temperature": get_temperature(),
            "max_iterations": get_max_iterations(),
            "llm_calls": 0,
            "llm_time_ms": 0.0,
            "llm_usage": None,
            "llm_models": [],
            "tools_used": [],
            "tool_stats": {},
            "tools_time_ms": 0.0,
            "had_search_tool": False,
            "tool_errors": 0,
        }
        token = run_meta_set(meta)

    try:
        response = await run_agent(
            user_id=req.user_id,
            chat_id=req.chat_id,
            message=req.message,
            username=req.username or "",
            chat_type=req.chat_type or "private",
            source=source
        )
        
        log_response(response)
        if meta is not None:
            meta["duration_ms"] = (perf_counter() - started) * 1000
            meta["iterations"] = int(meta.get("llm_calls", 0))
            meta["final_response_chars"] = len(response or "")
            meta["status"] = "ok"
            return {"response": response, "meta": meta}
        return {"response": response}
    
    except Exception as e:
        api_logger.error(f"Chat error: {e}")
        if meta is not None:
            meta["duration_ms"] = (perf_counter() - started) * 1000
            meta["status"] = "error"
            meta["error"] = str(e)
            return {"response": f"Error: {e}", "meta": meta}
        return {"response": f"Error: {e}"}
    finally:
        if token is not None:
            run_meta_reset(token)


@app.post("/api/clear")
async def clear(req: ClearRequest):
    sessions.clear(req.user_id, req.chat_id)
    api_logger.info(f"Session cleared: {req.user_id}_{req.chat_id}")
    return {"status": "cleared"}
