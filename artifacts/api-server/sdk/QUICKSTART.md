# ADM-API Quickstart

**AI Dungeon Master Infrastructure API** — deterministic narrative compiler for multiplayer simulation systems.

```
GAME EVENTS  →  POST /api/v1/render  →  STRUCTURED NARRATIVE STATE
```

This is infrastructure, not a game. Think Stripe for financial events — ADM-API for narrative events.

---

## Authentication

Every `/v1/` endpoint requires an API key.

```
X-API-Key: adm_test_e2f4a6b8c0d1e3f5a7b9c1d3e5f7000100000001
```

A test key is printed to the server log on first boot. Live keys are created via the admin API.

---

## Endpoints

| Method    | Path               | Description                            | Auth |
|-----------|--------------------|----------------------------------------|------|
| `POST`    | `/api/v1/render`   | Convert events → NarrativeState        | ✅   |
| `WS`      | `/api/v1/stream`   | Real-time incremental event ingestion  | ✅   |
| `POST`    | `/api/v1/simulate` | Deterministic N-step world progression | ✅   |
| `GET`     | `/api/v1/usage`    | Usage stats for your API key           | ✅   |
| `GET`     | `/api/healthz`     | Health check                           | ✗    |
| `GET`     | `/api/docs`        | Swagger UI                             | ✗    |

---

## POST /api/v1/render

### Request

```json
{
  "session_id": "game-session-001",
  "events": [
    {
      "id":        "evt-001",
      "type":      "combat",
      "intensity": 0.85,
      "actors":    ["Northern Legion", "Iron Pact"],
      "tags":      ["war", "conflict"],
      "payload":   {}
    },
    {
      "id":        "evt-002",
      "type":      "politics",
      "intensity": 0.70,
      "actors":    ["faction:High Council"],
      "tags":      ["crisis"],
      "payload":   {}
    }
  ],
  "world_state": {}
}
```

**Event types:** `combat` · `politics` · `economy` · `ecology` · `social` · `weather` · `exploration`

**intensity:** `0.0` (negligible) → `1.0` (maximum)

### Response

```json
{
  "scene_summary":          "Northern Legion forces clash in war, shifting frontlines amid escalating attrition",
  "cinematic_description":  "The war zone is in motion. Combat forces exert measurable pressure...",
  "character_focus":        "Northern Legion",
  "tension_curve":          [1.0, 0.775],
  "narrative_consequences": [
    "Northern Legion: Frontline positions shift in favor of the aggressor",
    "faction:High Council: Governing coalition fractures under accumulated pressure",
    "Conflict escalation triggers regional destabilization cascade"
  ],
  "suggested_next_events": [
    { "type": "politics", "intensity": 0.925, "description": "Political response to military escalation" },
    { "type": "economy",  "intensity": 0.700, "description": "Resource drain from sustained combat" }
  ],
  "llm_prompt": "[ADM-API NARRATIVE CONTEXT v1]\n...",
  "metadata": {
    "avg_intensity":     0.775,
    "dominant_category": "combat",
    "event_count":       2
  }
}
```

**Response headers:**
- `X-ADM-Processing-Ms` — pipeline execution time
- `X-RateLimit-Limit` — daily request quota
- `X-RateLimit-Remaining` — remaining requests today
- `X-RateLimit-Reset` — UTC timestamp of next quota reset

---

## Python

### Install

```bash
# No dependencies for HTTP; websockets for streaming
pip install websockets
```

### Render

```python
from sdk.python.adm_client import ADMClient

client = ADMClient(
    api_key  = "adm_test_e2f4a6b8c0d1e3f5a7b9c1d3e5f7000100000001",
    base_url = "https://your-domain.replit.app/api",
)

result = client.render(
    session_id = "game-session-001",
    events = [
        {
            "id":        "evt-001",
            "type":      "combat",
            "intensity": 0.85,
            "actors":    ["Northern Legion"],
            "tags":      ["war"],
            "payload":   {}
        }
    ]
)

print(result["scene_summary"])
print(result["tension_curve"])
print(result["metadata"])
```

### WebSocket streaming

