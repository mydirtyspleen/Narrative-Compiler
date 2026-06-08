"""
dependencies — FastAPI dependency injection for authentication.

Usage in route handlers:
  key: APIKey = Depends(require_api_key)

Extracts key from:
  1. X-API-Key header  (preferred)
  2. Authorization: Bearer <key>  (fallback)

WebSocket routes use authenticate_ws_key() directly.
"""

from __future__ import annotations

import os

from fastapi import Header, HTTPException
from fastapi.security.utils import get_authorization_scheme_param

from adm_api.auth.api_keys import APIKey, key_store

_ADMIN_KEY = os.environ.get("ADM_ADMIN_KEY", "adm_admin_dev_insecure_default")


def _extract_key(
    x_api_key: str | None,
    authorization: str | None,
) -> str | None:
    if x_api_key:
        return x_api_key.strip()
    if authorization:
        scheme, param = get_authorization_scheme_param(authorization)
        if scheme.lower() == "bearer" and param:
            return param.strip()
    return None


async def require_api_key(
    x_api_key:     str | None = Header(default=None, alias="X-API-Key"),
    authorization: str | None = Header(default=None),
) -> APIKey:
    """
    FastAPI dependency: validates API key, returns APIKey object.
    Does NOT check rate limit — that is done inside each route so
    endpoint names can be recorded accurately.
    """
    raw = _extract_key(x_api_key, authorization)

    if not raw:
        raise HTTPException(
            status_code = 401,
            detail      = {
                "error":   "missing_api_key",
                "message": "Provide your API key via 'X-API-Key' header or 'Authorization: Bearer <key>'.",
                "code":    "ADM_AUTH_001",
                "docs":    "/api/docs",
            },
        )

    key = key_store.get(raw)

    if key is None or not key.active:
        raise HTTPException(
            status_code = 401,
            detail      = {
                "error":   "invalid_api_key",
                "message": "The provided API key is invalid or has been revoked.",
                "code":    "ADM_AUTH_002",
                "docs":    "/api/docs",
            },
        )

    return key


async def require_admin_key(
    x_admin_key: str | None = Header(default=None, alias="X-Admin-Key"),
) -> None:
    """Dependency for admin-only routes. Validates against ADM_ADMIN_KEY env var."""
    if not x_admin_key or x_admin_key.strip() != _ADMIN_KEY:
        raise HTTPException(
            status_code = 403,
            detail      = {
                "error":   "forbidden",
                "message": "Admin access required. Provide a valid X-Admin-Key header.",
                "code":    "ADM_AUTH_003",
            },
        )


def authenticate_ws_key(raw_key: str | None) -> APIKey:
    """
    Authenticate a WebSocket connection.
    Called with the key from query param or first-message field.
    Returns APIKey or raises ValueError (converted to WS close by caller).
    """
    if not raw_key:
        raise ValueError("missing_api_key")

    key = key_store.get(raw_key.strip())
    if key is None or not key.active:
        raise ValueError("invalid_api_key")

    return key
