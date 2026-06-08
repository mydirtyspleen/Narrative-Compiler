"""
session/store.py — Abstract session storage layer for WebSocket event history.

Abstracts the in-process dict used by /v1/stream so the implementation
can be swapped for Redis without changing route code.

Implementations:
  InMemorySessionStore   — default; per-process dict; not shared across workers
  RedisSessionStore      — stub; wired when REDIS_URL env var is set

Usage in routes:
  from adm_api.session.store import get_session_store
  store = get_session_store()   # returns the singleton configured at startup

  # In WebSocket handler:
  all_events = await store.append(session_id, event)
  await store.clear(session_id)
  events = await store.get(session_id)

Scaling notes:
  Single-node (default):
    InMemorySessionStore — works perfectly, zero dependencies.

  Multi-node (horizontal scaling):
    Set REDIS_URL env var and import RedisSessionStore.
    All workers share session state via Redis LIST operations.
    Required packages: redis[asyncio] (pip install redis[asyncio])
    See RedisSessionStore docstring for full migration steps.
"""

from __future__ import annotations

import asyncio
import os
from abc import ABC, abstractmethod
from collections import defaultdict
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from adm_api.models.schemas import GameEvent


# ============================================================================
# Abstract interface
# ============================================================================

class SessionStore(ABC):
    """
    Abstract session store for WebSocket event history.

    All methods are async to support both in-process (trivially awaitable)
    and I/O-bound (Redis) implementations without changing call sites.
    """

    @abstractmethod
    async def append(self, session_id: str, event: "GameEvent") -> list["GameEvent"]:
        """
        Append an event to the session history and return all events.

        Atomic: the append and read happen under the same lock/transaction.
        """
        ...

    @abstractmethod
    async def get(self, session_id: str) -> list["GameEvent"]:
        """Return a snapshot of all events for the session (oldest first)."""
        ...

    @abstractmethod
    async def clear(self, session_id: str) -> None:
        """Remove all events for the session."""
        ...

    @abstractmethod
    async def delete(self, session_id: str) -> None:
        """Delete the session entirely (alias for clear; kept for semantic clarity)."""
        ...

    @abstractmethod
    async def list_sessions(self) -> list[str]:
        """Return all known session IDs. Primarily for observability/admin."""
        ...


# ============================================================================
# In-memory implementation (default)
# ============================================================================

class InMemorySessionStore(SessionStore):
    """
    In-process session store backed by a dict + asyncio.Lock per session.

    Properties:
      - Zero dependencies
      - Thread-safe via per-session asyncio.Lock
      - Not shared across processes — only suitable for single-worker deployments
        or WebSocket-aware load balancing (sticky sessions)

    Production note:
      When running with multiple Gunicorn workers (WORKERS > 1), each worker
      has its own InMemorySessionStore. A client reconnecting to a different
      worker will see an empty session. Migrate to RedisSessionStore to fix this.
    """

    def __init__(self) -> None:
        self._events: dict[str, list] = defaultdict(list)
        self._locks:  dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    async def append(self, session_id: str, event: "GameEvent") -> list["GameEvent"]:
        async with self._locks[session_id]:
            self._events[session_id].append(event)
            return list(self._events[session_id])

    async def get(self, session_id: str) -> list["GameEvent"]:
        async with self._locks[session_id]:
            return list(self._events[session_id])

    async def clear(self, session_id: str) -> None:
        async with self._locks[session_id]:
            self._events[session_id].clear()

    async def delete(self, session_id: str) -> None:
        async with self._locks[session_id]:
            self._events.pop(session_id, None)

    async def list_sessions(self) -> list[str]:
        return list(self._events.keys())

    # ── Observability ─────────────────────────────────────────────────────────

    @property
    def session_count(self) -> int:
        return len(self._events)

    @property
    def total_events(self) -> int:
        return sum(len(v) for v in self._events.values())


# ============================================================================
# Redis stub (multi-node scaling path)
# ============================================================================

