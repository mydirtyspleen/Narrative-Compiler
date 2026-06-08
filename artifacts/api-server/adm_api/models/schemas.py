"""
ADM-API v1 — Canonical schema definitions (single source of truth).

All request and response models live here.
Strict validation: extra fields are rejected, types are not silently coerced.

Sections:
  1. Base config
  2. Domain types (EventType, GameEvent)
  3. POST /v1/render  → NarrativeState
  4. WS   /v1/stream  → StreamUpdate
  5. POST /v1/simulate → SimulateResponse
  6. Auth & usage      → APIKeyInfo, UsageResponse
  7. Admin             → AdminCreateKeyRequest/Response
  8. Errors            → ErrorResponse
"""

from __future__ import annotations

from enum import Enum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


# ============================================================================
# 1. Base config
# ============================================================================

class _StrictRequest(BaseModel):
    """Applied to all inbound request models. Rejects unknown fields."""
    model_config = ConfigDict(
        extra                = "forbid",
        str_strip_whitespace = True,
        validate_default     = True,
    )


# ============================================================================
# 2. Domain types
# ============================================================================

class EventType(str, Enum):
    combat      = "combat"
    politics    = "politics"
    economy     = "economy"
    ecology     = "ecology"
    social      = "social"
    weather     = "weather"
    exploration = "exploration"


class GameEvent(_StrictRequest):
    """
    A single typed game or simulation event.

    The `id` field is the stability anchor for all deterministic operations —
    consequence selection, simulation cascade, and event ranking all derive
    from `id`. Use stable, unique identifiers (UUIDs recommended).
    """
    model_config = ConfigDict(
        extra                = "forbid",
        str_strip_whitespace = True,
        validate_default     = True,
        json_schema_extra    = {
            "example": {
                "id":        "evt-001",
                "type":      "combat",
                "intensity": 0.85,
                "actors":    ["Northern Legion", "Iron Pact"],
                "tags":      ["war", "conflict"],
                "payload":   {},
            }
        },
    )

    id: str = Field(
        description = (
            "Unique event identifier. Used as the stability anchor for deterministic "
            "consequence selection: `hash(id) % pool_size`. "
            "Use stable IDs (UUIDs) — the same ID always yields the same consequence."
        ),
    )
    type: EventType = Field(
        description = (
            "Event category. Determines base tension weight, cascade rules, "
            "and consequence pool. One of: combat, politics, economy, ecology, "
            "social, weather, exploration."
        ),
    )
    intensity: float = Field(
        ge          = 0.0,
        le          = 1.0,
        description = (
            "Event severity on a normalized [0.0, 1.0] scale. "
            "Drives tension scoring and consequence tier selection: "
            "≥0.7 → 'high' tier, 0.4–0.69 → 'medium', <0.4 → 'low'."
        ),
    )
    actors: list[str] = Field(
        default_factory = list,
        description     = (
            "Named entities involved (factions, characters, regions, etc.). "
            "The first actor is used to prefix consequence text. "
            "Use namespaces for clarity: 'faction:Council', 'region:Tundra'."
        ),
    )
    tags: list[str] = Field(
        default_factory = list,
        description     = (
            "Descriptive tags. Affect tension scoring: "
            "war/conflict/chaos → +0.25 modifier; peace/order → -0.25 modifier."
        ),
    )
    payload: dict[str, Any] = Field(
        default_factory = dict,
        description     = (
            "Arbitrary additional data. Passed through to output; not used by the "
            "core pipeline. Use for game-engine-specific metadata."
        ),
    )


# ============================================================================
# 3. POST /v1/render
# ============================================================================

