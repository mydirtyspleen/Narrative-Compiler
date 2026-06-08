"""
ADM-API v1 — AI Dungeon Master Infrastructure API

A deterministic real-time narrative infrastructure layer for
multiplayer simulation systems.

  GAME EVENTS → ADM-API → STRUCTURED NARRATIVE STATE

This is NOT a story generator.
This is a deterministic narrative compiler — infrastructure for
game developers and simulation engineers.
"""

from __future__ import annotations

import os
import time
from collections import defaultdict
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import ValidationError

from adm_api.api.admin_routes import router as admin_router
from adm_api.api.playground_routes import router as playground_router
from adm_api.api.replay_routes import router as replay_router
from adm_api.api.routes import router as v1_router
from adm_api.observability.logger import log_auth_failure, log_rate_limit_violation, log_request, logger
from adm_api.observability.metrics import metrics

BASE_PATH = os.environ.get("BASE_PATH", "/api").rstrip("/")

# ============================================================================
# Application
# ============================================================================

app = FastAPI(
    title       = "ADM-API",
    version     = "1.0.0",
    description = (
        "## AI Dungeon Master Infrastructure API\n\n"
        "A **deterministic real-time narrative compiler** for multiplayer simulation systems.\n\n"
        "```\nGAME EVENTS  →  ADM-API  →  STRUCTURED NARRATIVE STATE\n```\n\n"
        "ADM-API is infrastructure, not a game. Same input always returns byte-identical output.\n"
        "No AI dependency in the hot path. No stochastic state.\n\n"
        "---\n\n"
        "### Authentication\n"
        "Pass your API key on every `/v1/` request:\n"
        "```\nX-API-Key: adm_test_...\n```\n"
        "or via `Authorization: Bearer adm_test_...`\n\n"
        "### Getting a key\n"
        "- **Test key**: printed to server stdout on first boot\n"
        "- **New key**: `POST /v1/admin/keys` with `X-Admin-Key` header\n"
        "- **No key needed**: try `POST /v1/playground/render` for an unauthenticated sandbox\n\n"
        "### Rate limits\n"
        "| Tier | Limit |\n|---|---|\n"
        "| test | 100 req / day |\n"
        "| live | 1 000 req / day |\n\n"
        "Every response includes `X-RateLimit-Limit`, `X-RateLimit-Remaining`, `X-RateLimit-Reset`."
    ),
    docs_url    = f"{BASE_PATH}/docs",
    redoc_url   = f"{BASE_PATH}/redoc",
    openapi_url = f"{BASE_PATH}/openapi.json",
)

# ============================================================================
# Middleware
# ============================================================================

app.add_middleware(
    CORSMiddleware,
    allow_origins     = ["*"],
    allow_credentials = True,
    allow_methods     = ["*"],
    allow_headers     = ["*"],
)


@app.middleware("http")
async def observability_middleware(request: Request, call_next):
    """
    Attaches timing header, emits a structured request log,
    and records metrics for every HTTP request.
    """
    t0       = time.monotonic()
    response = await call_next(request)
    ms       = (time.monotonic() - t0) * 1000

    response.headers["X-ADM-Processing-Ms"] = f"{ms:.2f}"

    path     = request.url.path
    method   = request.method
    status   = response.status_code

    # Emit structured log (skip health probes to keep logs clean)
    if path != f"{BASE_PATH}/healthz":
        log_request(
            method     = method,
            path       = path,
            status     = status,
            latency_ms = ms,
            ip         = request.client.host if request.client else None,
        )

    # Record metrics (skip static/docs paths)
    if not any(path.endswith(s) for s in ("/docs", "/redoc", "/openapi.json", "/healthz")):
        endpoint = f"{method} {path}"
        metrics.record_request(endpoint, ms)

    return response


# ============================================================================
# Structured error handlers
# ============================================================================

@app.exception_handler(RequestValidationError)
async def request_validation_handler(req: Request, exc: RequestValidationError):
    """Pydantic v2 request body validation errors → structured 422."""
    logger.warning("validation.failed", extra={
        "path":   req.url.path,
        "errors": exc.errors(),
    })
    return JSONResponse(
        status_code = 422,
        content     = {
            "error":   "validation_error",
            "message": "Request body failed schema validation. Check 'detail' for field errors.",
            "code":    "ADM_VAL_001",
            "detail":  exc.errors(),
            "docs":    "/api/docs",
        },
    )


@app.exception_handler(ValidationError)
async def pydantic_validation_handler(_req: Request, exc: ValidationError):
    """Internal Pydantic validation errors (should not surface; caught as safety net)."""
    return JSONResponse(
        status_code = 422,
        content     = {
            "error":   "validation_error",
            "message": "Internal schema validation error.",
            "code":    "ADM_VAL_002",
            "detail":  exc.errors(),
            "docs":    "/api/docs",
        },
    )


@app.exception_handler(HTTPException)
async def http_exception_handler(req: Request, exc: HTTPException):
    """All HTTPExceptions → uniform JSON envelope."""
    detail = exc.detail
    if isinstance(detail, dict):
        content = detail
        # Log auth failures and rate limit violations
        code = detail.get("code", "")
        if code in ("ADM_AUTH_001", "ADM_AUTH_002"):
            log_auth_failure(
                reason = code,
                ip     = req.client.host if req.client else None,
                path   = req.url.path,
            )
        elif code in ("ADM_RATE_001", "ADM_RATE_002"):
            metrics.record_rate_limit_violation()
    else:
        content = {
            "error":   "http_error",
            "message": str(detail),
            "code":    f"ADM_HTTP_{exc.status_code}",
            "docs":    "/api/docs",
        }
    return JSONResponse(status_code=exc.status_code, content=content)


