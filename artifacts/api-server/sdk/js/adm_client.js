/**
 * ADM-API JavaScript Client — v2
 *
 * Fetch-based HTTP client + WebSocket streaming client for the
 * AI Dungeon Master Infrastructure API.
 * Works in Node.js (18+) and modern browsers. No external dependencies.
 *
 * What's new in v2:
 *   - Automatic retry with exponential backoff for 5xx / network errors
 *   - Named error code constants
 *   - ADMStreamClient: auto-reconnect on network drop, connection state,
 *     promise-based send/receive, structured event queue
 *   - JSDoc return types aligned with server schemas
 *
 * Usage (ESM):
 *   import { ADMClient, ADMStreamClient, ADMError } from "./adm_client.js";
 *
 *   const client = new ADMClient({
 *     apiKey:  "adm_live_...",
 *     baseUrl: "https://your-domain.replit.app/api",
 *   });
 *
 *   const result = await client.render("session-001", [
 *     { id: "e1", type: "combat", intensity: 0.85,
 *       actors: ["Northern Legion"], tags: ["war"], payload: {} }
 *   ]);
 *   console.log(result.scene_summary);
 *   console.log(result.tension_curve);
 */

// ── Error codes ────────────────────────────────────────────────────────────────

export const ADM_MISSING_KEY      = "ADM_AUTH_001";
export const ADM_INVALID_KEY      = "ADM_AUTH_002";
export const ADM_FORBIDDEN        = "ADM_AUTH_003";
export const ADM_VALIDATION_ERROR = "ADM_VAL_001";
export const ADM_RATE_LIMITED     = "ADM_RATE_001";
export const ADM_SERVER_ERROR     = "ADM_SRV_001";


// ── Error class ───────────────────────────────────────────────────────────────

export class ADMError extends Error {
  /**
   * @param {number} status  - HTTP status code (0 for network errors)
   * @param {object} body    - Parsed server error body
   */
  constructor(status, body) {
    super(`ADM-API error ${status} [${body.code ?? ""}]: ${body.error ?? "unknown"} — ${body.message ?? ""}`);
    this.name    = "ADMError";
    this.status  = status;
    this.code    = body.code ?? "";
    this.body    = body;
  }

  get isAuthError()       { return this.status === 401 || this.status === 403; }
  get isRateLimited()     { return this.status === 429; }
  get isServerError()     { return this.status >= 500; }
  get isValidationError() { return this.status === 422; }
  get isNetworkError()    { return this.status === 0; }
}


// ── Default retry config ───────────────────────────────────────────────────────

const RETRY_STATUS = new Set([500, 502, 503, 504]);
const CLIENT_VERSION = "2.0.0";


// ── HTTP client ───────────────────────────────────────────────────────────────

export class ADMClient {
  /**
   * @param {object} options
   * @param {string}  options.apiKey      - Your ADM API key (adm_test_... or adm_live_...)
   * @param {string}  [options.baseUrl]   - Base URL, e.g. "https://app.replit.app/api"
   * @param {number}  [options.timeoutMs] - Request timeout in milliseconds (default 10 000)
   * @param {number}  [options.maxRetries]  - Max retries for 5xx responses (default 3)
   * @param {number}  [options.retryDelayMs] - Base backoff delay in ms (default 500)
   */
  constructor({
    apiKey,
    baseUrl       = "http://localhost:80/api",
    timeoutMs     = 10_000,
    maxRetries    = 3,
    retryDelayMs  = 500,
  }) {
    this.apiKey       = apiKey;
    this.baseUrl      = baseUrl.replace(/\/$/, "");
    this.timeoutMs    = timeoutMs;
    this.maxRetries   = maxRetries;
    this.retryDelayMs = retryDelayMs;
  }

  // ── Internal ───────────────────────────────────────────────────────────────