```python
import asyncio
from sdk.python.adm_client import ADMStreamClient

async def main():
    async with ADMStreamClient(
        api_key  = "adm_test_...",
        base_url = "ws://localhost:80/api",
    ) as stream:
        update = await stream.send_event(
            event = {
                "id": "e1", "type": "combat", "intensity": 0.9,
                "actors": ["Legion"], "tags": ["war"], "payload": {}
            },
            session_id = "session-001",
        )
        print(update["scene_summary"])
        print(update["tension_curve"])

asyncio.run(main())
```

### Check usage

```python
u = client.usage()
print(f"Used today: {u['requests_today']} / {u['rate_limit']}")
print(f"Remaining:  {u['remaining_today']}")
```

---

## JavaScript

### Render

```javascript
import { ADMClient } from "./sdk/js/adm_client.js";

const client = new ADMClient({
  apiKey:  "adm_test_e2f4a6b8c0d1e3f5a7b9c1d3e5f7000100000001",
  baseUrl: "https://your-domain.replit.app/api",
});

const result = await client.render("game-session-001", [
  {
    id:        "evt-001",
    type:      "combat",
    intensity: 0.85,
    actors:    ["Northern Legion"],
    tags:      ["war"],
    payload:   {}
  }
]);

console.log(result.scene_summary);
console.log(result.tension_curve);
```

### WebSocket streaming

```javascript
import { ADMStreamClient } from "./sdk/js/adm_client.js";

const stream = new ADMStreamClient({
  apiKey:  "adm_test_...",
  baseUrl: "ws://localhost:80/api",
});

stream.onUpdate = (update) => {
  console.log("Scene:", update.scene_summary);
  console.log("Tension:", update.tension_curve);
};

await stream.connect();

await stream.sendEvent("session-001", {
  id: "e1", type: "combat", intensity: 0.9,
  actors: ["Legion"], tags: ["war"], payload: {}
});

await stream.close();
```

### curl

```bash
export API_KEY="adm_test_e2f4a6b8c0d1e3f5a7b9c1d3e5f7000100000001"
export BASE="https://your-domain.replit.app/api"

# Render
curl -X POST "$BASE/v1/render" \
  -H "X-API-Key: $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "demo",
    "events": [{
      "id": "e1", "type": "combat", "intensity": 0.85,
      "actors": ["Legion"], "tags": ["war"], "payload": {}
    }]
  }'

# Usage
curl "$BASE/v1/usage" -H "X-API-Key: $API_KEY"
```

---

## Admin: Create API Keys

```bash
# Create a live key
curl -X POST "$BASE/v1/admin/keys" \
  -H "X-Admin-Key: $ADM_ADMIN_KEY" \
  -H "Content-Type: application/json" \
  -d '{ "name": "My Game Studio", "tier": "live" }'

# List all keys
curl "$BASE/v1/admin/keys" -H "X-Admin-Key: $ADM_ADMIN_KEY"

# Revoke a key
curl -X POST "$BASE/v1/admin/keys/adm_live_.../deactivate" \
  -H "X-Admin-Key: $ADM_ADMIN_KEY"
```

**Tiers:**

| Tier    | Rate limit        |
|---------|-------------------|
| `test`  | 100 req / day     |
| `live`  | 1,000 req / day   |
| `admin` | 10,000 req / day  |

---

## Error responses

All errors return a consistent JSON envelope:

```json
{
  "error":   "invalid_api_key",
  "message": "The provided API key is invalid or has been revoked.",
  "code":    "ADM_AUTH_002",
  "docs":    "/api/docs"
}
```

| HTTP | error                  | code           | Cause                        |
|------|------------------------|----------------|------------------------------|
| 401  | `missing_api_key`      | ADM_AUTH_001   | No key provided              |
| 401  | `invalid_api_key`      | ADM_AUTH_002   | Key not found or revoked     |
| 403  | `forbidden`            | ADM_AUTH_003   | Admin key required           |
| 422  | `validation_error`     | ADM_VAL_001    | Request schema violation     |
| 429  | `rate_limit_exceeded`  | ADM_RATE_001   | Daily quota reached          |
| 500  | `internal_error`       | ADM_SRV_001    | Unexpected server error      |

---

## Design guarantees

- **Deterministic** — same input always returns byte-identical output
- **Stateless core** — pipeline has no hidden state; sessions live only in the stream endpoint
- **No AI dependency** — fully rule-based engine
- **`<100ms` latency** — for ≤20 events; `X-ADM-Processing-Ms` header on every response
- **Versioned** — all routes under `/v1/`; future `/v2/` evolution is isolated
