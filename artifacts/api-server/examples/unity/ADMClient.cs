// ADM-API — Unity C# Client v1
//
// Coroutine-based HTTP client + NativeWebSocket streaming.
// Drop into Assets/ADM/ADMClient.cs
//
// Dependencies:
//   HTTP:      UnityWebRequest (built-in)
//   WebSocket: NativeWebSocket (https://github.com/endel/NativeWebSocket)
//              OR replace ADMStreamClient with your preferred WS library.
//
// Setup:
//   1. Attach ADMClient component to a persistent GameObject (e.g. GameManager).
//   2. Set ApiKey and BaseUrl in the Inspector.
//   3. Call RenderAsync() from any MonoBehaviour.

using System;
using System.Collections;
using System.Text;
using UnityEngine;
using UnityEngine.Networking;

#if UNITY_WEBGL && !UNITY_EDITOR
using NativeWebSocket;
#endif

namespace ADMAPI
{
    public class ADMClient : MonoBehaviour
    {
        // ── Inspector fields ───────────────────────────────────────────────────

        [Header("ADM-API Configuration")]
        [Tooltip("Your ADM API key (adm_live_... or adm_test_...)")]
        public string ApiKey = "adm_test_...";

        [Tooltip("Base URL of your ADM-API deployment")]
        public string BaseUrl = "https://your-host.replit.app/api";

        [Tooltip("Request timeout in seconds")]
        public int TimeoutSeconds = 10;

        // ── Events ─────────────────────────────────────────────────────────────

        /// <summary>Fired when a render response is received.</summary>
        public event Action<NarrativeState> OnNarrativeStateReceived;

        /// <summary>Fired when a WebSocket stream update is received.</summary>
        public event Action<StreamUpdate> OnStreamUpdateReceived;

        /// <summary>Fired on any API error (auth, rate-limit, server error).</summary>
        public event Action<int, ADMErrorResponse> OnError;

        // ── Internal ──────────────────────────────────────────────────────────

        private string _wsUrl;

#if UNITY_WEBGL && !UNITY_EDITOR
        private WebSocket _ws;
#endif

        private void Awake()
        {
            _wsUrl = BaseUrl
                .Replace("https://", "wss://")
                .Replace("http://",  "ws://")
                .TrimEnd('/');
        }

        // ======================================================================
        // POST /v1/render
        // ======================================================================

        /// <summary>
        /// Convert a batch of game events into a full NarrativeState.
        /// Attach to a UI button or call from game logic on significant events.
        ///
        /// Usage:
        ///   StartCoroutine(admClient.RenderAsync(
        ///       sessionId: "room-001",
        ///       events:    new GameEvent[] { combatEvent, politicsEvent },
        ///       onSuccess: (state) => narrativeText.text = state.scene_summary
        ///   ));
        /// </summary>
        public IEnumerator RenderAsync(
            string          sessionId,
            GameEvent[]     events,
            Action<NarrativeState> onSuccess = null,
            Action<int, ADMErrorResponse> onError = null)
        {
            var body = new RenderRequest
            {
                session_id = sessionId,
                events     = events,
            };

            yield return PostJson(
                "/v1/render",
                JsonUtility.ToJson(body),
                (json) =>
                {
                    var state = JsonUtility.FromJson<NarrativeState>(json);
                    OnNarrativeStateReceived?.Invoke(state);
                    onSuccess?.Invoke(state);
                },
                onError
            );
        }

        // ======================================================================
        // POST /v1/simulate
        // ======================================================================

        /// <summary>
        /// Generate deterministic cascading future events from current world state.
        /// Same input + same session_id always produces the same simulated timeline.
        /// </summary>
        public IEnumerator SimulateAsync(
            string          sessionId,
            GameEvent[]     currentEvents,
            int             steps     = 3,
            Action<SimulateResponse> onSuccess = null,
            Action<int, ADMErrorResponse> onError = null)
        {
            var body = new SimulateRequest
            {
                session_id     = sessionId,
                current_events = currentEvents,
                steps          = steps,
            };

            yield return PostJson(
                "/v1/simulate",
                JsonUtility.ToJson(body),
                (json) =>
                {
                    var response = JsonUtility.FromJson<SimulateResponse>(json);
                    onSuccess?.Invoke(response);
                },
                onError
            );
        }

