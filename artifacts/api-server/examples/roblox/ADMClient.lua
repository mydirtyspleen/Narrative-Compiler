--[[
  ADM-API — Roblox ModuleScript Client v1

  Place this as a ModuleScript in ServerScriptService or ReplicatedStorage.
  Require it from your game scripts:

    local ADMClient = require(script.Parent.ADMClient)
    local adm = ADMClient.new("adm_live_...", "https://your-host.replit.app/api")

    local result = adm:render("session-001", {
        { id = "e1", type = "combat", intensity = 0.85,
          actors = {"Iron Pact"}, tags = {"war"} }
    })
    print(result.scene_summary)

  Enable HTTP requests in Roblox:
    Game Settings → Security → Allow HTTP Requests = ON

  API Base URL:
    Use your deployed ADM-API domain, e.g. "https://your-name.replit.app/api"
    Do NOT use localhost — Roblox game servers run on Roblox infrastructure.
--]]

local HttpService = game:GetService("HttpService")

-- ── Error codes ──────────────────────────────────────────────────────────────

local ADMErrorCodes = {
    MISSING_KEY      = "ADM_AUTH_001",
    INVALID_KEY      = "ADM_AUTH_002",
    VALIDATION_ERROR = "ADM_VAL_001",
    RATE_LIMITED     = "ADM_RATE_001",
    SERVER_ERROR     = "ADM_SRV_001",
}

-- ── ADMError ─────────────────────────────────────────────────────────────────

local ADMError = {}
ADMError.__index = ADMError

function ADMError.new(statusCode, body)
    local self = setmetatable({}, ADMError)
    self.statusCode = statusCode
    self.code       = body.code or ""
    self.error      = body.error or "unknown"
    self.message    = body.message or ""
    self.body       = body
    return self
end

function ADMError:__tostring()
    return string.format("ADM-API error %d [%s]: %s — %s",
        self.statusCode, self.code, self.error, self.message)
end

function ADMError:isAuthError()
    return self.statusCode == 401 or self.statusCode == 403
end

function ADMError:isRateLimited()
    return self.statusCode == 429
end

function ADMError:isServerError()
    return self.statusCode >= 500
end

-- ── ADMClient ─────────────────────────────────────────────────────────────────

local ADMClient = {}
ADMClient.__index = ADMClient

--- Create a new ADM-API client.
-- @param apiKey  string  Your ADM API key (adm_test_... or adm_live_...)
-- @param baseUrl string  Base URL of the deployed API
-- @param options table   Optional: { maxRetries=3, retryDelay=0.5 }
function ADMClient.new(apiKey, baseUrl, options)
    assert(apiKey,   "[ADMClient] apiKey is required")
    assert(baseUrl,  "[ADMClient] baseUrl is required")

    local opts = options or {}
    local self = setmetatable({}, ADMClient)
    self.apiKey     = apiKey
    self.baseUrl    = baseUrl:gsub("/$", "")
    self.maxRetries = opts.maxRetries or 3
    self.retryDelay = opts.retryDelay or 0.5
    return self
end

-- ── Internal request helper ───────────────────────────────────────────────────

function ADMClient:_request(method, path, body)
    local url       = self.baseUrl .. path
    local bodyJson  = body and HttpService:JSONEncode(body) or nil
    local lastError = nil

    for attempt = 1, self.maxRetries + 1 do
        local ok, result = pcall(function()
            return HttpService:RequestAsync({
                Url     = url,
                Method  = method,
                Headers = {
                    ["X-API-Key"]    = self.apiKey,
                    ["Content-Type"] = "application/json",
                    ["Accept"]       = "application/json",
                    ["User-Agent"]   = "adm-roblox-client/1.0",
                },
                Body = bodyJson,
            })
        end)

        if not ok then
            -- HttpService network-level error
            lastError = {
                statusCode = 0,
                body = { error = "network_error", message = tostring(result), code = "ADM_NET_001" }
            }
            if attempt <= self.maxRetries then
                task.wait(self.retryDelay * (2 ^ (attempt - 1)))
            end
        else
            -- Parse response
            local parsed = nil
            local parseOk, parseErr = pcall(function()
                parsed = HttpService:JSONDecode(result.Body)
            end)
            if not parseOk then
                parsed = { error = "parse_error", message = result.Body, code = "" }
            end

            if result.Success then
                return parsed  -- success path
            else
                local err = ADMError.new(result.StatusCode, parsed)
                -- Never retry auth/validation
                if result.StatusCode == 401 or result.StatusCode == 403 or result.StatusCode == 422 then
                    error(err, 2)
                end
                -- Retry on 429 and 5xx
                if (result.StatusCode == 429 or result.StatusCode >= 500) and attempt <= self.maxRetries then
                    lastError = err
                    task.wait(self.retryDelay * (2 ^ (attempt - 1)))
                else
                    error(err, 2)
                end
            end
        end
    end

    error(lastError or ADMError.new(0, { error = "retry_exhausted", message = "Max retries exceeded", code = "ADM_NET_002" }), 2)
