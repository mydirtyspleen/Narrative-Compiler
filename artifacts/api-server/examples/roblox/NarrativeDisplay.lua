--[[
  ADM-API — Roblox Narrative Display Script
  
  Demonstrates a complete game integration:
    1. Recording events as they happen in-game
    2. Rendering narrative at phase end
    3. Displaying results in a ScreenGui
    4. Running world simulation to project future events
    5. Handling errors gracefully

  Place as a LocalScript or Script depending on your architecture.
  Wire up the GUI references at the top of the script.
--]]

local ReplicatedStorage = game:GetService("ReplicatedStorage")
local Players           = game:GetService("Players")
local RunService        = game:GetService("RunService")

-- ── Load ADMClient ────────────────────────────────────────────────────────────
-- Adjust path to wherever you placed ADMClient.lua
local ADMClient = require(ReplicatedStorage:WaitForChild("ADMClient"))

-- ── Configuration ─────────────────────────────────────────────────────────────

local CONFIG = {
    API_KEY    = "adm_live_...",  -- Replace with your key
    BASE_URL   = "https://your-host.replit.app/api",
    SESSION_ID = "roblox-" .. tostring(math.random(100000, 999999)),
}

-- ── Initialize client ─────────────────────────────────────────────────────────

local adm = ADMClient.new(CONFIG.API_KEY, CONFIG.BASE_URL, {
    maxRetries = 2,
    retryDelay = 0.5,
})

print("[ADM] Session:", CONFIG.SESSION_ID)

-- ── Event accumulator ─────────────────────────────────────────────────────────

local pendingEvents    = {}
local eventIdCounter   = 0

local function nextEventId(prefix)
    eventIdCounter += 1
    return string.format("%s-%04d", prefix, eventIdCounter)
end

-- ── Event recording helpers ────────────────────────────────────────────────────

--- Record a combat event when players fight
local function recordCombat(attackerName, defenderName, damage)
    -- Normalize damage to [0, 1] assuming max meaningful damage = 100
    local intensity = math.clamp(damage / 100, 0.1, 1.0)
    local event = ADMClient.buildEvent(
        nextEventId("combat"),
        "combat",
        intensity,
        { attackerName, defenderName },
        { intensity >= 0.7 and "war" or "skirmish", "pvp" }
    )
    table.insert(pendingEvents, event)
    print(string.format("[ADM] Recorded combat: %s vs %s (intensity=%.2f)", attackerName, defenderName, intensity))
end

--- Record a territory capture as a political event
local function recordTerritoryCapture(factionName, territoryName, importance)
    local event = ADMClient.buildEvent(
        nextEventId("politics"),
        "politics",
        math.clamp(importance, 0, 1),
        { factionName },
        { "territory", "capture", importance >= 0.6 and "crisis" or "shift" }
    )
    table.insert(pendingEvents, event)
    print(string.format("[ADM] Recorded territory capture: %s → %s", factionName, territoryName))
end

--- Record a resource event (mining, harvesting, depletion)
local function recordResourceEvent(regionName, depletion)
    local event = ADMClient.buildEvent(
        nextEventId("ecology"),
        "ecology",
        math.clamp(depletion, 0, 1),
        { "region:" .. regionName },
        { depletion >= 0.6 and "drought" or "stress", "resources" }
    )
    table.insert(pendingEvents, event)
end

-- ── Narrative display ─────────────────────────────────────────────────────────