class RenderRequest(_StrictRequest):
    """
    Batch render request. Accepts up to ~50 events; top 10 by intensity
    are used by the pipeline (event_ranker cap).
    """
    model_config = ConfigDict(
        extra                = "forbid",
        str_strip_whitespace = True,
        validate_default     = True,
        json_schema_extra    = {
            "example": {
                "session_id": "game-session-001",
                "events": [
                    {
                        "id": "evt-001", "type": "combat", "intensity": 0.88,
                        "actors": ["Iron Pact", "Northern Legion"],
                        "tags": ["war", "conflict"], "payload": {},
                    },
                    {
                        "id": "evt-002", "type": "politics", "intensity": 0.65,
                        "actors": ["faction:Council"], "tags": ["crisis"], "payload": {},
                    },
                ],
                "world_state": {},
            }
        },
    )

    session_id: str = Field(
        description = "Client-assigned session identifier. Echoed back in response headers.",
    )
    events: list[GameEvent] = Field(
        min_length  = 1,
        description = (
            "Batch of game events to render. Minimum 1, no hard maximum "
            "(event_ranker processes the top 10 by intensity). "
            "Order does not affect output — events are re-ranked by intensity."
        ),
    )
    world_state: dict[str, Any] = Field(
        default_factory = dict,
        description     = (
            "Reserved for future context enrichment. Not used by the core pipeline. "
            "Pass an empty object or omit entirely."
        ),
    )


class SuggestedNextEvent(BaseModel):
    """A deterministic recommendation for the next simulation step."""
    type: str = Field(
        description = "Suggested event type for the next step.",
    )
    intensity: float = Field(
        ge          = 0.0,
        le          = 1.0,
        description = "Suggested intensity, derived from avg_intensity ± cascade delta.",
    )
    description: str = Field(
        description = "Human-readable rationale for the suggestion.",
    )


class RenderMetadata(BaseModel):
    """Aggregate statistics about the processed event batch."""
    avg_intensity: float = Field(
        description = "Mean intensity across all ranked events.",
    )
    dominant_category: str = Field(
        description = "Most frequent EventType in the ranked event set.",
    )
    event_count: int = Field(
        description = "Number of events processed by the pipeline (capped at 10 by event_ranker).",
    )


class NarrativeState(BaseModel):
    """
    Full output of the ADM pipeline. Returned by POST /v1/render.

    All fields are deterministically derived from the input events.
    Same input always produces byte-identical output.
    """
    model_config = ConfigDict(
        json_schema_extra = {
            "example": {
                "scene_summary": "Overwhelming Iron Pact military engagement erupts across war zones",
                "cinematic_description": "The battlefield trembles beneath the iron boots of converging forces...",
                "character_focus": "Iron Pact",
                "tension_curve": [1.0, 0.725],
                "narrative_consequences": [
                    "Iron Pact: Military forces suffer catastrophic losses across contested zones",
                    "Conflict escalation triggers regional destabilization cascade",
                ],
                "suggested_next_events": [
                    {"type": "politics", "intensity": 0.95, "description": "Political response to military escalation"},
                ],
                "llm_prompt": "NARRATIVE CONTEXT\n================\n...",
                "metadata": {"avg_intensity": 0.765, "dominant_category": "combat", "event_count": 2},
            }
        }
    )

    scene_summary: str = Field(
        description = (
            "One-sentence scene description. Tone-mapped to avg_intensity: "
            "low → ambient, medium → tense, high → catastrophic."
        ),
    )
    cinematic_description: str = Field(
        description = "Multi-sentence atmospheric description. Same tone mapping as scene_summary.",
    )
    character_focus: str | None = Field(
        description = (
            "Dominant actor across all events. "
            "Determined by the most frequently appearing actor in the highest-intensity event category. "
            "Null if no events have named actors."
        ),
    )
    tension_curve: list[float] = Field(
        description = (
            "Per-event tension value, one float per ranked event. "
            "Formula: (base_weight + intensity) / 2 ± tag_modifier, clamped [0.0, 1.0]. "
            "Ordered by event intensity descending."
        ),
    )
    narrative_consequences: list[str] = Field(
        description = (
            "Deterministic structured outcomes. "
            "Selected via hash(event.id) % pool_size — same event ID always yields the same text. "
            "Includes cascade triggers for threshold-crossing event combinations."
        ),
    )
    suggested_next_events: list[SuggestedNextEvent] = Field(
        description = (
            "Typed recommendations for the next simulation step. "
            "Derived from the dominant event category's cascade rules."
        ),
    )
    llm_prompt: str = Field(
        description = (
            "Pre-formatted context block for LLM enrichment. "
            "Paste directly into any LLM system prompt to get narrative-aware responses. "
            "ADM-API itself never calls an LLM — this field is a convenience for integrations that do."
        ),
    )
    metadata: RenderMetadata = Field(
        description = "Aggregate statistics about the processed event batch.",
    )