  /**
   * @param {number} ms
   * @returns {Promise<void>}
   */
  static #sleep(ms) {
    return new Promise((r) => setTimeout(r, ms));
  }

  /**
   * Execute a request with automatic retry and exponential backoff.
   *
   * @param {string}  method   - HTTP method
   * @param {string}  path     - Endpoint path
   * @param {object}  [body]   - JSON request body
   * @param {object}  [opts]
   * @param {number}  [opts.retries] - Override maxRetries for this call
   * @returns {Promise<object>}
   */
  async #request(method, path, body, { retries } = {}) {
    const maxRetries = retries ?? this.maxRetries;
    const url        = `${this.baseUrl}${path}`;
    let lastError;

    for (let attempt = 0; attempt <= maxRetries; attempt++) {
      const controller = new AbortController();
      const timer      = setTimeout(() => controller.abort(), this.timeoutMs);

      try {
        const response = await fetch(url, {
          method,
          headers: {
            "X-API-Key":    this.apiKey,
            "Content-Type": "application/json",
            "Accept":       "application/json",
            "User-Agent":   `adm-js-client/${CLIENT_VERSION}`,
          },
          body:   body != null ? JSON.stringify(body) : undefined,
          signal: controller.signal,
        });

        const json = await response.json();

        if (!response.ok) {
          const err = new ADMError(response.status, json);

          // Never retry auth or validation errors
          if (response.status === 401 || response.status === 403 || response.status === 422) {
            throw err;
          }

          // Back off on rate limit or 5xx
          if ((response.status === 429 || RETRY_STATUS.has(response.status)) && attempt < maxRetries) {
            lastError = err;
            await ADMClient.#sleep(this.retryDelayMs * (2 ** attempt));
            continue;
          }

          throw err;
        }

        return json;

      } catch (e) {
        if (e instanceof ADMError) throw e;

        // Network / timeout error — wrap and retry
        const netErr = new ADMError(0, {
          error:   "network_error",
          message: e.message,
          code:    "ADM_NET_001",
        });

        if (attempt < maxRetries) {
          lastError = netErr;
          await ADMClient.#sleep(this.retryDelayMs * (2 ** attempt));
          continue;
        }

        throw netErr;

      } finally {
        clearTimeout(timer);
      }
    }

    throw lastError;
  }

  // ── Public API ─────────────────────────────────────────────────────────────

  /**
   * POST /v1/render
   *
   * Convert a batch of game events into a full deterministic NarrativeState.
   *
   * @param {string} sessionId
   * @param {Array<{id:string, type:string, intensity:number, actors:string[], tags:string[], payload:object}>} events
   * @param {object} [worldState={}]
   * @returns {Promise<{
   *   scene_summary: string,
   *   cinematic_description: string,
   *   character_focus: string|null,
   *   tension_curve: number[],
   *   narrative_consequences: string[],
   *   suggested_next_events: Array<{type:string, intensity:number, description:string}>,
   *   llm_prompt: string,
   *   metadata: {avg_intensity:number, dominant_category:string, event_count:number}
   * }>}
   */
  async render(sessionId, events, worldState = {}) {
    return this.#request("POST", "/v1/render", {
      session_id:  sessionId,
      events,
      world_state: worldState,
    });
  }

  /**
   * POST /v1/simulate
   *
   * Generate deterministic cascading future events.
   *
   * @param {string}  sessionId
   * @param {Array}   [currentEvents=[]]
   * @param {number}  [steps=3]          - Simulation steps 1–10
   * @param {object}  [worldState={}]
   * @returns {Promise<{
   *   session_id: string,
   *   simulated_events: Array,
   *   projected_tension: number[],
   *   world_trajectory: string,
   *   dominant_force: string
   * }>}
   */
  async simulate(sessionId, currentEvents = [], steps = 3, worldState = {}) {
    return this.#request("POST", "/v1/simulate", {
      session_id:     sessionId,
      current_events: currentEvents,
      steps,
      world_state:    worldState,
    });
  }

  /**
   * GET /v1/usage — Returns daily quota and usage breakdown.
   * Does NOT consume rate-limit quota.
   * @returns {Promise<object>}
   */
  async usage() {
    return this.#request("GET", "/v1/usage", undefined, { retries: 0 });
  }

  /**
   * POST /v1/playground/render
   *
   * Unauthenticated sandbox. Max 5 events. No API key needed
   * (the key in the client headers is ignored by this endpoint).
   *
   * @param {Array}  events      - 1–5 event objects
   * @param {string} [sessionId="playground"]
   * @param {object} [worldState={}]
   * @returns {Promise<object>} Same NarrativeState shape as render()
   */
  async playground(events, sessionId = "playground", worldState = {}) {
    return this.#request("POST", "/v1/playground/render", {
      session_id:  sessionId,
      events,
      world_state: worldState,
    });
  }
}


// ── WebSocket streaming client ─────────────────────────────────────────────────

