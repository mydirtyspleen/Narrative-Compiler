"""
playground_routes — unauthenticated sandbox endpoint for developer testing.

POST /v1/playground/render

Purpose:
  Let developers evaluate ADM-API outputs without provisioning an API key.
  Accepts a simplified event payload and returns a full NarrativeState.

Constraints (enforced to prevent abuse):
  - Max 5 events per request.
  - Rate-limited to 30 requests / minute per IP (rolling window).
  - No API key required.
  - Identical output contract to POST /v1/render.

Note on determinism:
  Playground responses are fully deterministic — same input → same output,
  same as the authenticated endpoint.  The only difference is the auth model.
"""

from __future__ import annotations

import time
from collections import defaultdict, deque
from threading import Lock
from typing import Annotated, Any

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from adm_api.engine.pipeline import run_pipeline
from adm_api.models.schemas import EventType, GameEvent, NarrativeState

router = APIRouter(tags=["playground"])


# ============================================================================
# IP rate-limiter (rolling 60 s window)
# ============================================================================

_PLAYGROUND_LIMIT    = 30   # requests per window
_PLAYGROUND_WINDOW   = 60   # seconds

_ip_windows: dict[str, deque[float]] = defaultdict(deque)
_ip_lock = Lock()


def _check_playground_rate(ip: str) -> None:
    now = time.monotonic()
    with _ip_lock:
        window = _ip_windows[ip]
        while window and now - window[0] > _PLAYGROUND_WINDOW:
            window.popleft()
        if len(window) >= _PLAYGROUND_LIMIT:
            raise HTTPException(
                status_code = 429,
                detail      = {
                    "error":   "playground_rate_limit",
                    "message": f"Playground is limited to {_PLAYGROUND_LIMIT} requests per {_PLAYGROUND_WINDOW}s per IP. "
                               "Create an API key at POST /v1/admin/keys for higher limits.",
                    "code":    "ADM_RATE_002",
                    "docs":    "/api/docs",
                },
            )
        window.append(now)


# ============================================================================
# Simplified input schema
# ============================================================================

class PlaygroundEvent(BaseModel):
    """
    Simplified event for the playground endpoint.
    Actors, tags, and payload are all optional.
    """
    model_config = ConfigDict(
        extra              = "forbid",
        str_strip_whitespace = True,
        json_schema_extra  = {
            "example": {
                "id":        "evt-001",
                "type":      "combat",
                "intensity": 0.85,
                "actors":    ["Northern Legion"],
                "tags":      ["war", "conflict"],
            }
        },
    )

    id:        str       = Field(description="Unique event identifier")
    type:      EventType = Field(description="Event category")
    intensity: float     = Field(ge=0.0, le=1.0, description="Event severity, 0.0–1.0")
    actors:    list[str] = Field(default_factory=list, description="Named entities involved")
    tags:      list[str] = Field(default_factory=list, description="Descriptive tags")
    payload:   dict[str, Any] = Field(default_factory=dict)


class PlaygroundRenderRequest(BaseModel):
    """
    Simplified render request for developer playground.
    No API key required. Limited to 5 events per request.
    """
    model_config = ConfigDict(
        extra              = "forbid",
        str_strip_whitespace = True,
        json_schema_extra  = {
            "example": {
                "session_id": "my-test-session",
                "events": [
                    {
                        "id": "evt-001", "type": "combat", "intensity": 0.85,
                        "actors": ["Northern Legion", "Iron Pact"],
                        "tags": ["war", "conflict"],
                    },
                    {
                        "id": "evt-002", "type": "politics", "intensity": 0.6,
                        "actors": ["faction:Council"],
                        "tags": ["crisis"],
                    },
                ],
            }
        },
    )

    session_id: str = Field(default="playground", description="Session identifier (optional)")
    events: Annotated[
        list[PlaygroundEvent],
        Field(min_length=1, max_length=5, description="1–5 game events to render"),
    ]
    world_state: dict[str, Any] = Field(default_factory=dict)


# ============================================================================
# Route
# ============================================================================

@router.post(
    "/v1/playground/render",
    response_model = NarrativeState,
    summary        = "Playground render — no API key required",
    description    = (
        "**Developer sandbox.** Accepts a simplified event payload and returns "
        "a full deterministic `NarrativeState` — no API key required.\n\n"
        "- Max **5 events** per request.\n"
        "- Rate-limited to **30 requests / 60 s** per IP.\n"
        "- Output is byte-identical to `POST /v1/render` for the same input.\n\n"
        "Ready to integrate? Create an API key via `POST /v1/admin/keys` and "
        "switch to the authenticated endpoint for higher limits and usage tracking."
    ),
    responses      = {
        200: {
            "description": "Full NarrativeState — deterministic, same input always returns same output.",
            "content": {
                "application/json": {
                    "example": {
                        "scene_summary": "Overwhelming Alpha military engagement erupts across war zones",
                        "cinematic_description": "The battlefield trembles...",
                        "character_focus": "Northern Legion",
                        "tension_curve": [1.0, 0.725],
                        "narrative_consequences": [
                            "Northern Legion: Military forces suffer catastrophic losses across contested zones"
                        ],
                        "suggested_next_events": [
                            {"type": "politics", "intensity": 0.95, "description": "Political response to military escalation"}
                        ],
                        "llm_prompt": "...",
                        "metadata": {"avg_intensity": 0.725, "dominant_category": "combat", "event_count": 2},
                    }
                }
            },
        },
        429: {"description": "Playground rate limit exceeded. Use an API key for higher throughput."},
    },
)
async def playground_render(
    request: Request,
    body: PlaygroundRenderRequest,
) -> JSONResponse:
    ip = request.client.host if request.client else "unknown"
    _check_playground_rate(ip)

    t0 = time.monotonic()

    # Convert playground events → GameEvent (schemas are compatible)
    game_events = [
        GameEvent(
            id        = e.id,
            type      = e.type,
            intensity = e.intensity,
            actors    = e.actors,
            tags      = e.tags,
            payload   = e.payload,
        )
        for e in body.events
    ]

    state = run_pipeline(game_events, body.world_state)
    ms    = (time.monotonic() - t0) * 1000

    return JSONResponse(
        content = state.model_dump(),
        headers = {
            "X-ADM-Processing-Ms":    f"{ms:.2f}",
            "X-ADM-Session-Id":       body.session_id,
            "X-ADM-Playground":       "true",
            "X-ADM-Upgrade-Hint":     "POST /v1/admin/keys to get a full API key",
        },
    )
