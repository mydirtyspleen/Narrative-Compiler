"""
rate_limiter — per-key daily rate limit enforcement.

Thin wrapper around APIKeyStore.check_and_record().
Raises HTTP 429 when limit exceeded, attaches rate-limit headers on pass.
"""

from __future__ import annotations

from fastapi import HTTPException

from adm_api.auth.api_keys import key_store


def enforce_rate_limit(api_key: str, endpoint: str) -> dict[str, str]:
    """
    Check and record a request for the given API key.

    Returns rate-limit headers to attach to the response.
    Raises HTTP 429 if the daily limit is exceeded.
    """
    allowed, headers = key_store.check_and_record(api_key, endpoint)

    if not allowed:
        raise HTTPException(
            status_code = 429,
            detail      = {
                "error":   "rate_limit_exceeded",
                "message": "Daily request limit reached. Limit resets at UTC midnight.",
                "code":    "ADM_RATE_001",
                "headers": headers,
            },
        )

    return headers
