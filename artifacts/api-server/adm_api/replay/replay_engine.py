"""
replay/replay_engine.py — Event replay system for ADM-API.

Purpose:
  Save named event batches to disk, replay them later, and verify that
  the pipeline produces byte-identical output on every run.
  Serves as a live regression test for the determinism guarantee.

Storage:
  data/replays/{name}.json
  Each file is a ReplayBatch: session_id, events, saved_at, output_hash.

Hash:
  SHA-256 of the canonical JSON output (keys sorted, no whitespace).
  Saved on first run; verified on every subsequent replay.

API routes (in replay_routes.py):
  POST /v1/replay/save    — save a named event batch + compute reference hash
  POST /v1/replay/run     — replay a named batch and verify hash
  GET  /v1/replay/list    — list all saved replays
  GET  /v1/replay/{name}  — get replay metadata
"""

from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from adm_api.engine.pipeline import run_pipeline
from adm_api.models.schemas import GameEvent


# ── Storage ───────────────────────────────────────────────────────────────────

_REPLAYS_DIR = Path(__file__).parent.parent.parent / "data" / "replays"


def _ensure_dir() -> None:
    _REPLAYS_DIR.mkdir(parents=True, exist_ok=True)


def _replay_path(name: str) -> Path:
    # Sanitize name — only alphanumeric + hyphens/underscores
    safe = "".join(c for c in name if c.isalnum() or c in "-_")
    if not safe:
        raise ValueError(f"Invalid replay name: {name!r}")
    return _REPLAYS_DIR / f"{safe}.json"


def _canonical_json(obj: dict) -> str:
    """Deterministic JSON string (sorted keys, compact)."""
    return json.dumps(obj, sort_keys=True, separators=(",", ":"))


def _output_hash(narrative_state_dict: dict) -> str:
    """SHA-256 of the canonical JSON of a NarrativeState dict."""
    return hashlib.sha256(_canonical_json(narrative_state_dict).encode()).hexdigest()


# ── Data structures ───────────────────────────────────────────────────────────

class ReplaySaveResult:
    """Result returned by save_replay()."""
    __slots__ = ("name", "event_count", "output_hash", "saved_at")

    def __init__(
        self,
        name:        str,
        event_count: int,
        output_hash: str,
        saved_at:    str,
    ) -> None:
        self.name        = name
        self.event_count = event_count
        self.output_hash = output_hash
        self.saved_at    = saved_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "name":        self.name,
            "event_count": self.event_count,
            "output_hash": self.output_hash,
            "saved_at":    self.saved_at,
        }


class ReplayRunResult:
    """Result returned by run_replay()."""
    __slots__ = (
        "name", "session_id", "event_count",
        "output_hash", "reference_hash",
        "hash_match", "latency_ms",
        "narrative_state",
        "run_at",
    )

    def __init__(
        self,
        name:            str,
        session_id:      str,
        event_count:     int,
        output_hash:     str,
        reference_hash:  str,
        latency_ms:      float,
        narrative_state: dict,
        run_at:          str,
    ) -> None:
        self.name            = name
        self.session_id      = session_id
        self.event_count     = event_count
        self.output_hash     = output_hash
        self.reference_hash  = reference_hash
        self.hash_match      = output_hash == reference_hash
        self.latency_ms      = latency_ms
        self.narrative_state = narrative_state
        self.run_at          = run_at

    def to_dict(self) -> dict[str, Any]:
        return {
            "name":            self.name,
            "session_id":      self.session_id,
            "event_count":     self.event_count,
            "output_hash":     self.output_hash,
            "reference_hash":  self.reference_hash,
            "hash_match":      self.hash_match,
            "latency_ms":      round(self.latency_ms, 3),
            "narrative_state": self.narrative_state,
            "run_at":          self.run_at,
        }


class ReplayInfo:
    """Metadata for a saved replay (list view)."""
    __slots__ = ("name", "session_id", "event_count", "output_hash", "saved_at", "run_count", "last_run_at")

    def __init__(self, d: dict) -> None:
        self.name        = d["name"]
        self.session_id  = d["session_id"]
        self.event_count = d["event_count"]
        self.output_hash = d["output_hash"]
        self.saved_at    = d["saved_at"]
        self.run_count   = d.get("run_count", 0)
        self.last_run_at = d.get("last_run_at")

    def to_dict(self) -> dict[str, Any]:
        return {
            "name":        self.name,
            "session_id":  self.session_id,
            "event_count": self.event_count,
            "output_hash": self.output_hash,
            "saved_at":    self.saved_at,
            "run_count":   self.run_count,
            "last_run_at": self.last_run_at,
        }


# ── Engine ────────────────────────────────────────────────────────────────────

