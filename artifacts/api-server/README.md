# ADM-API

**AI Dungeon Master Infrastructure API** — a deterministic real-time narrative compiler for multiplayer simulation systems.

```
GAME EVENTS  →  ADM-API  →  STRUCTURED NARRATIVE STATE
```

ADM-API is infrastructure software, not a game. It occupies the same position in your stack that Stripe does for payments — a single, reliable, versioned API that converts structured input into structured output, with determinism and latency guarantees you can build a product on.

---

## What ADM-API Is

ADM-API accepts a stream of typed game events (combat, politics, economy, ecology, social, weather, exploration) and returns a fully structured `NarrativeState` pack:

| Field | Description |
|---|---|
| `scene_summary` | One-sentence human-readable scene description |
| `cinematic_description` | Longer atmospheric description, tone-mapped to event intensity |
| `character_focus` | Dominant actor across all events |
| `tension_curve` | Per-event tension values [0.0–1.0], sorted by intensity |
| `narrative_consequences` | Deterministic structured outcomes (hash-stable, not random) |
| `suggested_next_events` | Typed recommendations for the next simulation step |
| `llm_prompt` | Pre-formatted context block ready to pass to any LLM |
| `metadata` | avg_intensity, dominant_category, event_count |

Every output field is derived entirely from the input. No AI required. No network calls. No stochastic state.

---

## Why Deterministic Narrative Infrastructure

### The Problem

Multiplayer simulation games face a coordination problem: when narrative content is generated at runtime by an AI model, the same world state can produce different narratives for different players, on different servers, at different times. This breaks:

- **Replay systems** — a recorded session can't be re-narrated identically
- **Moderation** — you can't audit what narrative was shown without storing it
- **Multiplayer sync** — player A and player B may see different descriptions of the same event
- **Testing** — non-deterministic output means your test suite can't assert on content

### The Solution

ADM-API treats narrative as a **pure function**:

```
f(events, world_state) → NarrativeState
```

Same input always returns byte-identical output. No AI dependency in the hot path. Consequence selection uses `hash(event.id) % pool_size` — same event ID always picks the same consequence text. Tension scores are computed from a deterministic formula. Rankings are stable sort by intensity.

The `llm_prompt` field is included for integrations that *want* to enhance output with AI — but the pipeline itself never requires it.

---

## Quick Start

### 1. Get a test key

Start the server. On first boot, a test key is printed to stdout:

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ADM-API  —  First-boot key seeded
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Test API key : adm_test_e2f4a6b8c0d1e3f5a7b9c1d3e5f7000100000001
  Rate limit   : 100 requests / day
  Header       : X-API-Key: <key>
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
```

### 2. Try the playground (no key required)

```bash
curl -X POST https://your-host/api/v1/playground/render \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "test",
    "events": [
      {
        "id": "e1",
        "type": "combat",
        "intensity": 0.85,
        "actors": ["Northern Legion", "Iron Pact"],
        "tags": ["war", "conflict"]
      }
    ]
  }'
```

### 3. Authenticated render

```bash
curl -X POST https://your-host/api/v1/render \
  -H "X-API-Key: adm_test_..." \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "game-session-001",
    "events": [
      {"id": "e1", "type": "combat",   "intensity": 0.88, "actors": ["Iron Pact"],       "tags": ["war"],    "payload": {}},
      {"id": "e2", "type": "politics", "intensity": 0.65, "actors": ["faction:Council"], "tags": ["crisis"], "payload": {}}
    ],
    "world_state": {}
  }'
```

---

## Endpoints

| Method | Path | Auth | Description |
|---|---|---|---|
| `POST` | `/v1/render` | API key | Batch event → full NarrativeState |
| `WS` | `/v1/stream` | API key (query param) | Incremental streaming |
| `POST` | `/v1/simulate` | API key | Deterministic N-step world progression |
| `GET` | `/v1/usage` | API key | Daily quota and usage breakdown |
| `GET` | `/v1/metrics` | None | Aggregate platform metrics |
| `POST` | `/v1/playground/render` | None (IP rate-limited) | Developer sandbox |
| `GET` | `/v1/info` | None | Service metadata |
| `GET` | `/healthz` | None | Health probe |
| `POST` | `/v1/admin/keys` | Admin key | Create API key |
| `GET` | `/v1/admin/keys` | Admin key | List all keys |
| `POST` | `/v1/admin/keys/{key}/deactivate` | Admin key | Revoke key |

Interactive docs: `GET /api/docs` (Swagger UI)

---

## Integration Examples

### Python SDK

```python
from sdk.python.adm_client import ADMClient

client = ADMClient(
    api_key  = "adm_live_...",
    base_url = "https://your-host/api",
)

result = client.render(
    session_id = "session-001",
    events     = [
        {"id": "e1", "type": "combat", "intensity": 0.85,
         "actors": ["Northern Legion"], "tags": ["war"], "payload": {}}
    ],
)

