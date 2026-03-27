"""
Tools API - Single source of truth for agent tools

Provides:
- Built-in tool definitions
- MCP server management
- Skills system (Anthropic-style)
- Dynamic tool loading
"""

import logging
from fastapi import FastAPI
from contextlib import asynccontextmanager

from src.mcp import mcp_cache
from src.observability import instrument_fastapi, setup_observability
from src.skills import skills_manager
from src.routes import tools_router, mcp_router, skills_router, corp_db_router

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


# Health check
@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": "3.0",
        "mcp_enabled": True,
        "skills_enabled": True
    }


# Include routers
app.include_router(tools_router)
app.include_router(mcp_router)
app.include_router(skills_router)
app.include_router(corp_db_router)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8100)
