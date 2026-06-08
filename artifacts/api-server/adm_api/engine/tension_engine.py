"""
tension_engine — deterministic tension curve computation.

Pure function: (list[GameEvent]) → list[float]

Base weights per event type:
  combat: 0.9  politics: 0.8  social: 0.6  ecology: 0.6
  economy: 0.5  weather: 0.4  exploration: 0.3

Formula:   tension = (base_weight + intensity) / 2
Modifiers: +0.25 if tags ∩ {war, conflict, chaos} is non-empty
           -0.25 if tags ∩ {peace, order} is non-empty
Clamped:   [0.0, 1.0]
Output:    one float per event, max MAX_TENSION_VALUES entries
"""

from __future__ import annotations

from adm_api.models.schemas import EventType, GameEvent

_BASE_WEIGHTS: dict[EventType, float] = {
    EventType.combat:      0.9,
    EventType.politics:    0.8,
    EventType.social:      0.6,
    EventType.ecology:     0.6,
    EventType.economy:     0.5,
    EventType.weather:     0.4,
    EventType.exploration: 0.3,
}

_ESCALATION_TAGS:    frozenset[str] = frozenset({"war", "conflict", "chaos"})
_DEESCALATION_TAGS:  frozenset[str] = frozenset({"peace", "order"})

MAX_TENSION_VALUES = 10


def _single_tension(event: GameEvent) -> float:
    base    = _BASE_WEIGHTS[event.type]
    tension = (base + event.intensity) / 2.0
    tags    = {t.lower() for t in event.tags}
    if tags & _ESCALATION_TAGS:
        tension += 0.25
    if tags & _DEESCALATION_TAGS:
        tension -= 0.25
    return round(max(0.0, min(1.0, tension)), 4)


def compute_tension_curve(ranked_events: list[GameEvent]) -> list[float]:
    """
    Input MUST be pre-ranked (from event_ranker).
    Returns one tension value per event, up to MAX_TENSION_VALUES.
    """
    return [_single_tension(e) for e in ranked_events[:MAX_TENSION_VALUES]]