# ============================================================================
# 4. WS /v1/stream
# ============================================================================

class StreamEventEnvelope(_StrictRequest):
    """Single-event WebSocket message. Sent by the client on each game tick."""
    session_id: str = Field(
        description = "Session identifier. Server accumulates all events for this session.",
    )
    event: GameEvent = Field(
        description = "The new event to append to the session's event history.",
    )
    world_state: dict[str, Any] = Field(
        default_factory = dict,
        description     = "Reserved. Pass empty object or omit.",
    )


class StreamUpdate(BaseModel):
    """Incremental narrative update pushed by the server after each ingested event."""
    session_id: str = Field(
        description = "Echo of the session_id from the inbound envelope.",
    )
    scene_summary: str = Field(
        description = "Updated scene summary after incorporating the new event.",
    )
    tension_curve: list[float] = Field(
        description = "Updated tension curve including the new event.",
    )
    narrative_consequences: list[str] = Field(
        description = "Updated consequence list.",
    )
    event_count: int = Field(
        description = "Total events accumulated in this session so far.",
    )


# ============================================================================
# 5. POST /v1/simulate
# ============================================================================

class SimulateRequest(_StrictRequest):
    """
    World progression simulation request.
    The simulator generates `steps` future timesteps from `current_events`.
    """
    model_config = ConfigDict(
        extra                = "forbid",
        str_strip_whitespace = True,
        validate_default     = True,
        json_schema_extra    = {
            "example": {
                "session_id":     "sim-001",
                "steps":          3,
                "current_events": [
                    {
                        "id": "seed-001", "type": "combat", "intensity": 0.8,
                        "actors": ["Iron Pact"], "tags": ["war"], "payload": {},
                    }
                ],
                "world_state": {},
            }
        },
    )

    session_id: str = Field(
        description = (
            "Session identifier. Also seeds the deterministic simulation: "
            "different session_ids produce different (but still deterministic) simulated timelines."
        ),
    )
    world_state: dict[str, Any] = Field(
        default_factory = dict,
        description     = "Reserved. Pass empty object or omit.",
    )
    current_events: list[GameEvent] = Field(
        default_factory = list,
        description     = "Seed events for the simulation. Can be empty (produces minimal cascade).",
    )
    steps: int = Field(
        default     = 3,
        ge          = 1,
        le          = 10,
        description = "Number of simulation timesteps to generate. Range [1, 10].",
    )


class SimulatedEvent(BaseModel):
    """A single event in the simulated future timeline."""
    id:        str   = Field(description = "Deterministically generated event ID.")
    type:      EventType
    intensity: float = Field(ge=0.0, le=1.0)
    actors:    list[str]
    tags:      list[str]
    payload:   dict[str, Any]
    step:      int   = Field(description = "Simulation timestep this event belongs to (1-indexed).")
    rationale: str   = Field(description = "Human-readable explanation of why this event was generated.")


class SimulateResponse(BaseModel):
    """Deterministic N-step simulation output."""
    session_id: str = Field(
        description = "Echo of the session_id from the request.",
    )
    simulated_events: list[SimulatedEvent] = Field(
        description = "All generated events across all steps, ordered by step then type.",
    )
    projected_tension: list[float] = Field(
        description = "Tension curve computed over the full simulated event set.",
    )
    world_trajectory: str = Field(
        description = (
            "High-level trajectory label: 'Escalating', 'Stable', or 'De-escalating'. "
            "Derived from projected avg intensity vs seed avg intensity."
        ),
    )
    dominant_force: str = Field(
        description = "Most frequent event type across all simulated steps.",
    )