class RedisSessionStore(SessionStore):
    """
    Redis-backed session store for horizontal scaling.

    Each session maps to a Redis LIST key:
      Key:   "adm:session:{session_id}"
      Value: JSON-serialized GameEvent objects, one per LIST element
      TTL:   24 hours (configurable via SESSION_TTL_SECONDS env var)

    Migration from InMemorySessionStore:
      1. Add Redis to your stack:  pip install redis[asyncio]
      2. Set REDIS_URL env var:    redis://localhost:6379/0
      3. Change get_session_store() below to return RedisSessionStore()
      4. Existing in-flight sessions will be empty on restart (expected)

    Multi-node WebSocket notes:
      WebSocket connections are long-lived. With Redis-backed sessions,
      a client can reconnect to ANY worker and see its full history.
      However, live StreamUpdate pushes still require the client to be
      connected to the specific worker that processes the event.
      For full multi-node streaming, add a Redis pub/sub broadcast layer:

        On event processed:
          r.publish(f"adm:stream:{session_id}", update_json)
        Each worker subscribes and forwards to local WebSocket connections.

    Example usage:
      store = RedisSessionStore(redis_url="redis://localhost:6379/0")
      await store.connect()   # call once on startup
    """

    def __init__(
        self,
        redis_url: str = "redis://localhost:6379/0",
        ttl_seconds: int = 86_400,  # 24 hours
        key_prefix: str = "adm:session:",
    ) -> None:
        self._url        = redis_url
        self._ttl        = ttl_seconds
        self._prefix     = key_prefix
        self._client     = None  # set by connect()

    async def connect(self) -> None:
        """
        Initialize the Redis connection pool.
        Call once on application startup:
          store = RedisSessionStore()
          await store.connect()
        """
        try:
            import redis.asyncio as aioredis  # type: ignore
            self._client = await aioredis.from_url(
                self._url,
                encoding       = "utf-8",
                decode_responses = True,
            )
            # Smoke-test
            await self._client.ping()
        except ImportError:
            raise ImportError(
                "redis[asyncio] is required for RedisSessionStore. "
                "Install with: pip install redis[asyncio]"
            )

    def _key(self, session_id: str) -> str:
        return f"{self._prefix}{session_id}"

    async def append(self, session_id: str, event: "GameEvent") -> list["GameEvent"]:
        """
        Append event to Redis LIST and return all events.
        Uses MULTI/EXEC pipeline for atomicity.
        """
        import json
        from adm_api.models.schemas import GameEvent as GE

        key        = self._key(session_id)
        event_json = event.model_dump_json()

        async with self._client.pipeline(transaction=True) as pipe:
            await pipe.rpush(key, event_json)
            await pipe.expire(key, self._ttl)
            await pipe.lrange(key, 0, -1)
            results = await pipe.execute()

        raw_list = results[2]  # lrange result
        return [GE.model_validate_json(r) for r in raw_list]

    async def get(self, session_id: str) -> list["GameEvent"]:
        from adm_api.models.schemas import GameEvent as GE
        raw_list = await self._client.lrange(self._key(session_id), 0, -1)
        return [GE.model_validate_json(r) for r in raw_list]

    async def clear(self, session_id: str) -> None:
        await self._client.delete(self._key(session_id))

    async def delete(self, session_id: str) -> None:
        await self._client.delete(self._key(session_id))

    async def list_sessions(self) -> list[str]:
        keys = await self._client.keys(f"{self._prefix}*")
        return [k[len(self._prefix):] for k in keys]


# ============================================================================
# Factory — returns the configured singleton
# ============================================================================

_store: SessionStore | None = None


def get_session_store() -> SessionStore:
    """
    Return the configured session store singleton.

    Selection logic:
      REDIS_URL env var set → RedisSessionStore (raises ImportError if redis not installed)
      otherwise             → InMemorySessionStore

    The store is created once on first call and reused.
    """
    global _store
    if _store is None:
        redis_url = os.environ.get("REDIS_URL")
        if redis_url:
            _store = RedisSessionStore(redis_url=redis_url)
            # connect() is async — called from main.py lifespan event if REDIS_URL is set
        else:
            _store = InMemorySessionStore()
    return _store
