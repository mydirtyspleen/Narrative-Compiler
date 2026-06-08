"""
admin_routes — API key management endpoints.

All routes require X-Admin-Key header matching ADM_ADMIN_KEY env var.

Endpoints:
  POST /v1/admin/keys              — create a new API key
  GET  /v1/admin/keys              — list all keys (usage stats included)
  POST /v1/admin/keys/{key}/deactivate — revoke a key
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from adm_api.auth.api_keys import key_store
from adm_api.auth.dependencies import require_admin_key
from adm_api.models.schemas import (
    AdminCreateKeyRequest,
    AdminCreateKeyResponse,
    AdminDeactivateResponse,
    AdminListKeysResponse,
    APIKeyInfo,
)

router = APIRouter(
    prefix       = "/v1/admin",
    tags         = ["admin"],
    dependencies = [Depends(require_admin_key)],
)


@router.post(
    "/keys",
    response_model = AdminCreateKeyResponse,
    status_code    = 201,
    summary        = "Create a new API key",
)
async def create_key(body: AdminCreateKeyRequest) -> AdminCreateKeyResponse:
    key = key_store.create(name=body.name, tier=body.tier)
    return AdminCreateKeyResponse(
        key        = key.key,
        name       = key.name,
        tier       = key.tier,
        rate_limit = key.rate_limit,
        created_at = key.created_at,
    )


@router.get(
    "/keys",
    response_model = AdminListKeysResponse,
    summary        = "List all API keys",
)
async def list_keys() -> AdminListKeysResponse:
    all_keys = key_store.list_all()
    return AdminListKeysResponse(
        keys  = [
            APIKeyInfo(
                key        = k.key,
                name       = k.name,
                tier       = k.tier,
                rate_limit = k.rate_limit,
                created_at = k.created_at,
                active     = k.active,
            )
            for k in all_keys
        ],
        total = len(all_keys),
    )


@router.post(
    "/keys/{api_key}/deactivate",
    response_model = AdminDeactivateResponse,
    summary        = "Revoke an API key",
)
async def deactivate_key(api_key: str) -> AdminDeactivateResponse:
    ok = key_store.deactivate(api_key)
    if not ok:
        from fastapi import HTTPException
        raise HTTPException(
            status_code = 404,
            detail      = {
                "error":   "key_not_found",
                "message": f"No API key matching '{api_key}' was found.",
                "code":    "ADM_ADMIN_001",
            },
        )
    return AdminDeactivateResponse(
        key     = api_key,
        active  = False,
        message = "API key revoked. Existing requests in-flight will still complete.",
    )
