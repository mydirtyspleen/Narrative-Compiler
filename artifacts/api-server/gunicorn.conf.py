"""
gunicorn.conf.py — Production server configuration for ADM-API.

Uses UvicornWorker (async ASGI workers) for full FastAPI/WebSocket support.

Environment overrides:
  WORKERS   — number of worker processes (default: 4)
  HOST      — bind host (default: 0.0.0.0)
  PORT      — bind port (default: 8080)
  LOG_LEVEL — gunicorn log level (default: info)
  TIMEOUT   — worker timeout seconds (default: 30)

References:
  https://docs.gunicorn.org/en/stable/configure.html
  https://www.uvicorn.org/deployment/#gunicorn
"""

from __future__ import annotations
import os

# ── Workers ───────────────────────────────────────────────────────────────────

# 4 workers handles ~400–800 concurrent requests (assuming <100ms avg latency).
# Scale up proportionally with CPU cores: (2 × cpu_count) + 1 is a common rule.
# NOTE: WebSocket session state is in-process — use 1 worker with Redis pub/sub
# for stateful multi-worker WebSocket deployments.
workers = int(os.environ.get("WORKERS", "4"))

# UvicornWorker: runs each Gunicorn worker as an asyncio event loop.
# Required for FastAPI (ASGI) and WebSocket support.
worker_class = "uvicorn.workers.UvicornWorker"

# ── Binding ───────────────────────────────────────────────────────────────────

host = os.environ.get("HOST", "0.0.0.0")
port = int(os.environ.get("PORT", "8080"))
bind = f"{host}:{port}"

# ── Timeouts ──────────────────────────────────────────────────────────────────

# Worker timeout: worker is killed and restarted if it doesn't respond in this
# many seconds. WebSocket workers hold long-lived connections — if you use
# WS heavily, raise this value or use a dedicated WS process.
timeout = int(os.environ.get("TIMEOUT", "30"))

# How long to wait for connections to close on graceful shutdown.
graceful_timeout = 20

# Keep-alive: seconds to wait for another request on an existing connection.
keepalive = 5

# ── Logging ───────────────────────────────────────────────────────────────────

# Gunicorn log level (debug, info, warning, error, critical).
loglevel = os.environ.get("LOG_LEVEL", "info")

# Route access and error logs to stdout — structured log aggregators pick
# these up via the container's stdout stream.
accesslog  = "-"
errorlog   = "-"

# Disable Gunicorn's default access log format — ADM-API emits structured
# JSON request logs via its own middleware (adm_api.observability.logger).
access_log_format = ""

# ── Performance ───────────────────────────────────────────────────────────────

# Max requests per worker before graceful restart (prevents memory bloat).
max_requests          = 10_000
max_requests_jitter   = 1_000

# ── Process naming ────────────────────────────────────────────────────────────

proc_name    = "adm-api"
default_proc_name = "adm-api"

# ── Security ──────────────────────────────────────────────────────────────────

# Forward IP from X-Forwarded-For when behind a trusted reverse proxy.
# Set to the number of trusted proxies in your network topology.
# 0 = direct connections only (no proxy).
forwarded_allow_ips = os.environ.get("FORWARDED_ALLOW_IPS", "127.0.0.1")