print(result["scene_summary"])
print(result["tension_curve"])
```

### JavaScript / TypeScript SDK

```javascript
import { ADMClient } from "./sdk/js/adm_client.js";

const client = new ADMClient({
  apiKey:  "adm_live_...",
  baseUrl: "https://your-host/api",
});

const result = await client.render("session-001", [
  { id: "e1", type: "combat", intensity: 0.85,
    actors: ["Northern Legion"], tags: ["war"], payload: {} }
]);

console.log(result.scene_summary);
console.log(result.tension_curve);
```

### WebSocket streaming (JavaScript)

```javascript
import { ADMStreamClient } from "./sdk/js/adm_client.js";

const stream = new ADMStreamClient({
  apiKey:  "adm_live_...",
  baseUrl: "wss://your-host/api",
});

await stream.connect();

stream.onUpdate = (update) => {
  console.log(`[${update.session_id}] ${update.scene_summary}`);
  console.log("Tension:", update.tension_curve);
};

// Send events as they occur in-game
await stream.sendEvent("session-001", {
  id: "event-001", type: "combat", intensity: 0.9,
  actors: ["Legion"], tags: ["war"], payload: {}
});
```

### Unity / C# (plain HTTP)

```csharp
using System.Net.Http;
using System.Net.Http.Headers;
using Newtonsoft.Json;

var client = new HttpClient();
client.DefaultRequestHeaders.Add("X-API-Key", "adm_live_...");

var payload = new {
    session_id = "unity-session",
    events = new[] {
        new { id = "e1", type = "combat", intensity = 0.85f,
              actors = new[] { "Player Guild" }, tags = new[] { "war" }, payload = new {} }
    },
    world_state = new {}
};

var response = await client.PostAsync(
    "https://your-host/api/v1/render",
    new StringContent(JsonConvert.SerializeObject(payload), Encoding.UTF8, "application/json")
);

var result = JsonConvert.DeserializeObject<dynamic>(await response.Content.ReadAsStringAsync());
Console.WriteLine(result.scene_summary);
```

### Roblox / Lua

```lua
local HttpService = game:GetService("HttpService")

local function renderNarrative(events)
    local payload = HttpService:JSONEncode({
        session_id = "roblox-session",
        events = events,
        world_state = {}
    })

    local response = HttpService:RequestAsync({
        Url = "https://your-host/api/v1/render",
        Method = "POST",
        Headers = {
            ["X-API-Key"] = "adm_live_...",
            ["Content-Type"] = "application/json",
        },
        Body = payload
    })

    if response.Success then
        local data = HttpService:JSONDecode(response.Body)
        return data.scene_summary, data.tension_curve
    end
end
```

---

## Architecture

```
┌──────────────────────────────────────────────────────────────┐
│                         ADM-API                              │
│                                                              │
│  POST /v1/render                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Auth → Rate Limit → Pipeline → Response             │   │
│  │                                                      │   │
│  │  Pipeline (pure, stateless):                         │   │
│  │    1. event_ranker         — sort by intensity       │   │
│  │    2. tension_engine       — compute tension curve   │   │
│  │    3. character_focus_engine — resolve dominant actor│   │
│  │    4. narrative_engine     — scene summary + desc    │   │
│  │    5. consequence_engine   — hash-stable outcomes    │   │
│  │    6. prompt_generator     — LLM context block       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  WS /v1/stream                                               │
│  ┌──────────────────────────────────────────────────────┐   │
│  │  Auth → per-session event accumulator → Pipeline     │   │
│  │  Session state: in-process dict (Redis-ready)        │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                              │
│  Auth Layer: APIKeyStore (in-memory + JSON persistence)      │
│  Metrics: in-process counters + latency histogram            │
│  Logging: JSON structured to stdout                          │
└──────────────────────────────────────────────────────────────┘
```

### Determinism guarantees

| Property | Mechanism |
|---|---|
| Event ranking | Stable sort by `intensity DESC`, tie-break by `id` |
| Tension scores | Pure formula: `(base_weight + intensity) / 2 ± modifier`, clamped |
| Consequence selection | `hash(event.id) % len(pool)` — no PRNG, no seed |
| Simulation steps | `hash(step + event.id + session_id)` — deterministic cascade rules |
| Narrative text | Template-driven, no generative model |

---

## Event Types

| Type | Base Tension Weight | Cascade Threshold |
|---|---|---|
| `combat` | 0.9 | 0.7 |
| `politics` | 0.8 | — |
| `social` | 0.6 | 0.75 |
| `ecology` | 0.6 | 0.6 |
| `economy` | 0.5 | 0.6 |
| `weather` | 0.4 | — |
| `exploration` | 0.3 | — |

### Tension modifiers

- `+0.25` if event tags contain `war`, `conflict`, or `chaos`
- `-0.25` if event tags contain `peace` or `order`
- Final value is clamped to `[0.0, 1.0]`

---

## Authentication

All `/v1/` endpoints (except `/v1/playground/render`, `/v1/metrics`, and `/v1/info`) require an API key.

**Headers:**
```
X-API-Key: adm_live_<hex>
```
or
```
Authorization: Bearer adm_live_<hex>
```

**WebSocket:** Pass key as query param: `wss://host/api/v1/stream?api_key=adm_...`

