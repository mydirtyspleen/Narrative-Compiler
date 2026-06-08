"""
ADM-API v1 — All route handlers.

Every /v1/ endpoint (except /v1/info, /v1/metrics, /v1/playground/render)
requires a valid API key.  Rate limiting is enforced per endpoint per key
(daily quota).

Endpoints:
  POST /v1/render    — batch event → full NarrativeState
  WS   /v1/stream    — incremental events → streamed NarrativeState updates
  POST /v1/simulate  — deterministic world progression
  GET  /v1/usage     — usage stats for the authenticated key
"""

from __future__ import annotations

import asyncio
import time
from collections import defaultdict

from fastapi import APIRouter, Depends, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from adm_api.auth.api_keys import APIKey, key_store
from adm_api.auth.dependencies import authenticate_ws_key, require_api_key
from adm_api.engine.pipeline import run_pipeline
from adm_api.engine.simulator import (
    compute_dominant_force,
    compute_trajectory,
    simulate_progression,
)
from adm_api.engine.tension_engine import compute_tension_curve
from adm_api.middleware.rate_limiter import enforce_rate_limit
from adm_api.models.schemas import (
    GameEvent,
    NarrativeState,
    RenderRequest,
    SimulateRequest,
    SimulateResponse,
    StreamEventEnvelope,
    StreamUpdate,
    UsageResponse,
)
from adm_api.observability.logger import (
    log_pipeline,
    log_rate_limit_violation,
    log_ws_connect,
    log_ws_disconnect,
    logger,
)
from adm_api.observability.metrics import metrics
from adm_api.session.store import get_session_store

router = APIRouter()

# Session store — swap get_session_store() implementation for horizontal scaling.
# Default: InMemorySessionStore (single-node, zero dependencies).
# Redis:   Set REDIS_URL env var → RedisSessionStore (requires redis[asyncio]).
# See adm_api/session/store.py for migration docs.
_session_store = get_session_store()


# ============================================================================
# POST /v1/render
# ============================================================================

_RENDER_EXAMPLE = {
    "session_id": "game-session-001",
    "events": [
        {
            "id":        "evt-001",
            "type":      "combat",
            "intensity": 0.88,
            "actors":    ["Iron Pact", "Northern Legion"],
            "tags":      ["war", "conflict"],
            "payload":   {},
        },
        {
            "id":        "evt-002",
            "type":      "politics",
            "intensity": 0.65,
            "actors":    ["faction:Council"],
            "tags":      ["crisis"],
            "payload":   {},
        },
    ],
    "world_state": {},
}

_RENDER_RESPONSE_EXAMPLE = {
    "scene_summary": "Overwhelming Iron Pact military engagement erupts across war zones, delivering catastrophic losses on all sides",
    "cinematic_description": "The battlefield trembles beneath the iron boots of converging forces. Smoke chokes the horizon as the Iron Pact's war machine grinds forward...",
    "character_focus": "Iron Pact",
    "tension_curve": [1.0, 0.725],
    "narrative_consequences": [
        "Iron Pact: Military forces suffer catastrophic losses across contested zones",
        "faction:Council: Governing coalition fractures under accumulated pressure",
        "Conflict escalation triggers regional destabilization cascade",
    ],
    "suggested_next_events": [
        {"type": "politics", "intensity": 0.95, "description": "Political response to military escalation"},
        {"type": "economy",  "intensity": 0.75, "description": "Resource drain from sustained combat"},
    ],
    "llm_prompt": "NARRATIVE CONTEXT\n================\nScene: Overwhelming Iron Pact military engagement...",
    "metadata": {
        "avg_intensity":     0.765,
        "dominant_category": "combat",
        "event_count":       2,
    },
}


