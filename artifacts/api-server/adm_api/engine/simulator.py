"""
simulator — deterministic world progression engine.

Pure function: (list[GameEvent], steps, session_id) → list[SimulatedEvent]

NO randomness. Each step derives from previous state via cascade rules.
Actor continuity is preserved from input events.
"""

from __future__ import annotations

from collections import Counter

from adm_api.models.schemas import EventType, GameEvent, SimulatedEvent

# ---------------------------------------------------------------------------
# Cascade rules: for each dominant type, what follows
# ---------------------------------------------------------------------------

_RULES: dict[EventType, list[dict]] = {
    EventType.combat: [
        {"type": EventType.economy,  "delta": -0.15, "tags": ["war", "resource-drain"],   "rationale": "Sustained combat degrades regional economic capacity"},
        {"type": EventType.social,   "delta": +0.10, "tags": ["conflict", "displacement"], "rationale": "Combat pressure drives civilian social destabilization"},
        {"type": EventType.politics, "delta": +0.20, "tags": ["war", "crisis"],            "rationale": "Armed conflict triggers emergency political response"},
    ],
    EventType.politics: [
        {"type": EventType.economy, "delta": +0.10, "tags": ["policy-shift"],   "rationale": "Political realignment reshapes economic incentive structures"},
        {"type": EventType.social,  "delta": +0.15, "tags": ["governance"],     "rationale": "Political change propagates through social institutions"},
    ],
    EventType.economy: [
        {"type": EventType.social,   "delta": +0.20, "tags": ["scarcity", "conflict"], "rationale": "Economic contraction amplifies social stress vectors"},
        {"type": EventType.politics, "delta": +0.15, "tags": ["crisis"],               "rationale": "Economic shocks destabilize political equilibrium"},
    ],
    EventType.ecology: [
        {"type": EventType.economy, "delta": +0.15, "tags": ["resource-depletion"], "rationale": "Ecological degradation constricts available resource base"},
        {"type": EventType.social,  "delta": +0.10, "tags": ["displacement"],       "rationale": "Environmental stress forces population movement and conflict"},
    ],
    EventType.social: [
        {"type": EventType.politics, "delta": +0.20, "tags": ["pressure", "unrest"], "rationale": "Social instability escalates toward political confrontation"},
    ],
    EventType.weather: [
        {"type": EventType.ecology, "delta": +0.15, "tags": ["environmental"], "rationale": "Extreme weather accelerates ecological stress"},
        {"type": EventType.economy, "delta": +0.10, "tags": ["disruption"],    "rationale": "Weather events disrupt supply chains and infrastructure"},
    ],
    EventType.exploration: [
        {"type": EventType.politics, "delta": +0.10, "tags": ["territorial"],  "rationale": "Discovery creates political pressure over newly revealed territory"},
        {"type": EventType.economy,  "delta": -0.10, "tags": ["opportunity"],  "rationale": "Explored territory opens new economic extraction opportunity"},
    ],
}


def _dominant(events: list[GameEvent]) -> EventType:
    if not events:
        return EventType.exploration
    return Counter(e.type for e in events).most_common(1)[0][0]


def _top_actors(events: list[GameEvent]) -> list[str]:
    actors = [a for e in events for a in e.actors]
    return [a for a, _ in Counter(actors).most_common(3)]


def simulate_progression(
    current_events: list[GameEvent],
    steps: int,
    session_id: str,
) -> list[SimulatedEvent]:
    """
    Generate deterministic future events via cascade rules.
    Each step produces events derived from the previous step's dominant type.
    """
    simulated: list[SimulatedEvent] = []
    working   = list(current_events)

    for step in range(1, steps + 1):
        if not working:
            break

        dominant   = _dominant(working)
        rules      = _RULES.get(dominant, [])
        top_actors = _top_actors(working)
        avg        = sum(e.intensity for e in working) / len(working)

        step_events: list[SimulatedEvent] = []
        for rule_idx, rule in enumerate(rules):
            intensity = round(max(0.0, min(1.0, avg + rule["delta"])), 4)
            event_id  = f"{session_id}-sim-s{step}r{rule_idx}"
            step_events.append(SimulatedEvent(
                id        = event_id,
                type      = rule["type"],
                intensity = intensity,
                actors    = top_actors[:2],
                tags      = rule["tags"],
                payload   = {"simulated": True, "step": step, "source": dominant.value},
                step      = step,
                rationale = rule["rationale"],
            ))

        simulated.extend(step_events)
        working = [
            GameEvent(
                id        = f"w-{s.id}",
                type      = s.type,
                intensity = s.intensity,
                actors    = s.actors,
                tags      = s.tags,
                payload   = s.payload,
            )
            for s in step_events
        ]

    return simulated


def compute_trajectory(simulated: list[SimulatedEvent], seed_avg: float) -> str:
    if not simulated:
        return "World state remains static — no cascading forces detected"
    max_step  = max(s.step for s in simulated)
    final     = [s for s in simulated if s.step == max_step]
    final_avg = sum(s.intensity for s in final) / len(final)
    delta     = final_avg - seed_avg
    if delta > 0.15:
        return "Escalating — simulation projects increasing instability across all tracked domains"
    if delta < -0.15:
        return "De-escalating — simulation projects decreasing pressure toward equilibrium restoration"
    return "Stable oscillation — simulation projects sustained tension without definitive resolution"


def compute_dominant_force(simulated: list[SimulatedEvent]) -> str:
    if not simulated:
        return "none"
    return Counter(s.type for s in simulated).most_common(1)[0][0].value