### Key tiers

| Tier | Daily limit | Format |
|---|---|---|
| `test` | 100 req/day | `adm_test_<40hex>` |
| `live` | 1 000 req/day | `adm_live_<64hex>` |
| `admin` | 10 000 req/day | `adm_admin_<64hex>` |

### Rate limit headers

Every authenticated response includes:
```
X-RateLimit-Limit:     100
X-RateLimit-Remaining: 97
X-RateLimit-Reset:     1779408000    (next UTC midnight, unix timestamp)
X-ADM-Processing-Ms:   2.40
```

---

## Error Codes

| Code | HTTP | Meaning |
|---|---|---|
| `ADM_AUTH_001` | 401 | Missing API key |
| `ADM_AUTH_002` | 401 | Invalid or revoked API key |
| `ADM_AUTH_003` | 403 | Invalid admin key |
| `ADM_VAL_001` | 422 | Request body validation failed |
| `ADM_RATE_001` | 429 | API key daily limit exceeded |
| `ADM_RATE_002` | 429 | Playground IP rate limit exceeded |
| `ADM_SRV_001` | 500 | Unexpected server error |
| `ADM_ADMIN_001` | 404 | Key not found (admin routes) |

---

## Running in Production

### Docker (recommended)

```bash
# Build
docker build -t adm-api:latest .

# Run with 4 workers
docker run -p 8080:8080 \
  -e ADM_ADMIN_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))") \
  -v $(pwd)/data:/app/data \
  adm-api:latest
```

### Docker Compose

```bash
# Generate a strong admin key first
export ADM_ADMIN_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
docker compose up --build -d
```

### Direct (development)

```bash
cd artifacts/api-server
uvicorn adm_api.main:app --host 0.0.0.0 --port 8080 --reload
```

### Environment variables

| Variable | Default | Description |
|---|---|---|
| `BASE_PATH` | `/api` | URL prefix — must match proxy route |
| `ADM_ADMIN_KEY` | `adm_admin_dev_insecure_default` | Admin API key (**change in production**) |
| `WORKERS` | `4` | Gunicorn worker count |
| `PORT` | `8080` | Bind port |
| `LOG_LEVEL` | `info` | Gunicorn log level |

---

## Scaling Model

### Single node (current)

The default deployment runs 4 Gunicorn UvicornWorker processes sharing a single JSON-backed key store. This is suitable for:

- Up to ~4 000 authenticated requests/minute (assuming <100ms avg latency)
- Up to ~100 concurrent WebSocket sessions per worker

**Limitation:** WebSocket session state is in-process — sessions are not shared across workers.

### Multi-node (Redis path)

To scale horizontally, replace two components:

**1. Key store → Redis**

```python
# adm_api/auth/api_keys.py
# Replace APIKeyStore._load() / _flush() / check_and_record()
# with a Redis HASH + INCR pipeline using redis-py:
import redis
r = redis.Redis.from_url(os.environ["REDIS_URL"])
```

**2. WebSocket session state → Redis pub/sub**

```python
# adm_api/api/routes.py  _sessions dict
# Replace in-process defaultdict(list) with:
#   r.rpush(f"session:{session_id}", event.model_dump_json())
#   r.lrange(f"session:{session_id}", 0, -1)
```

With these two changes, ADM-API becomes fully stateless and can run behind any load balancer (AWS ALB, NGINX, Cloudflare) with unlimited horizontal scale.

### Latency profile

| Scenario | Typical latency |
|---|---|
| 1 event, no actors/tags | ~0.3ms |
| 5 events, mixed types | ~1–2ms |
| 20 events, all with actors | ~3–5ms |
| WebSocket event (cumulative 50) | ~8–12ms |

All measurements at single-core baseline. The pipeline is CPU-bound and parallelizes linearly with worker count.

---

## Testing

```bash
cd artifacts/api-server
python -m pytest tests/ -v
```

The test suite verifies:
- Byte-identical output on 100 repeated pipeline calls
- Hash-stable consequence selection per event ID
- Tension curve determinism across all 7 event types
- Simulation determinism with different session IDs
- Edge cases: zero intensity, max intensity, 50+ events, no actors, no tags

---

## SDK

| Language | Path | Notes |
|---|---|---|
| Python | `sdk/python/adm_client.py` | stdlib only + `websockets` for WS; retry + timeout support |
| JavaScript (ESM) | `sdk/js/adm_client.js` | Node 18+ / modern browsers; WS reconnect logic included |

See `sdk/QUICKSTART.md` for full usage examples.

---

## License

ADM-API is infrastructure software. See LICENSE for terms.