@router.post(
    "/v1/render",
    response_model = NarrativeState,
    summary        = "Render narrative state from event batch",
    description    = (
        "Accepts a batch of game/simulation events and returns a full deterministic "
        "`NarrativeState`. **Same input always produces byte-identical output.**\n\n"
        "**Pipeline stages (in order):**\n"
        "1. `event_ranker` — sort by intensity DESC, top 10\n"
        "2. `tension_engine` — per-event tension [0.0–1.0]\n"
        "3. `character_focus_engine` — dominant actor\n"
        "4. `narrative_engine` — scene_summary + cinematic_description\n"
        "5. `consequence_engine` — hash-stable outcome list\n"
        "6. `prompt_generator` — structured LLM context block\n\n"
        "Requires `X-API-Key` header. See `POST /v1/playground/render` for unauthenticated testing."
    ),
    tags           = ["narrative"],
    openapi_extra  = {
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "combat_politics": {
                            "summary": "Combat + politics scenario",
                            "value":   _RENDER_EXAMPLE,
                        },
                        "single_event": {
                            "summary": "Minimal single-event request",
                            "value": {
                                "session_id": "minimal",
                                "events": [{
                                    "id": "e1", "type": "ecology", "intensity": 0.4,
                                    "actors": [], "tags": [], "payload": {},
                                }],
                            },
                        },
                    }
                }
            }
        }
    },
    responses      = {
        200: {
            "description": "Full NarrativeState — deterministic",
            "content": {"application/json": {"example": _RENDER_RESPONSE_EXAMPLE}},
        },
        401: {"description": "Missing or invalid API key (ADM_AUTH_001 / ADM_AUTH_002)"},
        422: {"description": "Request body validation failed (ADM_VAL_001)"},
        429: {"description": "Daily rate limit exceeded (ADM_RATE_001)"},
    },
)
async def render(
    request: Request,
    body: RenderRequest,
    key: APIKey = Depends(require_api_key),
) -> JSONResponse:
    rl_headers = enforce_rate_limit(key.key, "POST /v1/render")

    t0    = time.monotonic()
    state = run_pipeline(body.events, body.world_state)
    ms    = (time.monotonic() - t0) * 1000

    log_pipeline(
        session_id    = body.session_id,
        event_count   = len(body.events),
        latency_ms    = ms,
        dominant      = state.metadata.dominant_category,
        avg_intensity = state.metadata.avg_intensity,
    )

    return JSONResponse(
        content = state.model_dump(),
        headers = {
            "X-ADM-Processing-Ms": f"{ms:.2f}",
            "X-ADM-Session-Id":    body.session_id,
            **rl_headers,
        },
    )


# ============================================================================
# WS /v1/stream  — session state backed by SessionStore
# ============================================================================
# Session state is managed via _session_store (see top of module).
# Default: InMemorySessionStore — zero deps, works for single-node.
# Scale path: set REDIS_URL env var to switch to RedisSessionStore.
# ============================================================================