class ReplayEngine:
    """
    Save and replay event batches to verify deterministic pipeline output.

    All operations are synchronous (disk I/O is minimal; fine for API handlers).
    """

    # ── Save ──────────────────────────────────────────────────────────────────

    def save_replay(
        self,
        name:       str,
        session_id: str,
        events:     list[GameEvent],
        world_state: dict[str, Any] | None = None,
    ) -> ReplaySaveResult:
        """
        Run the pipeline once, hash the output, and persist to disk.

        Parameters
        ----------
        name       : Unique replay name (alphanumeric + hyphens/underscores)
        session_id : Session identifier (echoed back in results)
        events     : Pre-validated GameEvent list
        world_state: Optional world context (passed through to pipeline)

        Returns
        -------
        ReplaySaveResult with name, event_count, output_hash, saved_at.

        Raises
        ------
        ValueError if name is invalid.
        FileExistsError if a replay with this name already exists.
        """
        _ensure_dir()
        path = _replay_path(name)
        if path.exists():
            raise FileExistsError(
                f"Replay '{name}' already exists. "
                "Use a different name or delete the existing replay first."
            )

        # Run pipeline
        state       = run_pipeline(events, world_state or {})
        state_dict  = state.model_dump()
        output_hash = _output_hash(state_dict)
        now         = datetime.now(timezone.utc).isoformat()

        # Persist
        doc = {
            "name":        name,
            "session_id":  session_id,
            "event_count": len(events),
            "events":      [e.model_dump() for e in events],
            "world_state": world_state or {},
            "output_hash": output_hash,
            "saved_at":    now,
            "run_count":   0,
            "last_run_at": None,
        }
        path.write_text(json.dumps(doc, indent=2))

        return ReplaySaveResult(
            name        = name,
            event_count = len(events),
            output_hash = output_hash,
            saved_at    = now,
        )

    # ── Run ───────────────────────────────────────────────────────────────────

    def run_replay(self, name: str) -> ReplayRunResult:
        """
        Load a saved replay, run the pipeline on the original events,
        and verify the output hash matches.

        A hash_match=False result indicates a determinism violation —
        this should never happen unless the engine code was intentionally modified.

        Returns
        -------
        ReplayRunResult with hash_match, latency_ms, and full narrative_state.

        Raises
        ------
        FileNotFoundError if no replay with this name exists.
        """
        path = _replay_path(name)
        if not path.exists():
            raise FileNotFoundError(f"Replay '{name}' not found.")

        doc = json.loads(path.read_text())

        # Reconstruct validated GameEvent objects
        events = [GameEvent.model_validate(e) for e in doc["events"]]
        world_state = doc.get("world_state", {})

        # Re-run pipeline
        t0          = time.monotonic()
        state       = run_pipeline(events, world_state)
        latency_ms  = (time.monotonic() - t0) * 1000
        state_dict  = state.model_dump()
        output_hash = _output_hash(state_dict)
        now         = datetime.now(timezone.utc).isoformat()

        # Update run stats on disk
        doc["run_count"]   = doc.get("run_count", 0) + 1
        doc["last_run_at"] = now
        path.write_text(json.dumps(doc, indent=2))

        return ReplayRunResult(
            name            = name,
            session_id      = doc["session_id"],
            event_count     = len(events),
            output_hash     = output_hash,
            reference_hash  = doc["output_hash"],
            latency_ms      = latency_ms,
            narrative_state = state_dict,
            run_at          = now,
        )

    # ── List ──────────────────────────────────────────────────────────────────

    def list_replays(self) -> list[ReplayInfo]:
        """
        Return metadata for all saved replays, sorted by saved_at descending.
        """
        _ensure_dir()
        results: list[ReplayInfo] = []
        for p in sorted(_REPLAYS_DIR.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True):
            try:
                doc = json.loads(p.read_text())
                results.append(ReplayInfo(doc))
            except Exception:
                pass  # skip corrupt files
        return results

    # ── Get ───────────────────────────────────────────────────────────────────

    def get_replay(self, name: str) -> ReplayInfo:
        """Get metadata for a single replay by name."""
        path = _replay_path(name)
        if not path.exists():
            raise FileNotFoundError(f"Replay '{name}' not found.")
        return ReplayInfo(json.loads(path.read_text()))

    # ── Delete ────────────────────────────────────────────────────────────────

    def delete_replay(self, name: str) -> bool:
        """Delete a replay. Returns True if deleted, False if not found."""
        path = _replay_path(name)
        if not path.exists():
            return False
        path.unlink()
        return True


# ── Module-level singleton ─────────────────────────────────────────────────────

replay_engine = ReplayEngine()
