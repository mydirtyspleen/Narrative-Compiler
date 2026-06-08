"""
character_focus_engine — deterministic actor selection.

Pure function: (list[GameEvent]) → str | None

Rules (applied to the dominant event type by intensity):
  combat      → first actor of highest-intensity combat event
  politics    → first actor containing "faction" (case-insensitive); else first actor
  ecology     → first actor containing "entity"  (case-insensitive); else first actor
  otherwise   → None
"""

from __future__ import annotations

from adm_api.models.schemas import EventType, GameEvent


def resolve_character_focus(ranked_events: list[GameEvent]) -> str | None:
    """Input MUST be pre-ranked (from event_ranker)."""
    if not ranked_events:
        return None

    dominant = ranked_events[0].type

    if dominant == EventType.combat:
        for e in ranked_events:
            if e.type == EventType.combat and e.actors:
                return e.actors[0]
        return None

    if dominant == EventType.politics:
        for e in ranked_events:
            if e.type != EventType.politics:
                continue
            for actor in e.actors:
                if "faction" in actor.lower():
                    return actor
        for e in ranked_events:
            if e.type == EventType.politics and e.actors:
                return e.actors[0]
        return None

    if dominant == EventType.ecology:
        for e in ranked_events:
            if e.type != EventType.ecology:
                continue
            for actor in e.actors:
                if "entity" in actor.lower():
                    return actor
        for e in ranked_events:
            if e.type == EventType.ecology and e.actors:
                return e.actors[0]
        return None

    return None
