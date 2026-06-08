"""
metrics — in-process metrics collector for ADM-API.

Thread-safe counters and histograms backed by plain Python data structures.
For production multi-node deployments, replace with a Prometheus client or
push metrics to a time-series store (InfluxDB, Datadog, etc.).

Exposed via GET /v1/metrics (no auth required — mount behind internal network
in production, or add auth if the endpoint must be public-facing).

Metric definitions:
  total_requests           — total HTTP requests processed since boot
  requests_by_endpoint     — {endpoint_label: count}
  active_ws_sessions       — gauge of live WebSocket connections
  latency_samples_ms       — list of all latency samples (capped at 10 000)
  avg_latency_ms           — mean of latency_samples_ms
  p95_latency_ms           — 95th-percentile of latency_samples_ms
  rate_limit_violations    — count of 429 responses issued
  api_key_counts           — {tier: count} — read from key_store on snapshot
  uptime_seconds           — seconds since MetricsCollector was created
"""

from __future__ import annotations

import time
from collections import defaultdict
from threading import Lock
from typing import Any


_MAX_LATENCY_SAMPLES = 10_000


class MetricsCollector:
    """
    Singleton metrics store.

    All mutation methods are thread-safe (Lock).
    snapshot() is safe to call without lock — worst case it sees a slightly
    stale count, which is acceptable for a metrics endpoint.
    """

    def __init__(self) -> None:
        self._lock                  = Lock()
        self._start_time: float     = time.monotonic()
        self._total_requests: int   = 0
        self._by_endpoint: dict[str, int] = defaultdict(int)
        self._active_ws: int        = 0
        self._latency_ms: list[float] = []
        self._rate_limit_violations: int = 0

    # ── Mutation helpers ──────────────────────────────────────────────────────

    def record_request(self, endpoint: str, latency_ms: float) -> None:
        """Called after every HTTP request completes."""
        with self._lock:
            self._total_requests += 1
            self._by_endpoint[endpoint] += 1
            if len(self._latency_ms) < _MAX_LATENCY_SAMPLES:
                self._latency_ms.append(latency_ms)

    def record_ws_connect(self) -> None:
        with self._lock:
            self._active_ws += 1

    def record_ws_disconnect(self) -> None:
        with self._lock:
            self._active_ws = max(0, self._active_ws - 1)

    def record_rate_limit_violation(self) -> None:
        with self._lock:
            self._rate_limit_violations += 1

    # ── Snapshot ─────────────────────────────────────────────────────────────

    def snapshot(self, api_key_counts: dict[str, int] | None = None) -> dict[str, Any]:
        """
        Return a point-in-time snapshot of all metrics.

        Parameters
        ----------
        api_key_counts : optional dict returned by key_store, e.g.
                         {"test": 1, "live": 3}.  Pass None to omit the field.
        """
        samples = list(self._latency_ms)

        if samples:
            avg = round(sum(samples) / len(samples), 3)
            sorted_samples = sorted(samples)
            idx_95 = max(0, int(len(sorted_samples) * 0.95) - 1)
            p95 = round(sorted_samples[idx_95], 3)
        else:
            avg = 0.0
            p95 = 0.0

        result: dict[str, Any] = {
            "total_requests":        self._total_requests,
            "requests_by_endpoint":  dict(self._by_endpoint),
            "active_ws_sessions":    self._active_ws,
            "avg_latency_ms":        avg,
            "p95_latency_ms":        p95,
            "sample_count":          len(samples),
            "rate_limit_violations": self._rate_limit_violations,
            "uptime_seconds":        round(time.monotonic() - self._start_time, 1),
        }

        if api_key_counts is not None:
            result["api_key_counts"] = api_key_counts

        return result


# ── Module-level singleton ─────────────────────────────────────────────────

metrics = MetricsCollector()