# ============================================================================
# 6. Auth & usage
# ============================================================================

class APIKeyInfo(BaseModel):
    """Public-safe view of an API key (secret value partially masked in responses)."""
    key:        str  = Field(description = "The API key value.")
    name:       str  = Field(description = "Human-readable label.")
    tier:       str  = Field(description = "Key tier: test, live, or admin.")
    rate_limit: int  = Field(description = "Daily request limit for this key.")
    created_at: str  = Field(description = "ISO-8601 UTC creation timestamp.")
    active:     bool = Field(description = "False if the key has been revoked.")


class EndpointUsage(BaseModel):
    endpoint: str
    requests: int


class UsageResponse(BaseModel):
    """Returned by GET /v1/usage."""
    key:                  str               = Field(description = "The authenticated key.")
    name:                 str               = Field(description = "Key label.")
    tier:                 str               = Field(description = "Key tier.")
    rate_limit:           int               = Field(description = "Daily request limit.")
    total_requests:       int               = Field(description = "All-time request count for this key.")
    requests_today:       int               = Field(description = "Requests made today (UTC day).")
    remaining_today:      int               = Field(description = "Remaining requests for today.")
    usage_date:           str               = Field(description = "Current usage accounting date (UTC, YYYY-MM-DD).")
    last_used_at:         str | None        = Field(description = "ISO-8601 timestamp of last request.")
    requests_by_endpoint: dict[str, int]    = Field(description = "Per-endpoint request breakdown.")


# ============================================================================
# 7. Admin
# ============================================================================

class AdminCreateKeyRequest(_StrictRequest):
    name: str = Field(
        min_length  = 1,
        max_length  = 120,
        description = "Human-readable label for the new key.",
        examples    = ["Unity Studio — Production", "Roblox Integration"],
    )
    tier: str = Field(
        default     = "live",
        pattern     = "^(test|live)$",
        description = "Key tier. 'test' → 100 req/day, 'live' → 1 000 req/day.",
    )


class AdminCreateKeyResponse(BaseModel):
    key:        str = Field(description = "The generated API key. Store securely — shown once.")
    name:       str
    tier:       str
    rate_limit: int
    created_at: str


class AdminListKeysResponse(BaseModel):
    keys:  list[APIKeyInfo]
    total: int


class AdminDeactivateResponse(BaseModel):
    key:     str
    active:  bool
    message: str


# ============================================================================
# 8. Errors  (structured error envelope for all 4xx / 5xx responses)
# ============================================================================

class ErrorResponse(BaseModel):
    """
    Uniform error envelope. All 4xx and 5xx responses use this shape.

    | code           | status | meaning                          |
    |----------------|--------|----------------------------------|
    | ADM_AUTH_001   | 401    | Missing API key                  |
    | ADM_AUTH_002   | 401    | Invalid or revoked API key       |
    | ADM_AUTH_003   | 403    | Invalid admin key                |
    | ADM_VAL_001    | 422    | Request body validation failed   |
    | ADM_RATE_001   | 429    | API key daily limit exceeded     |
    | ADM_RATE_002   | 429    | Playground IP rate limit         |
    | ADM_SRV_001    | 500    | Unexpected server error          |
    | ADM_ADMIN_001  | 404    | Key not found (admin routes)     |
    """
    model_config = ConfigDict(
        json_schema_extra = {
            "example": {
                "error":   "invalid_api_key",
                "message": "The provided API key is invalid or has been revoked.",
                "code":    "ADM_AUTH_002",
                "docs":    "/api/docs",
            }
        }
    )

    error:   str = Field(description = "Machine-readable error slug.")
    message: str = Field(description = "Human-readable error description.")
    code:    str = Field(description = "ADM error code for programmatic handling.")
    docs:    str = Field(default="/api/docs", description = "Link to API documentation.")