        // ======================================================================
        // WS /v1/stream — real-time incremental narrative updates
        // ======================================================================

#if UNITY_WEBGL && !UNITY_EDITOR
        /// <summary>
        /// Connect to the ADM-API WebSocket stream.
        /// Call SendStreamEvent() after connecting to push events.
        /// Subscribe to OnStreamUpdateReceived to receive narrative updates.
        /// </summary>
        public async void ConnectStream()
        {
            var url = $"{_wsUrl}/v1/stream?api_key={Uri.EscapeDataString(ApiKey)}";
            _ws     = new WebSocket(url);

            _ws.OnOpen    += () => Debug.Log("[ADM] WebSocket connected");
            _ws.OnClose   += (code) => Debug.Log($"[ADM] WebSocket closed: {code}");
            _ws.OnError   += (err) => Debug.LogError($"[ADM] WebSocket error: {err}");
            _ws.OnMessage += (data) =>
            {
                var json = Encoding.UTF8.GetString(data);
                // Control frame?
                if (json.Contains("\"action\""))
                {
                    Debug.Log($"[ADM] Control frame: {json}");
                    return;
                }
                var update = JsonUtility.FromJson<StreamUpdate>(json);
                OnStreamUpdateReceived?.Invoke(update);
            };

            await _ws.Connect();
        }

        /// <summary>Send one event to the stream and receive a narrative update via OnStreamUpdateReceived.</summary>
        public async void SendStreamEvent(string sessionId, GameEvent evt)
        {
            if (_ws == null || _ws.State != WebSocketState.Open)
            {
                Debug.LogWarning("[ADM] WebSocket not connected. Call ConnectStream() first.");
                return;
            }

            var envelope = $"{{\"session_id\":\"{sessionId}\",\"event\":{JsonUtility.ToJson(evt)},\"world_state\":{{}}}}";
            await _ws.SendText(envelope);
        }

        public async void DisconnectStream(string sessionId = null)
        {
            if (_ws == null) return;
            var close = sessionId != null
                ? $"{{\"action\":\"close\",\"session_id\":\"{sessionId}\"}}"
                : "{\"action\":\"close\"}";
            await _ws.SendText(close);
            await _ws.Close();
        }

        private void Update()
        {
            // NativeWebSocket requires DispatchMessageQueue() in Update for non-WebGL builds
#if !UNITY_WEBGL || UNITY_EDITOR
            _ws?.DispatchMessageQueue();
#endif
        }
#endif

        // ======================================================================
        // Internal HTTP helpers
        // ======================================================================

        private IEnumerator PostJson(
            string   path,
            string   bodyJson,
            Action<string>                    onSuccess,
            Action<int, ADMErrorResponse>     onError)
        {
            var url  = BaseUrl.TrimEnd('/') + path;
            var data = Encoding.UTF8.GetBytes(bodyJson);

            using var req = new UnityWebRequest(url, "POST")
            {
                uploadHandler   = new UploadHandlerRaw(data),
                downloadHandler = new DownloadHandlerBuffer(),
                timeout         = TimeoutSeconds,
            };
            req.SetRequestHeader("Content-Type", "application/json");
            req.SetRequestHeader("Accept",       "application/json");
            req.SetRequestHeader("X-API-Key",    ApiKey);
            req.SetRequestHeader("User-Agent",   "adm-unity-client/1.0");

            yield return req.SendWebRequest();

            if (req.result == UnityWebRequest.Result.Success)
            {
                onSuccess?.Invoke(req.downloadHandler.text);
            }
            else
            {
                var status = (int)req.responseCode;
                ADMErrorResponse errBody = null;
                try
                {
                    errBody = JsonUtility.FromJson<ADMErrorResponse>(req.downloadHandler.text);
                }
                catch
                {
                    errBody = new ADMErrorResponse
                    {
                        error   = "network_error",
                        message = req.error,
                        code    = "ADM_NET_001",
                    };
                }

                Debug.LogError($"[ADM] Error {status} [{errBody?.code}]: {errBody?.message}");
                OnError?.Invoke(status, errBody);
                onError?.Invoke(status, errBody);
            }
        }
    }
}
