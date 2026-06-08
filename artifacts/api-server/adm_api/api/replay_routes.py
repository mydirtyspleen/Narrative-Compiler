"""
replay_routes — Event replay system API routes.

POST /v1/replay/save        — Save a named event batch + compute reference hash
POST /v1/replay/{name}/run  — Replay the batch and verify hash
GET  /v1/replay/list        — List all saved replays
GET  /v1/replay/{name}      — Get replay metadata
DELETE /v1/replay/{name}    — Delete a replay

Purpose:
  Prove determinism. The hash_match field in run responses is the machine-
  checkable proof that ADM-API produces identical output for identical input.
  Use in CI pipelines to catch any accidental non-determinism regressions.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, ConfigDict, Field

from adm_api.auth.api_keys import APIKey
from adm_api.auth.dependencies import require_api_key
from adm_api.models.schemas import GameEvent, _StrictRequest
from adm_api.replay.replay_engine import replay_engine

router = APIRouter(tags=["replay"])


# ============================================================================
# Schemas
# ============================================================================

class ReplaySaveRequest(_StrictRequest):
    model_config = ConfigDict(
        extra                = "forbid",
        str_strip_whitespace = True,
        validate_default     = True,
        json_schema_extra    = {
            "example": {
                "name":       "combat-scenario-alpha",
                "session_id": "reference-session-001",
                "events": [
                    {
                        "id": "e1", "type": "combat", "intensity": 0.88,
                        "actors": ["Iron Pact"], "tags": ["war"], "payload": {},
                    },
                    {
                        "id": "e2", "type": "politics", "intensity": 0.65,
                        "actors": ["faction:Council"], "tags": ["crisis"], "payload": {},
                    },
                ],
            }
        },
    )

    name:       str             = Field(
        min_length  = 1,
        max_length  = 80,
        pattern     = r"^[a-zA-Z0-9_-]+$",
        description = "Unique replay name (alphanumeric + hyphens/underscores).",
    )
    session_id: str             = Field(description = "Session identifier for this replay.")
    events:     list[GameEvent] = Field(min_length=1, description="Events to save.")
    world_state: dict           = Field(default_factory=dict)


class ReplaySaveResponse(BaseModel):
    name:        str
    event_count: int
    output_hash: str = Field(
        description = "SHA-256 of the canonical JSON output. "
                      "Every subsequent run must produce this same hash.",
    )
    saved_at:    str


class ReplayRunResponse(BaseModel):
    name:            str
    session_id:      str
    event_count:     int
    output_hash:     str  = Field(description = "Hash from this run.")
    reference_hash:  str  = Field(description = "Hash saved at creation time.")
    hash_match:      bool = Field(
        description = "True if output_hash == reference_hash. "
                      "False indicates a determinism violation — should never occur.",
    )
    latency_ms:      float
    narrative_state: dict
    run_at:          str


class ReplayInfoResponse(BaseModel):
    name:        str
    session_id:  str
    event_count: int
    output_hash: str
    saved_at:    str
    run_count:   int
    last_run_at: str | None


class ReplayListResponse(BaseModel):
    replays: list[ReplayInfoResponse]
    total:   int


# ============================================================================
# Routes
# ============================================================================

@router.post(
    "/v1/replay/save",
    response_model  = ReplaySaveResponse,
    status_code     = 201,
    summary         = "Save a named event batch",
    description     = (
        "Runs the pipeline on the provided events, hashes the output, "
        "and persists both to disk.\n\n"
        "The `output_hash` is the SHA-256 of the canonical JSON output. "
        "Every call to `POST /v1/replay/{name}/run` must produce the same hash — "
        "this is the machine-verifiable proof of determinism.\n\n"
        "Use in CI/CD: save reference replays with known-good builds, "
        "then run them after every deployment to verify no regression."
    ),
)
async def save_replay(
    body: ReplaySaveRequest,
    key:  APIKey = Depends(require_api_key),
) -> ReplaySaveResponse:
    try:
        result = replay_engine.save_replay(
            name        = body.name,
            session_id  = body.session_id,
            events      = body.events,
            world_state = body.world_state,
        )
    except FileExistsError as e:
        raise HTTPException(
            status_code = 409,
            detail      = {
                "error":   "replay_exists",
                "message": str(e),
                "code":    "ADM_REPLAY_001",
            },
        )
    except ValueError as e:
        raise HTTPException(
            status_code = 422,
            detail      = {"error": "invalid_name", "message": str(e), "code": "ADM_REPLAY_002"},
        )

    return ReplaySaveResponse(**result.to_dict())


@router.post(
    "/v1/replay/{name}/run",
    response_model = ReplayRunResponse,
    summary        = "Replay a saved batch and verify output hash",
    description    = (
        "Replays the named event batch through the pipeline and verifies that "
        "the output hash is byte-identical to the reference hash saved at creation.\n\n"
        "`hash_match: true` confirms determinism holds.\n"
        "`hash_match: false` indicates a regression — the pipeline output has changed "
        "for the same input, which should never happen unless the engine was modified."
    ),
)
async def run_replay(
    name: str,
    key:  APIKey = Depends(require_api_key),
) -> ReplayRunResponse:
    try:
        result = replay_engine.run_replay(name)
    except FileNotFoundError:
        raise HTTPException(
            status_code = 404,
            detail      = {
                "error":   "replay_not_found",
                "message": f"No replay named '{name}' found.",
                "code":    "ADM_REPLAY_003",
            },
        )

    return ReplayRunResponse(**result.to_dict())


@router.get(
    "/v1/replay/list",
    response_model = ReplayListResponse,
    summary        = "List all saved replays",
)
async def list_replays(key: APIKey = Depends(require_api_key)) -> ReplayListResponse:
    replays = replay_engine.list_replays()
    return ReplayListResponse(
        replays = [ReplayInfoResponse(**r.to_dict()) for r in replays],
        total   = len(replays),
    )


@router.get(
    "/v1/replay/{name}",
    response_model = ReplayInfoResponse,
    summary        = "Get replay metadata",
)
async def get_replay(name: str, key: APIKey = Depends(require_api_key)) -> ReplayInfoResponse:
    try:
        info = replay_engine.get_replay(name)
    except FileNotFoundError:
        raise HTTPException(
            status_code = 404,
            detail      = {"error": "replay_not_found", "message": f"No replay named '{name}'.", "code": "ADM_REPLAY_003"},
        )
    return ReplayInfoResponse(**info.to_dict())


@router.delete(
    "/v1/replay/{name}",
    status_code    = 204,
    response_class = Response,
    summary        = "Delete a replay",
)
async def delete_replay(name: str, key: APIKey = Depends(require_api_key)):
    deleted = replay_engine.delete_replay(name)
    if not deleted:
        raise HTTPException(
            status_code = 404,
            detail      = {"error": "replay_not_found", "message": f"No replay named '{name}'.", "code": "ADM_REPLAY_003"},
        )