--- Display narrative state in a ScreenGui
-- Replace with your own GUI references
local function displayNarrativeState(state)
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  NARRATIVE STATE")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("Scene:", state.scene_summary)
    print("")
    print("Character Focus:", state.character_focus or "—")
    print("")

    -- Tension curve as ASCII bar chart
    print("Tension Curve:")
    for i, t in ipairs(state.tension_curve) do
        local bars = math.floor(t * 20)
        local bar  = string.rep("█", bars) .. string.rep("░", 20 - bars)
        print(string.format("  [%d] %s %.2f", i, bar, t))
    end
    print("")

    print("Consequences:")
    for _, c in ipairs(state.narrative_consequences) do
        print("  →", c)
    end
    print("")

    print("Suggested Next Events:")
    for _, s in ipairs(state.suggested_next_events) do
        print(string.format("  ▸ [%s] %.2f — %s", s.type, s.intensity, s.description))
    end

    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")

    -- If you have a ScreenGui, update it here:
    -- local player = Players.LocalPlayer
    -- local gui    = player.PlayerGui:FindFirstChild("NarrativeGui")
    -- if gui then
    --     gui.SceneSummary.Text    = state.scene_summary
    --     gui.CharacterFocus.Text  = state.character_focus or "—"
    -- end
end

--- Display world simulation results
local function displaySimulation(sim)
    print("\n━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("  WORLD PROJECTION")
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    print("Trajectory:    ", sim.world_trajectory)
    print("Dominant Force:", sim.dominant_force)
    print("")
    print("Projected Events:")
    for _, evt in ipairs(sim.simulated_events) do
        print(string.format("  Step %d [%s] %.2f — %s",
            evt.step, evt.type, evt.intensity, evt.rationale))
    end
    print("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n")
end

-- ── Phase-end render ──────────────────────────────────────────────────────────

--- Call at the end of a combat round or significant phase.
--- Renders current events and optionally projects future steps.
local function renderPhaseEnd(simulateSteps)
    if #pendingEvents == 0 then
        print("[ADM] No events to render.")
        return
    end

    local eventsToRender = pendingEvents
    pendingEvents = {}  -- clear before async call

    -- Render narrative
    local ok, result = pcall(function()
        return adm:render(CONFIG.SESSION_ID, eventsToRender)
    end)

    if ok then
        displayNarrativeState(result)
    else
        warn("[ADM] Render failed:", tostring(result))
        return
    end

    -- Optionally project future steps
    if simulateSteps and simulateSteps > 0 then
        task.wait(0.1)  -- small delay between requests
        local simOk, sim = pcall(function()
            return adm:simulate(CONFIG.SESSION_ID, eventsToRender, simulateSteps)
        end)
        if simOk then
            displaySimulation(sim)
        else
            warn("[ADM] Simulate failed:", tostring(sim))
        end
    end
end

-- ── Demo scenario ─────────────────────────────────────────────────────────────
-- Run this to verify the integration is working

local function runDemoScenario()
    print("[ADM] Running demo scenario...")

    -- Simulate a few in-game events
    recordCombat("player:Axel_Thunder", "faction:Shadow_Guard",  85)  -- high damage
    recordCombat("player:MiraBlade",    "faction:Shadow_Guard",  42)  -- medium
    recordTerritoryCapture("faction:Iron_Pact", "Northwatch_Citadel", 0.7)
    recordResourceEvent("region:Tundra", 0.55)

    -- Render at phase end, project 3 steps ahead
    task.spawn(function()
        task.wait(0.5)
        renderPhaseEnd(3)
    end)
end

-- ── Wire up game events ───────────────────────────────────────────────────────
-- Example connections — replace with your actual game event signals

-- game.Players.PlayerAdded:Connect(function(player)
--     player.CharacterAdded:Connect(function(character)
--         local humanoid = character:WaitForChild("Humanoid")
--         humanoid.HealthChanged:Connect(function(health)
--             local damage = humanoid.MaxHealth - health
--             if damage > 10 then
--                 recordCombat(player.Name, "environment", damage)
--             end
--         end)
--     end)
-- end)

-- Example: render every 60 seconds of gameplay
-- task.spawn(function()
--     while true do
--         task.wait(60)
--         renderPhaseEnd(2)
--     end
-- end)

-- ── Run the demo ──────────────────────────────────────────────────────────────

task.spawn(runDemoScenario)
