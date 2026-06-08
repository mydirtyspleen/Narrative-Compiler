"""
logger — JSON structured logging for ADM-API.

All log records are emitted as single-line JSON objects to stdout.
Downstream log aggregators (Datadog, CloudWatch, Loki, etc.) can ingest
and index these records without any additional parsing.

Log record shape:
  {
    "ts":      "2026-01-01T00:00:00.000Z",   # ISO-8601 UTC
    "level":   "INFO",
    "service": "adm-api",
    "version": "1.0.0",
    "event":   "<short description>",
    ...additional context fields
  }

Usage:
  from adm_api.observability.logger import logger

  logger.info("request.completed", extra={
      "endpoint": "POST /v1/render",
      "key_tier": "live",
      "latency_ms": 4.2,
      "status": 200,
  })
"""

from __future__ import annotations

import json
import logging
import sys
from datetime import datetime, timezone


_SERVICE = "adm-api"
_VERSION = "1.0.0"


# ============================================================================
# JSON formatter
# ============================================================================

class _JSONFormatter(logging.Formatter):
    """Emit every log record as a single-line JSON object."""

    _LEVEL_MAP = {
        logging.DEBUG:    "DEBUG",
        logging.INFO:     "INFO",
        logging.WARNING:  "WARN",
        logging.ERROR:    "ERROR",
        logging.CRITICAL: "CRITICAL",
    }

    def format(self, record: logging.LogRecord) -> str:
        doc: dict = {
            "ts":      datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z",
            "level":   self._LEVEL_MAP.get(record.levelno, "INFO"),
            "service": _SERVICE,
            "version": _VERSION,
            "event":   record.getMessage(),
        }

        # Attach any extra= fields the caller provided
        skip = {
            "name", "msg", "args", "levelname", "levelno", "pathname",
            "filename", "module", "exc_info", "exc_text", "stack_info",
            "lineno", "funcName", "created", "msecs", "relativeCreated",
            "thread", "threadName", "processName", "process", "message",
            "taskName",
        }
        for k, v in record.__dict__.items():
            if k not in skip:
                doc[k] = v

        if record.exc_info:
            doc["exc"] = self.formatException(record.exc_info)

        return json.dumps(doc, default=str)


# ============================================================================
# Singleton logger
# ============================================================================

def _build_logger() -> logging.Logger:
    log = logging.getLogger("adm_api")
    log.setLevel(logging.DEBUG)
    log.propagate = False

    if not log.handlers:
        handler = logging.StreamHandler(sys.stdout)
        handler.setFormatter(_JSONFormatter())
        log.addHandler(handler)

    return log


logger = _build_logger()

# Silence noisy uvicorn access log (we emit structured request logs ourselves)
logging.getLogger("uvicorn.access").handlers = []
logging.getLogger("uvicorn.access").propagate = False


# ============================================================================
# Structured log helpers
# ============================================================================

def log_request(
    *,
    method:       str,
    path:         str,
    status:       int,
    latency_ms:   float,
    key_id:       str | None = None,
    key_tier:     str | None = None,
    session_id:   str | None = None,
    ip:           str | None = None,
) -> None:
    """Emit one INFO record for every completed HTTP request."""
    logger.info(
        "request.completed",
        extra={
            "method":     method,
            "path":       path,
            "status":     status,
            "latency_ms": round(latency_ms, 3),
            **({"key_id":   key_id}   if key_id   else {}),
            **({"key_tier": key_tier} if key_tier  else {}),
            **({"session_id": session_id} if session_id else {}),
            **({"ip": ip} if ip else {}),
        },
    )


def log_ws_connect(*, session_id: str | None, key_id: str | None, key_tier: str | None) -> None:
    logger.info(
        "ws.connected",
        extra={
            "session_id": session_id,
            "key_id":     key_id,
            "key_tier":   key_tier,
        },
    )


def log_ws_disconnect(*, session_id: str | None, key_id: str | None, event_count: int) -> None:
    logger.info(
        "ws.disconnected",
        extra={
            "session_id":  session_id,
            "key_id":      key_id,
            "event_count": event_count,
        },
    )


def log_rate_limit_violation(*, key_id: str, key_tier: str, endpoint: str) -> None:
    logger.warning(
        "rate_limit.exceeded",
        extra={
            "key_id":   key_id,
            "key_tier": key_tier,
            "endpoint": endpoint,
        },
    )


def log_auth_failure(*, reason: str, ip: str | None, path: str) -> None:
    logger.warning(
        "auth.failed",
        extra={
            "reason": reason,
            "path":   path,
            **({"ip": ip} if ip else {}),
        },
    )


def log_pipeline(
    *,
    session_id:   str,
    event_count:  int,
    latency_ms:   float,
    dominant:     str,
    avg_intensity: float,
) -> None:
    logger.debug(
        "pipeline.executed",
        extra={
            "session_id":    session_id,
            "event_count":   event_count,
            "latency_ms":    round(latency_ms, 3),
            "dominant":      dominant,
            "avg_intensity": round(avg_intensity, 4),
        },
    )
