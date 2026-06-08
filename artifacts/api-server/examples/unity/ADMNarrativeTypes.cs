// ADM-API — C# Type Definitions for Unity
// Matches the ADM-API v1 JSON schema exactly.
// Drop both files into your Unity Assets/ADM/ folder.
//
// Serialization: JsonUtility (no external deps) OR Newtonsoft.Json
// — both work; swap [JsonProperty] annotations if using Newtonsoft.

using System;
using System.Collections.Generic;

namespace ADMAPI
{
    // ── Event types ────────────────────────────────────────────────────────────

    public enum EventType
    {
        combat,
        politics,
        economy,
        ecology,
        social,
        weather,
        exploration
    }

    // ── Request: POST /v1/render ───────────────────────────────────────────────

    [Serializable]
    public class GameEvent
    {
        public string id;
        public string type;           // EventType.ToString()
        public float  intensity;      // [0.0, 1.0]
        public string[] actors;
        public string[] tags;
        // payload: omit or send as serialized JSON string if needed
    }

    [Serializable]
    public class RenderRequest
    {
        public string      session_id;
        public GameEvent[] events;
        // world_state: omit for default empty object
    }

    // ── Response: POST /v1/render → NarrativeState ────────────────────────────

    [Serializable]
    public class SuggestedNextEvent
    {
        public string type;
        public float  intensity;
        public string description;
    }

    [Serializable]
    public class RenderMetadata
    {
        public float  avg_intensity;
        public string dominant_category;
        public int    event_count;
    }

    [Serializable]
    public class NarrativeState
    {
        public string               scene_summary;
        public string               cinematic_description;
        public string               character_focus;
        public float[]              tension_curve;
        public string[]             narrative_consequences;
        public SuggestedNextEvent[] suggested_next_events;
        public string               llm_prompt;
        public RenderMetadata       metadata;
    }

    // ── WebSocket: StreamUpdate ────────────────────────────────────────────────

    [Serializable]
    public class StreamUpdate
    {
        public string   session_id;
        public string   scene_summary;
        public float[]  tension_curve;
        public string[] narrative_consequences;
        public int      event_count;
    }

    // ── Request: POST /v1/simulate ────────────────────────────────────────────

    [Serializable]
    public class SimulateRequest
    {
        public string      session_id;
        public GameEvent[] current_events;
        public int         steps;          // 1-10
    }

    [Serializable]
    public class SimulatedEvent
    {
        public string   id;
        public string   type;
        public float    intensity;
        public string[] actors;
        public string[] tags;
        public int      step;
        public string   rationale;
    }

    [Serializable]
    public class SimulateResponse
    {
        public string          session_id;
        public SimulatedEvent[] simulated_events;
        public float[]         projected_tension;
        public string          world_trajectory;
        public string          dominant_force;
    }

    // ── Error envelope ────────────────────────────────────────────────────────

    [Serializable]
    public class ADMErrorResponse
    {
        public string error;
        public string message;
        public string code;
        public string docs;
    }
}