end

-- ── POST /v1/render ───────────────────────────────────────────────────────────

--- Render a batch of game events into a full NarrativeState.
-- @param sessionId string     Client-assigned session identifier
-- @param events    table      Array of event tables (see example below)
-- @param worldState table     Optional additional context (pass nil or {})
-- @return NarrativeState table
--
-- Event table shape:
--   { id="e1", type="combat", intensity=0.85,
--     actors={"Iron Pact"}, tags={"war","conflict"} }
--
-- Returns table with:
--   scene_summary, cinematic_description, character_focus,
--   tension_curve, narrative_consequences, suggested_next_events,
--   llm_prompt, metadata
function ADMClient:render(sessionId, events, worldState)
    assert(sessionId,          "[ADMClient] sessionId is required")
    assert(events and #events > 0, "[ADMClient] events must be a non-empty array")

    -- Normalize events: ensure payload field exists
    for _, evt in ipairs(events) do
        evt.actors  = evt.actors  or {}
        evt.tags    = evt.tags    or {}
        evt.payload = evt.payload or {}
    end

    return self:_request("POST", "/v1/render", {
        session_id  = sessionId,
        events      = events,
        world_state = worldState or {},
    })
end

-- ── POST /v1/simulate ─────────────────────────────────────────────────────────

--- Generate deterministic N-step world progression.
-- @param sessionId     string  Seeds the deterministic simulation
-- @param currentEvents table   Seed events (can be empty)
-- @param steps         number  Simulation steps 1-10 (default: 3)
-- @return SimulateResponse table
function ADMClient:simulate(sessionId, currentEvents, steps)
    assert(sessionId, "[ADMClient] sessionId is required")

    local evts = currentEvents or {}
    for _, evt in ipairs(evts) do
        evt.actors  = evt.actors  or {}
        evt.tags    = evt.tags    or {}
        evt.payload = evt.payload or {}
    end

    return self:_request("POST", "/v1/simulate", {
        session_id     = sessionId,
        current_events = evts,
        steps          = steps or 3,
        world_state    = {},
    })
end

-- ── GET /v1/usage ─────────────────────────────────────────────────────────────

--- Get usage statistics for the authenticated key.
-- Does NOT consume quota — safe to poll.
-- @return UsageResponse table
function ADMClient:usage()
    return self:_request("GET", "/v1/usage", nil)
end

-- ── POST /v1/playground/render (no auth) ──────────────────────────────────────

--- Quick test without an API key. Max 5 events. IP rate-limited.
-- @param events table  1-5 game event tables
-- @return NarrativeState table
function ADMClient:playground(events)
    assert(events and #events > 0, "[ADMClient] events required")
    assert(#events <= 5, "[ADMClient] playground is limited to 5 events")

    for _, evt in ipairs(events) do
        evt.actors  = evt.actors  or {}
        evt.tags    = evt.tags    or {}
        evt.payload = evt.payload or {}
    end

    -- Playground doesn't require API key — but we pass it anyway, it's harmless
    return self:_request("POST", "/v1/playground/render", {
        session_id = "roblox-playground",
        events     = events,
    })
end

-- ── Utility: build event table ────────────────────────────────────────────────

--- Helper to build a well-formed event table.
-- @param id        string  Unique event identifier
-- @param eventType string  "combat"|"politics"|"economy"|"ecology"|"social"|"weather"|"exploration"
-- @param intensity number  [0.0, 1.0]
-- @param actors    table   Optional array of actor name strings
-- @param tags      table   Optional array of tag strings
-- @return GameEvent table
function ADMClient.buildEvent(id, eventType, intensity, actors, tags)
    assert(id,        "[ADMClient] event id is required")
    assert(eventType, "[ADMClient] event type is required")
    assert(intensity >= 0 and intensity <= 1, "[ADMClient] intensity must be in [0,1]")

    return {
        id        = id,
        type      = eventType,
        intensity = math.clamp(intensity, 0, 1),
        actors    = actors  or {},
        tags      = tags    or {},
        payload   = {},
    }
end

return ADMClient
