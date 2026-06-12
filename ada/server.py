"""
Ada — a structured memory substrate for LLMs.

Single FastAPI server exposing one MCP endpoint (/mcp) with the cognitive
tools (think / ask / tell / tell_raw / recall / history / stats).

Importable as ``ada.server:app``.
"""

import logging
from contextlib import asynccontextmanager
from datetime import datetime
from typing import AsyncGenerator, Optional

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from infrastructure.config import get_settings, validate_settings
from infrastructure.database import init_db, close_db, async_session_maker
from shared.exceptions import AdaRuntimeException
from shared.middleware import (
    CorrelationIDMiddleware,
    LoggingMiddleware,
)

# Configure structured logging
logging.basicConfig(
    level=logging.INFO,
    format='{"timestamp": "%(asctime)s", "level": "%(levelname)s", "logger": "%(name)s", "message": "%(message)s"}'
)
logger = logging.getLogger(__name__)

settings = get_settings()
_start_time = datetime.utcnow()

# ── Global brain state ───────────────────────────────────────────────────────

brain: Optional[object] = None  # domains.brain.think.Brain — set in lifespan


def get_brain():
    return brain


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Boot Ada's brain."""
    global brain

    logger.info("Waking up...")

    # Validate config
    try:
        validate_settings()
    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        raise

    # Database
    await init_db()
    logger.info("Memory banks online")

    # ── Initialize Ada's LLM ────────────────────────────────────────────
    from domains.brain.llm import AdaLLM

    llm = AdaLLM()
    app.state.llm = llm

    # ── Initialize the think pipeline ───────────────────────────────────
    # The enricher maps natural-language `tell`s into universal-schema
    # slots at write time (LLM if a key is present, regex fallback if not).
    from ada.encoder.llm_enricher import auto_enricher
    from domains.brain.think import Brain

    brain = Brain(
        llm=llm,
        session_factory=async_session_maker,
        enricher=auto_enricher(),
        storage_mode=settings.storage_mode,
    )
    app.state.brain = brain

    # ── Restore persisted memories ──────────────────────────────────────
    # Memory mode loads the main space into RAM (the chat pipeline reads
    # it). SQL mode skips the load entirely — O(1) boot, reads hit
    # fact_slots directly — and the chat space stays seed-only.
    if settings.storage_mode == "sql":
        logger.info("Storage mode: sql — facts served from fact_slots, "
                    "O(1) boot (chat uses an in-memory seed space)")
    else:
        from ada.memory.thought_persistence import load_thoughts
        loaded = await load_thoughts(async_session_maker, brain.cognitive.thought_space)
        if loaded:
            logger.info(f"Restored {loaded} memories from database")
        else:
            logger.info(f"No persisted memories — using {brain.cognitive.thought_space.count} seed memories")

    logger.info("Think pipeline online")

    # ── Initialize MCP ──────────────────────────────────────────────────
    from domains.auth.service import AuthService
    from domains.mcp.app import create_mcp_session_managers

    auth_service = AuthService()
    app.state.auth_service = auth_service
    json_manager, sse_manager = create_mcp_session_managers(brain, auth_service)
    app.state.mcp_session_managers = (json_manager, sse_manager)
    if settings.auth_required:
        logger.info("MCP endpoint online at /mcp (token auth REQUIRED)")
    else:
        logger.warning("MCP endpoint online at /mcp with auth DISABLED — "
                       "set ADA_AUTH_REQUIRED=true for any non-local deployment")

    # ── Start background persistence worker ─────────────────────────────
    import asyncio

    async def _persist_worker():
        """Flush thought queue to SQLite every 2 seconds."""
        while True:
            try:
                saved = await brain.flush_persist_queue()
                if saved:
                    logger.debug(f"Persisted {saved} thoughts")
            except Exception:
                pass
            await asyncio.sleep(2.0)

    persist_task = asyncio.create_task(_persist_worker())

    logger.info("Ada is awake.")

    # Run MCP session managers
    async with json_manager.run():
        async with sse_manager.run():
            yield

    # ── Shutdown ─────────────────────────────────────────────────────────
    logger.info("Going to sleep...")
    persist_task.cancel()
    # Final flush — don't lose queued thoughts
    await brain.flush_persist_queue()

    await close_db()
    logger.info("Ada is asleep.")


# Create FastAPI application
app = FastAPI(
    title="Ada",
    description="A structured memory substrate for LLMs",
    version="0.1.0",
    docs_url="/docs" if settings.enable_docs else None,
    redoc_url="/redoc" if settings.enable_docs else None,
    lifespan=lifespan,
)

# CORS middleware
if settings.cors_allow_all:
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=False,
        allow_methods=["*"],
        allow_headers=["*"],
    )
else:
    origins = settings.cors_origins_production or settings.cors_origins
    app.add_middleware(
        CORSMiddleware,
        allow_origins=origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH"],
        allow_headers=["*"],
    )

# Custom middleware
app.add_middleware(CorrelationIDMiddleware)
app.add_middleware(LoggingMiddleware)


# Global exception handlers
@app.exception_handler(AdaRuntimeException)
async def runtime_exception_handler(request: Request, exc: AdaRuntimeException) -> JSONResponse:
    """Handle custom runtime exceptions with CORS headers"""
    response = JSONResponse(
        status_code=exc.status_code,
        content={
            "error": {
                "code": exc.error_code,
                "message": exc.message,
                "details": exc.details,
                "correlation_id": getattr(request.state, "correlation_id", "unknown"),
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        }
    )
    origin = request.headers.get("origin")
    if origin and _is_allowed_origin(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """Handle unexpected exceptions with CORS headers"""
    logger.error(f"Unexpected error: {exc}", exc_info=True)
    response = JSONResponse(
        status_code=500,
        content={
            "error": {
                "code": "INTERNAL_SERVER_ERROR",
                "message": "An unexpected error occurred",
                "correlation_id": getattr(request.state, "correlation_id", "unknown"),
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        }
    )
    origin = request.headers.get("origin")
    if origin and _is_allowed_origin(origin):
        response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Credentials"] = "true"
    return response


def _is_allowed_origin(origin: str) -> bool:
    """Check if origin is in allowed CORS origins list."""
    if settings.cors_allow_all:
        return True
    import fnmatch
    origins = settings.cors_origins_production or settings.cors_origins
    for allowed in origins:
        if allowed == "*" or allowed == origin:
            return True
        if fnmatch.fnmatch(origin, allowed):
            return True
    return False


# Import and include routers
from api.routes import health_router, tokens_router

app.include_router(health_router)
app.include_router(tokens_router)


# MCP routing middleware — intercepts /mcp requests and forwards to the
# MCP SDK's Streamable HTTP handler. Single endpoint, no org/model.
from domains.mcp.app import MCPRoutingMiddleware

app.add_middleware(
    MCPRoutingMiddleware,
    mcp_app_getter=lambda: getattr(app.state, "mcp_session_managers", None),
    auth_getter=lambda: getattr(app.state, "auth_service", None),
    auth_required=settings.auth_required,
)