@app.exception_handler(Exception)
async def unhandled_exception_handler(_req: Request, exc: Exception):
    """Last-resort handler — never leak stack traces to clients."""
    logger.error("unhandled.exception", extra={"exc_type": type(exc).__name__, "exc": str(exc)})
    return JSONResponse(
        status_code = 500,
        content     = {
            "error":   "internal_error",
            "message": "An unexpected error occurred. The incident has been recorded.",
            "code":    "ADM_SRV_001",
            "docs":    "/api/docs",
        },
    )


# ============================================================================
# Routers
# ============================================================================

app.include_router(v1_router,        prefix=BASE_PATH)
app.include_router(playground_router, prefix=BASE_PATH)
app.include_router(admin_router,      prefix=BASE_PATH)
app.include_router(replay_router,     prefix=BASE_PATH)


# ============================================================================
# Ops endpoints — public, no auth, not rate-limited
# ============================================================================

_DASHBOARD_HTML = Path(__file__).parent.parent / "dashboard" / "index.html"
_DEMO_HTML      = Path(__file__).parent.parent / "demo"      / "index.html"


@app.get(
    f"{BASE_PATH}/demo",
    tags              = ["ops"],
    include_in_schema = False,
    response_class    = HTMLResponse,
)
async def demo() -> HTMLResponse:
    """
    Killer demo: one button → 15 scripted events → WebSocket stream → world collapse.
    Proves ADM-API determinism in under 60 seconds. No configuration required.
    """
    if not _DEMO_HTML.exists():
        raise HTTPException(status_code=404, detail="Demo not found")
    html = _DEMO_HTML.read_text()
    html = html.replace(
        "window.ADM_BASE || '/api'",
        f"window.ADM_BASE || '{BASE_PATH}'",
    )
    return HTMLResponse(content=html)


@app.get(
    f"{BASE_PATH}/dashboard",
    tags              = ["ops"],
    include_in_schema = False,
    response_class    = HTMLResponse,
)
async def dashboard() -> HTMLResponse:
    """
    Serve the integration demo dashboard.
    Features: event builder, render results, WebSocket stream, tension chart,
    consequence timeline, replay verification, and live metrics.
    """
    if not _DASHBOARD_HTML.exists():
        raise HTTPException(status_code=404, detail="Dashboard not found")
    html = _DASHBOARD_HTML.read_text()
    # Inject the base path so the dashboard can build correct API URLs
    html = html.replace(
        "window.BASE_PATH || '/api'",
        f"window.BASE_PATH || '{BASE_PATH}'",
    )
    return HTMLResponse(content=html)


@app.get(
    f"{BASE_PATH}/healthz",
    tags              = ["ops"],
    include_in_schema = False,
)
async def healthz() -> dict:
    return {"status": "ok", "service": "adm-api", "version": "1.0.0"}


@app.get(
    f"{BASE_PATH}/v1/info",
    tags        = ["ops"],
    summary     = "Service info",
    description = "Returns service metadata, endpoint listing, and core guarantees. No auth required.",
)
async def info() -> dict:
    return {
        "service":     "ADM-API",
        "version":     "1.0.0",
        "description": "Deterministic narrative compiler for multiplayer simulation systems",
        "endpoints": {
            "POST /v1/render":              "Convert event stream to structured NarrativeState",
            "WS   /v1/stream":              "Real-time incremental ingestion — live narrative updates",
            "POST /v1/simulate":            "Deterministic N-step world progression",
            "GET  /v1/usage":               "Usage stats for the authenticated API key",
            "GET  /v1/metrics":             "Aggregate platform metrics",
            "POST /v1/playground/render":   "Unauthenticated sandbox for testing",
            "POST /v1/replay/save":         "Save named event batch + compute reference hash",
            "POST /v1/replay/{name}/run":   "Replay batch and verify deterministic hash",
            "GET  /v1/replay/list":         "List all saved replays",
            "GET  /api/dashboard":          "Integration demo dashboard (HTML)",
        },
        "authentication": {
            "header":  "X-API-Key",
            "format":  "adm_test_... or adm_live_...",
            "docs":    "/api/docs",
        },
        "guarantees": {
            "stateless":      True,
            "deterministic":  True,
            "ai_required":    False,
            "latency_target": "<100ms for ≤20 events",
        },
    }


@app.get(
    f"{BASE_PATH}/v1/metrics",
    tags        = ["ops"],
    summary     = "Platform metrics",
    description = (
        "Returns aggregate request counts, latency percentiles, active WebSocket sessions, "
        "rate-limit violation counts, and key tier distribution. "
        "No authentication required — mount behind an internal network or VPN in production."
    ),
    response_description = "Point-in-time metrics snapshot",
)
async def get_metrics() -> JSONResponse:
    from adm_api.auth.api_keys import key_store
    all_keys = key_store.list_all()
    tier_counts: dict[str, int] = defaultdict(int)
    for k in all_keys:
        tier_counts[k.tier] += 1

    snapshot = metrics.snapshot(api_key_counts=dict(tier_counts))
    return JSONResponse(content=snapshot)