export class ADMStreamClient {
  /**
   * Real-time incremental event streaming via WebSocket.
   *
   * Features:
   *   - Automatic reconnect on disconnect (configurable max)
   *   - Exponential backoff between reconnect attempts
   *   - Event queue: server pushes are buffered if no consumer is awaiting
   *   - connection state readable via .connected
   *
   * @param {object} options
   * @param {string} options.apiKey
   * @param {string} [options.baseUrl]         - e.g. "wss://app.replit.app/api"
   * @param {number} [options.maxReconnects=5]
   * @param {number} [options.reconnectDelayMs=1000]
   *
   * Usage (event loop / callback style):
   *   const stream = new ADMStreamClient({ apiKey: "adm_test_..." });
   *   await stream.connect();
   *
   *   stream.onUpdate = (update) => {
   *     console.log(update.scene_summary);
   *   };
   *
   *   await stream.sendEvent("session-001", {
   *     id: "e1", type: "combat", intensity: 0.8,
   *     actors: ["Legion"], tags: ["war"], payload: {}
   *   });
   *
   *   await stream.close();
   *
   * Usage (promise style with sendAndReceive):
   *   const update = await stream.sendAndReceive("session-001", event);
   *   console.log(update.scene_summary);
   */
  constructor({
    apiKey,
    baseUrl           = "ws://localhost:80/api",
    maxReconnects     = 5,
    reconnectDelayMs  = 1_000,
  }) {
    this.apiKey           = apiKey;
    this.baseUrl          = baseUrl
      .replace(/\/$/, "")
      .replace(/^http:/, "ws:")
      .replace(/^https:/, "wss:");
    this.maxReconnects    = maxReconnects;
    this.reconnectDelayMs = reconnectDelayMs;

    this._ws        = null;
    this._connected = false;
    this._reconnectCount = 0;

    // Message queue for push-style consumers
    /** @type {Array<object>} */
    this._queue     = [];
    /** @type {Array<Function>} */
    this._waiters   = [];

    /** @type {((update: object) => void) | null} */
    this.onUpdate   = null;
    /** @type {((error: object) => void) | null} */
    this.onError    = null;
    /** @type {(() => void) | null} */
    this.onReconnect = null;
  }

  /** @returns {boolean} True if the WebSocket is currently open. */
  get connected() { return this._connected; }

  /** @returns {number} Total successful reconnects since construction. */
  get reconnectCount() { return this._reconnectCount; }

  // ── Connection management ──────────────────────────────────────────────────

  async connect() {
    await this._doConnect();
    return this;
  }

  async _doConnect() {
    const url = `${this.baseUrl}/v1/stream?api_key=${encodeURIComponent(this.apiKey)}`;
    this._ws = new WebSocket(url);

    await new Promise((resolve, reject) => {
      this._ws.addEventListener("open", () => {
        this._connected = true;
        resolve();
      }, { once: true });
      this._ws.addEventListener("error", (e) => {
        reject(new ADMError(0, { error: "ws_connect_error", message: "WebSocket connection failed", code: "ADM_NET_002" }));
      }, { once: true });
    });

    // Message handler: route to queue/waiters or callback
    this._ws.addEventListener("message", (evt) => {
      let data;
      try {
        data = JSON.parse(evt.data);
      } catch (_) {
        return;
      }

      if (data.error) {
        if (this.onError) this.onError(data);
        // Reject any pending waiters
        const waiter = this._waiters.shift();
        if (waiter) waiter.reject(new ADMError(0, data));
        return;
      }

      // Control frame acks (reset_ack, closed) — resolve waiter if present
      if (data.action) {
        const waiter = this._waiters.shift();
        if (waiter) waiter.resolve(data);
        return;
      }

      // Narrative update
      if (this.onUpdate) {
        this.onUpdate(data);
      } else {
        // Queue for sendAndReceive consumers
        const waiter = this._waiters.shift();
        if (waiter) {
          waiter.resolve(data);
        } else {
          this._queue.push(data);
        }
      }
    });

    // Disconnect handler — attempt reconnect
    this._ws.addEventListener("close", async (evt) => {
      this._connected = false;
      // Don't reconnect on intentional close (code 1000) or auth close (4001)
      if (evt.code === 1000 || evt.code === 4001) return;

      for (let attempt = 0; attempt < this.maxReconnects; attempt++) {
        const delay = this.reconnectDelayMs * (2 ** attempt);
        await new Promise((r) => setTimeout(r, delay));
        try {
          await this._doConnect();
          this._reconnectCount++;
          if (this.onReconnect) this.onReconnect();
          return;
        } catch (_) {
          // continue trying
        }
      }
      // All reconnect attempts exhausted — reject all pending waiters
      const err = new ADMError(0, {
        error:   "ws_reconnect_failed",
        message: `WebSocket reconnect failed after ${this.maxReconnects} attempts.`,
        code:    "ADM_NET_003",
      });
      for (const waiter of this._waiters) waiter.reject(err);
      this._waiters = [];
    });
  }

  // ── Event sending ──────────────────────────────────────────────────────────