@router.websocket("/v1/stream")
async def stream(
    websocket: WebSocket,
    api_key: str | None = None,
) -> None:
    """
    WebSocket: incremental event ingestion with live narrative updates.

    Authentication:
      Pass API key as query param: wss://host/api/v1/stream?api_key=adm_...

    Client sends JSON matching StreamEventEnvelope after auth:
      { "session_id": "...", "event": { GameEvent }, "world_state": {} }

    Control frames:
      { "action": "reset", "session_id": "..." }  — clear session history
      { "action": "close" }                        — graceful disconnect

    Server streams StreamUpdate JSON after each ingested event.

    Scaling:
      Session state is delegated to _session_store. Set REDIS_URL to use
      RedisSessionStore for multi-worker/multi-node deployments.
    """
    await websocket.accept()

    # --- Authenticate --------------------------------------------------------
    try:
        key_obj = authenticate_ws_key(api_key)
    except ValueError as e:
        await websocket.send_json({
            "error":   str(e),
            "message": "Provide your API key as ?api_key=adm_... query parameter.",
            "code":    "ADM_AUTH_001",
        })
        await websocket.close(code=4001)
        return

    metrics.record_ws_connect()
    log_ws_connect(
        session_id = None,
        key_id     = key_obj.key[:20] + "...",
        key_tier   = key_obj.tier,
    )

    session_id: str | None = None
    event_count: int = 0

    try:
        while True:
            raw = await websocket.receive_json()

            action = raw.get("action")

            if action == "close":
                sid = raw.get("session_id", session_id or "unknown")
                await websocket.send_json({"action": "closed", "session_id": sid})
                break

            if action == "reset":
                sid = raw.get("session_id", "")
                await _session_store.clear(sid)
                event_count = 0
                await websocket.send_json({"action": "reset_ack", "session_id": sid})
                logger.info("ws.session_reset", extra={"session_id": sid})
                continue

            # Validate envelope
            try:
                envelope = StreamEventEnvelope.model_validate(raw)
            except ValidationError as exc:
                await websocket.send_json({
                    "error":  "validation_error",
                    "detail": exc.errors(),
                    "code":   "ADM_VAL_001",
                })
                continue

            session_id = envelope.session_id

            # Rate limit (non-blocking check — WS gets same quota as HTTP)
            allowed, rl_headers = key_store.check_and_record(key_obj.key, "WS /v1/stream")
            if not allowed:
                log_rate_limit_violation(
                    key_id   = key_obj.key[:20] + "...",
                    key_tier = key_obj.tier,
                    endpoint = "WS /v1/stream",
                )
                metrics.record_rate_limit_violation()
                await websocket.send_json({
                    "error":   "rate_limit_exceeded",
                    "message": "Daily request limit reached.",
                    "code":    "ADM_RATE_001",
                    "headers": rl_headers,
                })
                continue

            # Append to store (atomic: append + get in one lock/transaction)
            all_events  = await _session_store.append(session_id, envelope.event)
            event_count = len(all_events)

            t0    = time.monotonic()
            state = run_pipeline(all_events, envelope.world_state)
            ms    = (time.monotonic() - t0) * 1000

            update = StreamUpdate(
                session_id             = session_id,
                scene_summary          = state.scene_summary,
                tension_curve          = state.tension_curve,
                narrative_consequences = state.narrative_consequences,
                event_count            = event_count,
            )
            await websocket.send_json(update.model_dump())

            logger.debug("ws.event_processed", extra={
                "session_id":  session_id,
                "event_count": event_count,
                "latency_ms":  round(ms, 3),
            })

    except WebSocketDisconnect:
        pass
    except Exception as exc:
        logger.error("ws.error", extra={"exc_type": type(exc).__name__, "exc": str(exc)})
        try:
            await websocket.send_json({
                "error":  "internal_error",
                "detail": str(exc),
                "code":   "ADM_SRV_001",
            })
        except Exception:
            pass
        await websocket.close(code=1011)
    finally:
        metrics.record_ws_disconnect()
        log_ws_disconnect(
            session_id  = session_id,
            key_id      = key_obj.key[:20] + "..." if key_obj else None,
            event_count = event_count,
        )
        # Clean up session on disconnect to avoid unbounded memory growth
        if session_id:
            await _session_store.delete(session_id)


# ============================================================================
# POST /v1/simulate
# ============================================================================

_SIMULATE_EXAMPLE = {
    "session_id":     "sim-session-001",
    "steps":          3,
    "current_events": [
        {
            "id":        "seed-001",
            "type":      "combat",
            "intensity": 0.8,
            "actors":    ["Iron Pact"],
            "tags":      ["war"],
            "payload":   {},
        }
    ],
    "world_state": {},
}


