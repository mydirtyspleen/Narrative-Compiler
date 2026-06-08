"""
narrative_engine — deterministic scene_summary and cinematic_description.

Pure functions:
  build_scene_summary(ranked, avg_intensity)        → str
  build_cinematic_description(ranked, avg_intensity) → str

Tone mapping:
  avg_intensity > 0.7   → catastrophic / epic
  0.4 <= avg <=  0.7    → moderate change
  avg_intensity < 0.4   → subtle atmospheric
"""

from __future__ import annotations

from collections import Counter

from adm_api.models.schemas import EventType, GameEvent

_CATASTROPHIC = "catastrophic"
_MODERATE     = "moderate"
_SUBTLE       = "subtle"


def _tone(avg_intensity: float) -> str:
    if avg_intensity > 0.7:
        return _CATASTROPHIC
    if avg_intensity >= 0.4:
        return _MODERATE
    return _SUBTLE


def _dominant_type(events: list[GameEvent]) -> EventType:
    return Counter(e.type for e in events).most_common(1)[0][0]


def _zone(events: list[GameEvent]) -> str:
    tags = [t for e in events for t in e.tags]
    if tags:
        top = Counter(tags).most_common(1)[0][0]
        return top.replace("-", " ").replace("_", " ")
    return f"{_dominant_type(events).value} zone"


def _lead_actor(events: list[GameEvent]) -> str:
    actors = [a for e in events for a in e.actors]
    if not actors:
        return "unaffiliated forces"
    return Counter(actors).most_common(1)[0][0]


_SUMMARY: dict[EventType, dict[str, str]] = {
    EventType.combat: {
        _CATASTROPHIC: "Overwhelming {actor} military engagement erupts across {zone}, delivering catastrophic losses on all sides",
        _MODERATE:     "{actor} forces clash in {zone}, shifting frontlines amid escalating attrition",
        _SUBTLE:       "Low-level {actor} hostilities simmer in {zone}, generating friction without decisive engagement",
    },
    EventType.politics: {
        _CATASTROPHIC: "The {actor} governing apparatus collapses under existential political pressure in {zone}",
        _MODERATE:     "Significant {actor} political realignment unfolds in {zone}, reshaping coalition dynamics",
        _SUBTLE:       "Procedural {actor} political maneuvering in {zone} produces incremental power shifts",
    },
    EventType.economy: {
        _CATASTROPHIC: "{actor} economic infrastructure catastrophically fails in {zone}, triggering systemic collapse",
        _MODERATE:     "{actor} market disruption propagates through {zone}'s resource networks",
        _SUBTLE:       "Minor {actor} economic fluctuations register across {zone}'s trade channels",
    },
    EventType.ecology: {
        _CATASTROPHIC: "Catastrophic ecological breakdown destabilizes {zone}'s {actor} biome across all dependency layers",
        _MODERATE:     "Measurable {actor} environmental degradation advances through {zone}'s ecosystems",
        _SUBTLE:       "Subtle {actor} ecological shifts register across {zone}'s peripheral habitats",
    },
    EventType.social: {
        _CATASTROPHIC: "Total {actor} social fragmentation tears through {zone}'s civil fabric",
        _MODERATE:     "{actor} social tensions reach critical threshold in {zone}, straining institutional bonds",
        _SUBTLE:       "Quiet {actor} social undercurrents shift cultural alignment in {zone}",
    },
    EventType.weather: {
        _CATASTROPHIC: "Catastrophic {actor} meteorological event devastates {zone}'s infrastructure capacity",
        _MODERATE:     "Significant weather patterns disrupt {actor} operations across {zone}",
        _SUBTLE:       "Atmospheric shifts introduce {actor} environmental variability across {zone}",
    },
    EventType.exploration: {
        _CATASTROPHIC: "Groundbreaking {actor} discovery in {zone} fundamentally redefines strategic geography",
        _MODERATE:     "{actor} exploration operations chart significant new territory in {zone}",
        _SUBTLE:       "{actor} reconnaissance yields incremental intelligence from {zone}'s outer margins",
    },
}

_CINEMATIC: dict[str, list[str]] = {
    _CATASTROPHIC: [
        (
            "The {zone} does not break — it shatters. {lead_type} forces converge at vectors "
            "that defy containment, each threshold crossed triggering cascades the modeling "
            "systems failed to anticipate. What began as {lead_type} activity at intensity "
            "{top_intensity:.2f} has propagated into something that rewrites the operational "
            "baseline entirely."
        ),
        (
            "In the aftermath, the architecture of {zone} is unrecognizable. {lead_actor} "
            "coordinates have been erased from stable maps. The simulation registers this not "
            "as disruption to the existing order but as the erasure of the order itself — "
            "a phase transition from structured volatility to systemic collapse."
        ),
        (
            "Across {zone}, {lead_type} pressure vectors have exceeded every modeled tolerance "
            "threshold. The narrative compiler registers {event_count} concurrent destabilization "
            "events averaging {avg_pct}% intensity — placing this sequence in the critical tier."
        ),
    ],
    _MODERATE: [
        (
            "The {zone} is in motion. {lead_type} forces exert measurable pressure across key "
            "structural nodes, bending — but not breaking — the existing configuration. "
            "{lead_actor} remains a factor, though margins are narrowing against a backdrop of "
            "{lead_type} activity at intensity {top_intensity:.2f}."
        ),
        (
            "Change propagates through {zone} in structured waves. The {event_count} registered "
            "events carry an average intensity of {avg_pct}%, sufficient to produce narrative "
            "momentum without triggering irreversible state transitions. The system is under "
            "load — not under collapse."
        ),
        (
            "For now, {zone} holds. But the {lead_type} pressure signature is building toward "
            "thresholds requiring active response. {lead_actor} operates at the edge of "
            "established parameters, buying time against an accelerating timeline."
        ),
    ],
    _SUBTLE: [
        (
            "The {zone} breathes. Small {lead_type} perturbations ripple through the simulation "
            "fabric — imperceptible at macro scale, but catalogued by the narrative layer as "
            "meaningful precursors. {lead_actor} moves quietly; the world adjusts its posture "
            "without announcing the shift."
        ),
        (
            "Beneath the surface stability of {zone}, {event_count} low-intensity events register "
            "cumulative drift at {avg_pct}% average intensity. This sequence falls below action "
            "thresholds — but the compiler notes it as directional signal, not noise."
        ),
    ],
}


def build_scene_summary(ranked_events: list[GameEvent], avg_intensity: float) -> str:
    tone     = _tone(avg_intensity)
    dominant = _dominant_type(ranked_events)
    template = _SUMMARY[dominant][tone]
    return template.format(actor=_lead_actor(ranked_events), zone=_zone(ranked_events))


def build_cinematic_description(ranked_events: list[GameEvent], avg_intensity: float) -> str:
    tone       = _tone(avg_intensity)
    paragraphs = _CINEMATIC[tone]
    dominant   = _dominant_type(ranked_events)
    top_event  = ranked_events[0]
    ctx = dict(
        zone          = _zone(ranked_events),
        lead_type     = dominant.value,
        lead_actor    = _lead_actor(ranked_events),
        top_intensity = top_event.intensity,
        event_count   = len(ranked_events),
        avg_pct       = f"{avg_intensity * 100:.1f}",
    )
    return "\n\n".join(p.format(**ctx) for p in paragraphs)