  /**
   * Send one game event. Server pushes back a StreamUpdate via onUpdate callback.
   * Use sendAndReceive() if you prefer a promise-based API.
   *
   * @param {string} sessionId
   * @param {{id:string, type:string, intensity:number, actors:string[], tags:string[], payload:object}} event
   * @param {object} [worldState={}]
   */
  async sendEvent(sessionId, event, worldState = {}) {
    if (!this._connected || !this._ws) {
      throw new ADMError(0, {
        error:   "not_connected",
        message: "WebSocket is not connected. Call connect() first.",
        code:    "ADM_NET_004",
      });
    }
    this._ws.send(JSON.stringify({
      session_id:  sessionId,
      event,
      world_state: worldState,
    }));
  }

  /**
   * Send one game event and await the server's StreamUpdate response.
   * This is the simplest integration pattern for request/response style clients.
   *
   * @param {string} sessionId
   * @param {object} event
   * @param {object} [worldState={}]
   * @param {number} [timeoutMs=10000] - Max wait for response
   * @returns {Promise<{session_id:string, scene_summary:string, tension_curve:number[], narrative_consequences:string[], event_count:number}>}
   */
  async sendAndReceive(sessionId, event, worldState = {}, timeoutMs = 10_000) {
    // Check queue first (already-buffered push)
    if (this._queue.length > 0) {
      const buffered = this._queue.shift();
      await this.sendEvent(sessionId, event, worldState);
      return buffered;
    }

    /** @type {Promise<object>} */
    const responsePromise = new Promise((resolve, reject) => {
      const timer = setTimeout(() => {
        const idx = this._waiters.findIndex((w) => w.resolve === resolve);
        if (idx !== -1) this._waiters.splice(idx, 1);
        reject(new ADMError(0, {
          error:   "timeout",
          message: `No response received within ${timeoutMs}ms.`,
          code:    "ADM_NET_005",
        }));
      }, timeoutMs);

      this._waiters.push({
        resolve: (v) => { clearTimeout(timer); resolve(v); },
        reject:  (e) => { clearTimeout(timer); reject(e); },
      });
    });

    await this.sendEvent(sessionId, event, worldState);
    return responsePromise;
  }

  /**
   * Clear server-side session history.
   * @param {string} sessionId
   */
  async resetSession(sessionId) {
    if (!this._ws || !this._connected) return;
    this._ws.send(JSON.stringify({ action: "reset", session_id: sessionId }));
  }

  async close() {
    if (this._ws && this._connected) {
      try {
        this._ws.send(JSON.stringify({ action: "close" }));
        await new Promise((r) => setTimeout(r, 100));
      } catch (_) {}
    }
    this._ws?.close(1000);
    this._connected = false;
    this._ws        = null;
    // Reject any pending waiters
    for (const w of this._waiters) {
      w.reject(new ADMError(0, { error: "closed", message: "Stream closed.", code: "ADM_NET_006" }));
    }
    this._waiters = [];
  }
}


// ── CLI smoke-test (Node.js only) ─────────────────────────────────────────────

const isMain =
  typeof process !== "undefined" &&
  process.argv[1] &&
  new URL(import.meta.url).pathname === process.argv[1];

if (isMain) {
  const apiKey  = process.argv[2] ?? "adm_test_e2f4a6b8c0d1e3f5a7b9c1d3e5f7000100000001";
  const baseUrl = process.argv[3] ?? "http://localhost:80/api";

  const client = new ADMClient({ apiKey, baseUrl });

  console.log("── render ───────────────────────────────");
  const result = await client.render("sdk-js-test", [
    { id: "t1", type: "combat",   intensity: 0.9,  actors: ["Alpha"],   tags: ["war"],    payload: {} },
    { id: "t2", type: "politics", intensity: 0.65, actors: ["Council"], tags: ["crisis"], payload: {} },
  ]);
  console.log("  scene_summary :", result.scene_summary);
  console.log("  tension_curve :", result.tension_curve);

  console.log("\n── playground (no auth) ─────────────────");
  try {
    const pg = await client.playground([
      { id: "pg1", type: "ecology", intensity: 0.5, actors: [], tags: [], payload: {} },
    ]);
    console.log("  scene_summary :", pg.scene_summary);
  } catch (e) {
    console.log("  playground error:", e.message);
  }

  console.log("\n── usage ────────────────────────────────");
  const u = await client.usage();
  console.log(`  requests_today : ${u.requests_today} / ${u.rate_limit}`);
  console.log(`  remaining      : ${u.remaining_today}`);
  console.log(`  by_endpoint    : ${JSON.stringify(u.requests_by_endpoint)}`);
}