@router.post(
    "/v1/simulate",
    response_model = SimulateResponse,
    summary        = "Deterministic world progression simulation",
    description    = (
        "Generates cascading future events from current world state using "
        "typed progression rules.\n\n"
        "**No randomness** — same input always produces the same simulated timeline.\n\n"
        "**Cascade rules** (examples):\n"
        "- `combat` (high) → escalates to `politics`\n"
        "- `ecology` (high) → degrades `economy`\n"
        "- `social` (high) → escalates to `politics`\n\n"
        "**Steps:** 1–10. Each step can produce multiple child events.\n\n"
        "Requires `X-API-Key` header."
    ),
    tags           = ["narrative"],
    openapi_extra  = {
        "requestBody": {
            "content": {
                "application/json": {
                    "examples": {
                        "combat_3_steps": {
                            "summary": "3-step combat cascade",
                            "value":   _SIMULATE_EXAMPLE,
                        },
                        "ecology_crisis": {
                            "summary": "Ecology → economy cascade",
                            "value": {
                                "session_id": "eco-sim",
                                "steps": 2,
                                "current_events": [{
                                    "id": "eco-01", "type": "ecology", "intensity": 0.75,
                                    "actors": ["region:Amazon"], "tags": ["drought"], "payload": {},
                                }],
                            },
                        },
                    }
                }
            }
        }
    },
    responses      = {
        200: {"description": "Simulated event timeline with projected tension and trajectory"},
        401: {"description": "Missing or invalid API key"},
        429: {"description": "Daily rate limit exceeded"},
    },
)
async def simulate(
    body: SimulateRequest,
    key: APIKey = Depends(require_api_key),
) -> SimulateResponse:
    enforce_rate_limit(key.key, "POST /v1/simulate")

    simulated = simulate_progression(
        current_events = body.current_events,
        steps          = body.steps,
        session_id     = body.session_id,
    )

    seed_avg = (
        sum(e.intensity for e in body.current_events) / len(body.current_events)
        if body.current_events else 0.5
    )

    projected_tension: list[float] = []
    if simulated:
        as_events = [
            GameEvent(
                id        = s.id,
                type      = s.type,
                intensity = s.intensity,
                actors    = s.actors,
                tags      = s.tags,
                payload   = s.payload,
            )
            for s in simulated
        ]
        projected_tension = compute_tension_curve(as_events)

    return SimulateResponse(
        session_id        = body.session_id,
        simulated_events  = simulated,
        projected_tension = projected_tension,
        world_trajectory  = compute_trajectory(simulated, seed_avg),
        dominant_force    = compute_dominant_force(simulated),
    )


# ============================================================================
# GET /v1/usage
# ============================================================================

@router.get(
    "/v1/usage",
    response_model = UsageResponse,
    summary        = "Get usage stats for the authenticated API key",
    description    = (
        "Returns daily quota, usage counters, and per-endpoint request breakdown "
        "for the authenticated API key.\n\n"
        "**Does NOT consume rate-limit quota** — safe to poll frequently.\n\n"
        "The `requests_by_endpoint` field breaks down usage across:\n"
        "`POST /v1/render`, `POST /v1/simulate`, `WS /v1/stream`"
    ),
    tags           = ["account"],
    responses      = {
        200: {
            "content": {
                "application/json": {
                    "example": {
                        "key":                   "adm_test_e2f4a6b8...",
                        "name":                  "Default Test Key",
                        "tier":                  "test",
                        "rate_limit":            100,
                        "total_requests":        42,
                        "requests_today":        5,
                        "remaining_today":       95,
                        "usage_date":            "2026-01-15",
                        "last_used_at":          "2026-01-15T14:22:01.123456+00:00",
                        "requests_by_endpoint": {
                            "POST /v1/render":   38,
                            "POST /v1/simulate":  3,
                            "WS /v1/stream":      1,
                        },
                    }
                }
            }
        }
    },
)
async def usage(key: APIKey = Depends(require_api_key)) -> UsageResponse:
    k = key_store.get_usage(key.key)
    return UsageResponse(
        key                  = k.key,
        name                 = k.name,
        tier                 = k.tier,
        rate_limit           = k.rate_limit,
        total_requests       = k.total_requests,
        requests_today       = k.requests_today,
        remaining_today      = max(0, k.rate_limit - k.requests_today),
        usage_date           = k.usage_date,
        last_used_at         = k.last_used_at,
        requests_by_endpoint = k.requests_by_endpoint,
    )
