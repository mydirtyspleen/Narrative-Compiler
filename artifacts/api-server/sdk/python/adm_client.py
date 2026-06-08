"""
ADM-API Python Client — v2

Synchronous HTTP + async WebSocket client for the AI Dungeon Master
Infrastructure API.

Dependencies:
  stdlib only for HTTP (urllib)
  `pip install websockets` for the streaming client (ADMStreamClient)

Features (v2):
  - Automatic retry with exponential backoff for 5xx and network errors
  - Per-request connect + read timeouts
  - TypedDict response types for IDE auto-complete
  - Named constants for error codes
  - User-Agent header for server-side analytics

Usage:
    from adm_client import ADMClient, NarrativeState

    client = ADMClient(
        api_key  = "adm_live_...",
        base_url = "https://your-domain.replit.app/api",
    )

    result: NarrativeState = client.render(
        session_id = "game-session-001",
        events     = [
            {
                "id":        "evt-001",
                "type":      "combat",
                "intensity": 0.85,
                "actors":    ["Northern Legion", "Iron Pact"],
                "tags":      ["war", "conflict"],
                "payload":   {},
            }
        ],
    )
    print(result["scene_summary"])
    print(result["tension_curve"])
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from typing import Any, TypedDict

__version__ = "2.0.0"

# ── Error codes ───────────────────────────────────────────────────────────────

ADM_MISSING_KEY      = "ADM_AUTH_001"
ADM_INVALID_KEY      = "ADM_AUTH_002"
ADM_FORBIDDEN        = "ADM_AUTH_003"
ADM_VALIDATION_ERROR = "ADM_VAL_001"
ADM_RATE_LIMITED     = "ADM_RATE_001"
ADM_SERVER_ERROR     = "ADM_SRV_001"


# ── Typed response shapes ─────────────────────────────────────────────────────

class RenderMetadata(TypedDict):
    avg_intensity:     float
    dominant_category: str
    event_count:       int


class SuggestedNextEvent(TypedDict):
    type:        str
    intensity:   float
    description: str


class NarrativeState(TypedDict):
    scene_summary:          str
    cinematic_description:  str
    character_focus:        str | None
    tension_curve:          list[float]
    narrative_consequences: list[str]
    suggested_next_events:  list[SuggestedNextEvent]
    llm_prompt:             str
    metadata:               RenderMetadata


class SimulatedEvent(TypedDict):
    id:        str
    type:      str
    intensity: float
    actors:    list[str]
    tags:      list[str]
    payload:   dict[str, Any]
    step:      int
    rationale: str


class SimulateResponse(TypedDict):
    session_id:        str
    simulated_events:  list[SimulatedEvent]
    projected_tension: list[float]
    world_trajectory:  str
    dominant_force:    str


class UsageResponse(TypedDict):
    key:                  str
    name:                 str
    tier:                 str
    rate_limit:           int
    total_requests:       int
    requests_today:       int
    remaining_today:      int
    usage_date:           str
    last_used_at:         str | None
    requests_by_endpoint: dict[str, int]


# ── Error class ───────────────────────────────────────────────────────────────

class ADMError(Exception):
    """
    Raised when the ADM-API returns a non-2xx response.

    Attributes
    ----------
    status : HTTP status code
    code   : ADM error code string (e.g. "ADM_AUTH_002")
    body   : Full parsed error response body
    """
    def __init__(self, status: int, body: dict) -> None:
        self.status = status
        self.code   = body.get("code", "")
        self.body   = body
        super().__init__(
            f"ADM-API error {status} [{self.code}]: "
            f"{body.get('error', 'unknown')} — {body.get('message', '')}"
        )

    @property
    def is_auth_error(self) -> bool:
        return self.status in (401, 403)

    @property
    def is_rate_limited(self) -> bool:
        return self.status == 429

    @property
    def is_server_error(self) -> bool:
        return self.status >= 500

    @property
    def is_validation_error(self) -> bool:
        return self.status == 422


class ADMNetworkError(ADMError):
    """Raised when a network-level error occurs (timeout, connection refused, etc.)."""
    def __init__(self, exc: Exception) -> None:
        self.status = 0
        self.code   = "ADM_NET_001"
        self.body   = {"error": "network_error", "message": str(exc)}
        Exception.__init__(self, f"ADM-API network error: {exc}")


# ── Retry configuration ───────────────────────────────────────────────────────

_DEFAULT_RETRY_STATUS = frozenset({500, 502, 503, 504})


# ── HTTP client ───────────────────────────────────────────────────────────────

class ADMClient:
    """
    Synchronous HTTP client for the ADM-API.

    Parameters
    ----------
    api_key      : Your ADM API key (adm_test_... or adm_live_...).
    base_url     : Base URL, e.g. "https://app.replit.app/api".
                   Defaults to localhost for development.
    timeout      : Total request timeout in seconds (default 10).
    max_retries  : Max retry attempts for 5xx responses (default 3).
    retry_delay  : Base delay in seconds for exponential backoff (default 0.5).
    """

    def __init__(
        self,
        api_key:     str,
        base_url:    str = "http://localhost:80/api",
        timeout:     float = 10.0,
        max_retries: int   = 3,
        retry_delay: float = 0.5,
    ) -> None:
        self.api_key     = api_key
        self.base_url    = base_url.rstrip("/")
        self.timeout     = timeout
        self.max_retries = max_retries
        self.retry_delay = retry_delay

    # ── Internal ─────────────────────────────────────────────────────────────

    def _request(
        self,
        method:  str,
        path:    str,
        body:    dict | None = None,
        *,
        retries: int | None  = None,
    ) -> dict:
        """
        Execute an HTTP request with retry + exponential backoff.

        Parameters
        ----------
        method  : HTTP method ("GET", "POST", etc.)
        path    : Endpoint path, e.g. "/v1/render"
        body    : Optional JSON-serializable request body
        retries : Override max_retries for this call (None = use instance default)
        """
        max_retries  = self.max_retries if retries is None else retries
        url          = f"{self.base_url}{path}"
        payload      = json.dumps(body).encode() if body is not None else None
        last_exc: Exception | None = None

        for attempt in range(max_retries + 1):
            req = urllib.request.Request(
                url     = url,
                data    = payload,
                method  = method,
                headers = {
                    "X-API-Key":    self.api_key,
                    "Content-Type": "application/json",
                    "Accept":       "application/json",
                    "User-Agent":   f"adm-python-client/{__version__}",
                },
            )

            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    return json.loads(resp.read())

            except urllib.error.HTTPError as e:
                try:
                    err_body = json.loads(e.read())
                except Exception:
                    err_body = {"error": "http_error", "message": str(e), "code": ""}

                exc = ADMError(e.code, err_body)

                # Never retry auth or validation errors — they won't recover
                if e.code in (401, 403, 422):
                    raise exc

                # Retry on rate-limit: back off then re-raise after max attempts
                if e.code == 429:
                    if attempt < max_retries:
                        time.sleep(self.retry_delay * (2 ** attempt))
                        last_exc = exc
                        continue
                    raise exc

                # Retry on 5xx
                if e.code in _DEFAULT_RETRY_STATUS and attempt < max_retries:
                    time.sleep(self.retry_delay * (2 ** attempt))
                    last_exc = exc
                    continue

                raise exc

            except TimeoutError as e:
                exc = ADMNetworkError(e)
                if attempt < max_retries:
                    time.sleep(self.retry_delay * (2 ** attempt))
                    last_exc = exc
                    continue
                raise exc

            except OSError as e:
                exc = ADMNetworkError(e)
                if attempt < max_retries:
                    time.sleep(self.retry_delay * (2 ** attempt))
                    last_exc = exc
                    continue
                raise exc

        # Should not be reached, but satisfy type checker
        raise last_exc or ADMNetworkError(RuntimeError("Unexpected retry exhaustion"))

    # ── Public API ────────────────────────────────────────────────────────────

    def render(
        self,
        session_id:  str,
        events:      list[dict[str, Any]],
        world_state: dict[str, Any] | None = None,
    ) -> NarrativeState:
        """
        POST /v1/render

        Converts a batch of game events into a full deterministic NarrativeState.

        Parameters
        ----------
        session_id  : Client-assigned session identifier.
        events      : List of game event dicts. Each must have:
                      id (str), type (EventType), intensity (float 0–1),
                      actors (list[str]), tags (list[str]), payload (dict).
        world_state : Reserved. Pass None or omit.

        Returns
        -------
        NarrativeState TypedDict — all 8 fields present and typed.
        """
        return self._request("POST", "/v1/render", {
            "session_id":  session_id,
            "events":      events,
            "world_state": world_state or {},
        })

    def simulate(
        self,
        session_id:     str,
        current_events: list[dict[str, Any]] | None = None,
        steps:          int                         = 3,
        world_state:    dict[str, Any] | None       = None,
    ) -> SimulateResponse:
        """
        POST /v1/simulate

        Generates deterministic cascading future events from current world state.

        Parameters
        ----------
        session_id     : Seeds the deterministic simulation cascade.
                         Same session_id + same events → identical simulation.
        current_events : Seed events. Pass [] for minimal cascade from empty world.
        steps          : Simulation steps to generate [1–10].
        world_state    : Reserved. Pass None or omit.

        Returns
        -------
        SimulateResponse TypedDict.
        """
        return self._request("POST", "/v1/simulate", {
            "session_id":     session_id,
            "current_events": current_events or [],
            "steps":          steps,
            "world_state":    world_state or {},
        })

    def usage(self) -> UsageResponse:
        """
        GET /v1/usage

        Returns usage statistics for the authenticated API key.
        Does NOT consume rate-limit quota.

        Returns
        -------
        UsageResponse TypedDict with daily quota and per-endpoint breakdown.
        """
        return self._request("GET", "/v1/usage", retries=0)

    def playground(
        self,
        events:      list[dict[str, Any]],
        session_id:  str = "playground",
        world_state: dict[str, Any] | None = None,
    ) -> NarrativeState:
        """
        POST /v1/playground/render

        Unauthenticated render for quick testing. Max 5 events. No API key needed.
        Rate-limited to 30 requests/60s per IP.

        Parameters
        ----------
        events     : 1–5 game event dicts.
        session_id : Optional session label (default "playground").

        Returns
        -------
        NarrativeState TypedDict — byte-identical to authenticated render for same input.
        """
        return self._request("POST", "/v1/playground/render", {
            "session_id":  session_id,
            "events":      events,
            "world_state": world_state or {},
        })


# ── Async streaming client ────────────────────────────────────────────────────

class ADMStreamClient:
    """
    Async WebSocket client for the /v1/stream endpoint.

    Requires: pip install websockets

    Features (v2):
      - Automatic reconnect on network disconnect (configurable max_reconnects)
      - Exponential backoff between reconnect attempts
      - Typed StreamUpdate callback
      - Connection state property

    Usage:
        import asyncio
        from adm_client import ADMStreamClient

        async def main():
            async with ADMStreamClient(
                api_key  = "adm_test_...",
                base_url = "ws://localhost:80/api",
            ) as client:
                async for update in client.stream("session-001"):
                    print(update["scene_summary"])

                    await client.send_event(
                        {
                            "id": "e1", "type": "combat", "intensity": 0.8,
                            "actors": ["Legion"], "tags": ["war"], "payload": {}
                        },
                        session_id = "session-001",
                    )

        asyncio.run(main())
    """

    def __init__(
        self,
        api_key:       str,
        base_url:      str = "ws://localhost:80/api",
        max_reconnects: int = 5,
        reconnect_delay: float = 1.0,
    ) -> None:
        self.api_key         = api_key
        self.base_url        = (
            base_url.rstrip("/")
            .replace("http://", "ws://")
            .replace("https://", "wss://")
        )
        self.max_reconnects  = max_reconnects
        self.reconnect_delay = reconnect_delay
        self._ws             = None
        self._connected      = False

    @property
    def connected(self) -> bool:
        """True if the WebSocket is currently open."""
        return self._connected

    async def __aenter__(self) -> "ADMStreamClient":
        await self._connect()
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    async def _connect(self) -> None:
        try:
            import websockets  # type: ignore
        except ImportError:
            raise ImportError("Install websockets: pip install websockets")

        url = f"{self.base_url}/v1/stream?api_key={self.api_key}"

        for attempt in range(self.max_reconnects + 1):
            try:
                self._ws        = await websockets.connect(url)
                self._connected = True
                return
            except Exception as e:
                if attempt >= self.max_reconnects:
                    raise ADMNetworkError(e) from e
                wait = self.reconnect_delay * (2 ** attempt)
                await __import__("asyncio").sleep(wait)

    async def _ensure_connected(self) -> None:
        """Re-connect if the WebSocket has dropped."""
        if not self._connected or self._ws is None:
            await self._connect()

    async def send_event(
        self,
        event:      dict[str, Any],
        session_id: str,
        world_state: dict[str, Any] | None = None,
    ) -> dict:
        """
        Send one event and receive the updated StreamUpdate.

        On network disconnect, automatically reconnects (up to max_reconnects)
        and retries the send once.

        Returns
        -------
        StreamUpdate dict: session_id, scene_summary, tension_curve,
                           narrative_consequences, event_count.
        """
        await self._ensure_connected()

        payload = json.dumps({
            "session_id":  session_id,
            "event":       event,
            "world_state": world_state or {},
        })

        for attempt in range(2):  # one retry on disconnect
            try:
                await self._ws.send(payload)
                raw = await self._ws.recv()
                return json.loads(raw)
            except Exception as e:
                if attempt == 0:
                    self._connected = False
                    await self._connect()
                else:
                    raise ADMNetworkError(e) from e

    async def reset_session(self, session_id: str) -> None:
        """Clear the server-side session history for session_id."""
        await self._ensure_connected()
        await self._ws.send(json.dumps({"action": "reset", "session_id": session_id}))
        await self._ws.recv()  # consume reset_ack

    async def close(self) -> None:
        """Send a graceful close frame and tear down the connection."""
        if self._ws and self._connected:
            try:
                await self._ws.send(json.dumps({"action": "close"}))
            except Exception:
                pass
            try:
                await self._ws.close()
            except Exception:
                pass
        self._connected = False
        self._ws        = None


# ── CLI smoke-test ────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    api_key  = sys.argv[1] if len(sys.argv) > 1 else "adm_test_e2f4a6b8c0d1e3f5a7b9c1d3e5f7000100000001"
    base_url = sys.argv[2] if len(sys.argv) > 2 else "http://localhost:80/api"

    client = ADMClient(api_key=api_key, base_url=base_url)

    print("── render ───────────────────────────────")
    result = client.render(
        session_id = "sdk-smoke-test",
        events     = [
            {"id": "t1", "type": "combat",   "intensity": 0.9,  "actors": ["Alpha"],   "tags": ["war"],    "payload": {}},
            {"id": "t2", "type": "politics", "intensity": 0.65, "actors": ["Council"], "tags": ["crisis"], "payload": {}},
        ],
    )
    print(f"  scene_summary : {result['scene_summary']}")
    print(f"  tension_curve : {result['tension_curve']}")
    print(f"  dominant      : {result['metadata']['dominant_category']}")

    print("\n── playground (no auth) ─────────────────")
    try:
        pg = client.playground(events=[
            {"id": "pg1", "type": "ecology", "intensity": 0.5, "actors": [], "tags": [], "payload": {}},
        ])
        print(f"  scene_summary : {pg['scene_summary']}")
    except ADMError as e:
        print(f"  playground error: {e}")

    print("\n── usage ────────────────────────────────")
    u = client.usage()
    print(f"  requests_today : {u['requests_today']} / {u['rate_limit']}")
    print(f"  remaining      : {u['remaining_today']}")
    print(f"  by_endpoint    : {u['requests_by_endpoint']}")
