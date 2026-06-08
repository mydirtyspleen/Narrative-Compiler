"""
event_ranker — deterministic event ordering and selection.

Pure function: (list[GameEvent]) → list[GameEvent]

Rules:
  - Sort by intensity DESC
  - Stable: equal-intensity events break ties by hash(event.id) ASC
  - Limit to top MAX_EVENTS
"""

from __future__ import annotations

from adm_api.models.schemas import GameEvent

MAX_EVENTS = 10


def rank_events(events: list[GameEvent]) -> list[GameEvent]:
    """Return top-N events sorted deterministically by intensity DESC, id-hash ASC."""
    ranked = sorted(
        events,
        key=lambda e: (-e.intensity, hash(e.id) & 0xFFFFFFFF),
    )
    return ranked[:MAX_EVENTS]
