"""
api_keys — in-memory API key store with JSON persistence and usage tracking.

Key format:
  adm_test_<40-hex>   — test tier (100 req/day)
  adm_live_<40-hex>   — live tier (1000 req/day, extendable)

Persistence:
  data/api_keys.json  — written on every mutation; loaded on startup

Usage tracking:
  Per-key, per-day counters (UTC calendar day).
  Endpoint breakdown tracked separately.

On first startup with no data file, a deterministic test key is seeded
and printed to stdout so developers can start immediately.
"""

from __future__ import annotations

import hashlib
import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from threading import Lock
from typing import Any

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_DATA_DIR  = Path(__file__).parent.parent.parent / "data"
_KEYS_FILE = _DATA_DIR / "api_keys.json"

_RATE_LIMITS: dict[str, int] = {
    "test":  100,
    "live":  1000,
    "admin": 10_000,
}

_SEEDED_TEST_KEY   = "adm_test_e2f4a6b8c0d1e3f5a7b9c1d3e5f7000100000001"
_SEEDED_TEST_NAME  = "Default Test Key"


# ---------------------------------------------------------------------------
# In-memory data structures
# ---------------------------------------------------------------------------

class APIKey:
    __slots__ = (
        "key", "name", "tier", "rate_limit",
        "created_at", "active",
        # usage (mutated in-place)
        "total_requests", "requests_today",
        "requests_by_endpoint", "last_used_at", "usage_date",
    )

    def __init__(
        self,
        key: str,
        name: str,
        tier: str,
        rate_limit: int,
        created_at: str,
        active: bool = True,
        total_requests: int = 0,
        requests_today: int = 0,
        requests_by_endpoint: dict[str, int] | None = None,
        last_used_at: str | None = None,
        usage_date: str = "",
    ) -> None:
        self.key                  = key
        self.name                 = name
        self.tier                 = tier
        self.rate_limit           = rate_limit
        self.created_at           = created_at
        self.active               = active
        self.total_requests       = total_requests
        self.requests_today       = requests_today
        self.requests_by_endpoint = requests_by_endpoint or {}
        self.last_used_at         = last_used_at
        self.usage_date           = usage_date or _today_utc()

    def to_dict(self) -> dict[str, Any]:
        return {
            "key":                   self.key,
            "name":                  self.name,
            "tier":                  self.tier,
            "rate_limit":            self.rate_limit,
            "created_at":            self.created_at,
            "active":                self.active,
            "total_requests":        self.total_requests,
            "requests_today":        self.requests_today,
            "requests_by_endpoint":  self.requests_by_endpoint,
            "last_used_at":          self.last_used_at,
            "usage_date":            self.usage_date,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "APIKey":
        return cls(**d)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _today_utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _next_midnight_ts() -> int:
    """Unix timestamp of the next UTC midnight."""
    now = datetime.now(timezone.utc)
    midnight = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
    # advance to next day
    next_midnight_ts = int(midnight.timestamp()) + 86400
    return next_midnight_ts


def _generate_key(tier: str) -> str:
    """Generate a collision-resistant API key using os.urandom (not random)."""
    raw = hashlib.sha256(os.urandom(64)).hexdigest()
    return f"adm_{tier}_{raw}"


# ---------------------------------------------------------------------------
# Store
# ---------------------------------------------------------------------------

class APIKeyStore:
    """
    Thread-safe in-memory store backed by a JSON file.

    All mutation methods acquire the lock and flush to disk immediately.
    Reads are lock-free (Python GIL + immutable lookup is safe enough
    for this use-case; production deployments should use Redis).
    """

    def __init__(self) -> None:
        self._keys: dict[str, APIKey] = {}
        self._lock = Lock()
        self._load()

    # ── Persistence ──────────────────────────────────────────────────────────

    def _load(self) -> None:
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        if _KEYS_FILE.exists():
            try:
                raw = json.loads(_KEYS_FILE.read_text())
                for d in raw.values():
                    k = APIKey.from_dict(d)
                    self._keys[k.key] = k
                return
            except Exception:
                pass  # corrupt file — start fresh

        # First boot: seed a test key
        self._seed_test_key()

    def _flush(self) -> None:
        """Write current state to disk. Must be called under lock."""
        _DATA_DIR.mkdir(parents=True, exist_ok=True)
        payload = {k: v.to_dict() for k, v in self._keys.items()}
        _KEYS_FILE.write_text(json.dumps(payload, indent=2))

    def _seed_test_key(self) -> None:
        key = APIKey(
            key        = _SEEDED_TEST_KEY,
            name       = _SEEDED_TEST_NAME,
            tier       = "test",
            rate_limit = _RATE_LIMITS["test"],
            created_at = _now_iso(),
        )
        self._keys[key.key] = key
        self._flush()
        _banner(key.key)

    # ── CRUD ─────────────────────────────────────────────────────────────────

    def create(self, name: str, tier: str) -> APIKey:
        if tier not in _RATE_LIMITS:
            raise ValueError(f"Unknown tier '{tier}'. Valid: {list(_RATE_LIMITS)}")
        key = APIKey(
            key        = _generate_key(tier),
            name       = name,
            tier       = tier,
            rate_limit = _RATE_LIMITS[tier],
            created_at = _now_iso(),
        )
        with self._lock:
            self._keys[key.key] = key
            self._flush()
        return key

    def get(self, api_key: str) -> APIKey | None:
        return self._keys.get(api_key)

    def list_all(self) -> list[APIKey]:
        return list(self._keys.values())

    def deactivate(self, api_key: str) -> bool:
        with self._lock:
            k = self._keys.get(api_key)
            if not k:
                return False
            k.active = False
            self._flush()
        return True

    # ── Rate limit & usage ───────────────────────────────────────────────────

    def check_and_record(self, api_key: str, endpoint: str) -> tuple[bool, dict[str, str]]:
        """
        Atomically check rate limit and record usage if within limit.

        Returns:
          (allowed: bool, rate_limit_headers: dict)
        """
        with self._lock:
            k = self._keys.get(api_key)
            if k is None:
                return False, {}

            today = _today_utc()
            if k.usage_date != today:
                k.requests_today = 0
                k.usage_date     = today

            remaining = k.rate_limit - k.requests_today
            headers = {
                "X-RateLimit-Limit":     str(k.rate_limit),
                "X-RateLimit-Remaining": str(max(0, remaining - 1)),
                "X-RateLimit-Reset":     str(_next_midnight_ts()),
            }

            if k.requests_today >= k.rate_limit:
                return False, headers

            # Record usage
            k.requests_today              += 1
            k.total_requests              += 1
            k.last_used_at                 = _now_iso()
            k.requests_by_endpoint[endpoint] = (
                k.requests_by_endpoint.get(endpoint, 0) + 1
            )
            self._flush()

        return True, headers

    def get_usage(self, api_key: str) -> APIKey | None:
        return self._keys.get(api_key)


# ---------------------------------------------------------------------------
# Module-level singleton
# ---------------------------------------------------------------------------

key_store = APIKeyStore()


# ---------------------------------------------------------------------------
# Banner (printed once on first boot)
# ---------------------------------------------------------------------------

def _banner(test_key: str) -> None:
    print("\n" + "━" * 62)
    print("  ADM-API  —  First-boot key seeded")
    print("━" * 62)
    print(f"  Test API key : {test_key}")
    print(f"  Rate limit   : {_RATE_LIMITS['test']} requests / day")
    print("  Header       : X-API-Key: <key>")
    print("━" * 62 + "\n", flush=True)
