"""
Tools API - Single source of truth for agent tools

Provides:
- Built-in tool definitions
- MCP server management
- Skills system (Anthropic-style)
- Dynamic tool loading
"""

import logging
import os
from contextlib import asynccontextmanager

import asyncpg
from fastapi import FastAPI

from src.mcp import mcp_cache
from src.observability import instrument_fastapi, setup_observability
from src.skills import skills_manager
from src.routes import tools_router, mcp_router, skills_router, corp_db_router
from src.routes.corp_db import _get_ro_dsn

setup_observability("tools-api")
logger = logging.getLogger("tools-api")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup and shutdown events"""
    # Startup
    logger.info("Starting up")
    mcp_cache.load_cache()
    skills_manager.load_cache()
    skills_manager.scan_all()
    logger.info("Loaded %s MCP tools, %s skills", len(mcp_cache.tools), len(skills_manager.skills))
    
    yield
    
    # Shutdown
    logger.info("Shutting down")


app = FastAPI(
    title="Tools API",
    version="3.0",
    description="Single source of truth for agent tools, MCP servers, and skills",
    lifespan=lifespan
)
instrument_fastapi(app)


def _build_runtime_info() -> dict[str, str]:
    return {
        "git_sha": str(os.getenv("BUILD_GIT_SHA", "unknown") or "unknown"),
        "build_time": str(os.getenv("BUILD_TIME", "unknown") or "unknown"),
    }


async def _corp_db_rfc026_health() -> dict[str, object]:
    query = """
    SELECT json_build_object(
        'sphere_curated_categories_table', to_regclass('corp.sphere_curated_categories') IS NOT NULL,
        'categories_parent_category_id_column', EXISTS (
            SELECT 1
            FROM information_schema.columns
            WHERE table_schema = 'corp'
              AND table_name = 'categories'
              AND column_name = 'parent_category_id'
        )
    )::text;
    """
    try:
        conn = await asyncpg.connect(_get_ro_dsn())
    except Exception as exc:
        return {"applied": False, "error": str(exc)[:300]}
    try:
        raw = await conn.fetchval(query)
    except Exception as exc:
        await conn.close()
        return {"applied": False, "error": str(exc)[:300]}
    await conn.close()
    try:
        import json
        payload = json.loads(raw or "{}")
    except Exception as exc:
        return {"applied": False, "error": f"invalid_payload:{exc}"}
    applied = bool(payload.get("sphere_curated_categories_table")) and bool(payload.get("categories_parent_category_id_column"))
    return {"applied": applied, "details": payload}


# Health check
@app.get("/health")
async def health():
    corp_db_rfc026 = await _corp_db_rfc026_health()
    return {
        "status": "ok",
        "service": "tools-api",
        "version": "3.0",
        "build": _build_runtime_info(),
        "mcp_enabled": True,
        "skills_enabled": True,
        "corp_db_rfc026": corp_db_rfc026,
    }


# Include routers
app.include_router(tools_router)
app.include_router(mcp_router)
app.include_router(skills_router)
app.include_router(corp_db_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8100)
