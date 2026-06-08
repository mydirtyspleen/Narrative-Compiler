// ADM-API — Unity Integration Demo
//
// Demonstrates real-world usage patterns:
//   1. Combat event on player dealing damage
//   2. Political event on faction territory capture
//   3. Real-time streaming on sustained engagement
//   4. World progression simulation at round end
//
// Setup:
//   - Attach this to a demo GameObject
//   - Wire up the ADMClient reference in Inspector
//   - Wire up UI Text references for narrative display

using System.Collections;
using System.Collections.Generic;
using UnityEngine;
using UnityEngine.UI;
using ADMAPI;

public class ADMDemo : MonoBehaviour
{
    // ── Inspector references ───────────────────────────────────────────────────

    [Header("ADM-API Client")]
    public ADMClient admClient;

    [Header("UI (optional — log to console if null)")]
    public Text sceneSummaryText;
    public Text consequencesText;
    public Text characterFocusText;
    public Slider[] tensionSliders;     // one per tension value, or leave empty

    // ── Session state ─────────────────────────────────────────────────────────

    private string _sessionId;
    private readonly List<GameEvent> _pendingEvents = new();

    // ── Lifecycle ─────────────────────────────────────────────────────────────

    private void Start()
    {
        _sessionId = $"unity-session-{SystemInfo.deviceUniqueIdentifier[..8]}";

        admClient.OnNarrativeStateReceived += DisplayNarrativeState;
        admClient.OnStreamUpdateReceived   += DisplayStreamUpdate;
        admClient.OnError                  += (status, err) =>
            Debug.LogError($"[ADM Demo] API error {status}: {err.message}");

        Debug.Log($"[ADM Demo] Session: {_sessionId}");
    }

    // ======================================================================
    // Pattern 1: Batch render on significant game moment
    // ======================================================================

    /// <summary>
    /// Call this at the end of a combat phase or on a significant world event.
    /// Collects pending events and renders the full narrative state.
    /// </summary>
    public void OnCombatPhaseEnd()
    {
        if (_pendingEvents.Count == 0)
        {
            Debug.Log("[ADM Demo] No pending events to render.");
            return;
        }

        var events = _pendingEvents.ToArray();
        _pendingEvents.Clear();

        StartCoroutine(admClient.RenderAsync(
            sessionId: _sessionId,
            events:    events,
            onSuccess: (state) =>
            {
                Debug.Log($"[ADM] Scene: {state.scene_summary}");
                Debug.Log($"[ADM] Tension: [{string.Join(", ", state.tension_curve)}]");
                foreach (var c in state.narrative_consequences)
                    Debug.Log($"[ADM] → {c}");

                // Pass llm_prompt to your AI narrative enrichment layer if desired
                // e.g. openAIClient.Complete(state.llm_prompt);
            }
        ));
    }

    // ======================================================================
    // Pattern 2: Queue events as they happen during a game tick
    // ======================================================================

    /// <summary>
    /// Call this whenever a significant game event occurs.
    /// Events accumulate and are rendered at phase end or on demand.
    ///
    /// Example: call from your combat system when a player attacks.
    /// </summary>
    public void RecordCombatEvent(
        string   eventId,
        string[] attackers,
        string[] defenders,
        float    intensity)
    {
        _pendingEvents.Add(new GameEvent
        {
            id        = eventId,
            type      = EventType.combat.ToString(),
            intensity = Mathf.Clamp01(intensity),
            actors    = attackers,
            tags      = new[] { "combat", intensity >= 0.7f ? "war" : "skirmish" },
        });
        Debug.Log($"[ADM Demo] Queued combat event: {eventId} (intensity: {intensity:F2})");
    }

    /// <summary>
    /// Call when a faction captures territory or issues a policy change.
    /// </summary>
    public void RecordPoliticalEvent(
        string factionName,
        float  impactLevel)
    {
        _pendingEvents.Add(new GameEvent
        {
            id        = $"pol-{Time.frameCount}",
            type      = EventType.politics.ToString(),
            intensity = Mathf.Clamp01(impactLevel),
            actors    = new[] { factionName },
            tags      = new[] { "territory", impactLevel >= 0.6f ? "crisis" : "shift" },
        });
    }

    // ======================================================================
    // Pattern 3: World progression at round end
    // ======================================================================

    /// <summary>
    /// At round end, simulate next N steps to give the GM/director
    /// a projected world trajectory for narration purposes.
    /// </summary>
    public void SimulateNextRound(int steps = 3)
    {
        if (_pendingEvents.Count == 0) return;

        StartCoroutine(admClient.SimulateAsync(
            sessionId:    _sessionId,
            currentEvents: _pendingEvents.ToArray(),
            steps:        steps,
            onSuccess:    (sim) =>
            {
                Debug.Log($"[ADM] Trajectory: {sim.world_trajectory}");
                Debug.Log($"[ADM] Dominant force: {sim.dominant_force}");
                Debug.Log($"[ADM] Simulated {sim.simulated_events.Length} future events");

                foreach (var evt in sim.simulated_events)
                    Debug.Log($"  Step {evt.step}: [{evt.type}] intensity={evt.intensity:F2} — {evt.rationale}");
            }
        ));
    }

    // ======================================================================
    // Demo: Fabricate a test scenario (Editor / QA use)
    // ======================================================================

    [ContextMenu("Run Demo Scenario")]
    public void RunDemoScenario()
    {
        _pendingEvents.Clear();
        _pendingEvents.Add(new GameEvent
        {
            id        = "demo-combat-01",
            type      = EventType.combat.ToString(),
            intensity = 0.88f,
            actors    = new[] { "Iron Pact", "Northern Legion" },
            tags      = new[] { "war", "conflict" },
        });
        _pendingEvents.Add(new GameEvent
        {
            id        = "demo-politics-01",
            type      = EventType.politics.ToString(),
            intensity = 0.65f,
            actors    = new[] { "faction:Council" },
            tags      = new[] { "crisis" },
        });
        _pendingEvents.Add(new GameEvent
        {
            id        = "demo-ecology-01",
            type      = EventType.ecology.ToString(),
            intensity = 0.40f,
            actors    = new[] { "region:Tundra" },
            tags      = new[] { "drought" },
        });

        OnCombatPhaseEnd();
    }

    // ======================================================================
    // Display helpers
    // ======================================================================

    private void DisplayNarrativeState(NarrativeState state)
    {
        if (sceneSummaryText) sceneSummaryText.text = state.scene_summary;
        if (characterFocusText) characterFocusText.text = state.character_focus ?? "—";

        if (consequencesText)
        {
            var sb = new System.Text.StringBuilder();
            foreach (var c in state.narrative_consequences)
                sb.AppendLine($"• {c}");
            consequencesText.text = sb.ToString();
        }

        if (tensionSliders != null)
        {
            for (int i = 0; i < tensionSliders.Length && i < state.tension_curve.Length; i++)
                tensionSliders[i].value = state.tension_curve[i];
        }
    }

    private void DisplayStreamUpdate(StreamUpdate update)
    {
        if (sceneSummaryText) sceneSummaryText.text = $"[LIVE] {update.scene_summary}";
        Debug.Log($"[ADM Stream] Events: {update.event_count} | {update.scene_summary}");
    }
}
