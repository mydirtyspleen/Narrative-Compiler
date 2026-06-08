"""
consequence_engine — fully deterministic structured outcome generation.

Pure functions:
  generate_consequences(ranked_events)                          → list[str]
  build_suggested_next_events(ranked_events, avg_intensity)     → list[SuggestedNextEvent]

NO randomness. Consequence selection uses hash(event.id) % len(pool).
Same event.id always yields the same consequence text.
"""

from __future__ import annotations

from collections import Counter

from adm_api.models.schemas import EventType, GameEvent, SuggestedNextEvent

# ---------------------------------------------------------------------------
# Consequence pools — keyed by (EventType, tier)
# ---------------------------------------------------------------------------

_POOLS: dict[EventType, dict[str, list[str]]] = {
    EventType.combat: {
        "high": [
            "Military forces suffer catastrophic losses across contested zones",
            "Command structure fractures under sustained engagement pressure",
            "Strategic supply lines are severed, forcing logistical collapse",
        ],
        "medium": [
            "Frontline positions shift in favor of the aggressor",
            "Defensive morale deteriorates under continued assault",
            "Civilian infrastructure sustains collateral damage",
        ],
        "low": [
            "Minor skirmish escalates local tensions without decisive outcome",
            "Patrol patterns are disrupted along contested borders",
        ],
    },
    EventType.politics: {
        "high": [
            "Governing coalition fractures under accumulated pressure",
            "Emergency powers are invoked, concentrating authority",
            "Opposition bloc gains decisive leverage over policy formation",
        ],
        "medium": [
            "Diplomatic channels are suspended pending resolution",
            "Public confidence in leadership erodes measurably",
            "Legislative agenda stalls amid factional deadlock",
        ],
        "low": [
            "Procedural dispute delays routine governance decisions",
            "Minor policy concession signals shifting priorities",
        ],
    },
    EventType.economy: {
        "high": [
            "Critical resource reserves fall below operational threshold",
            "Trade networks collapse, triggering supply-chain failure cascade",
            "Currency stability is undermined by capital flight",
        ],
        "medium": [
            "Production output contracts across key industrial sectors",
            "Market confidence declines amid uncertainty signals",
            "Labor mobility increases as economic pressure mounts",
        ],
        "low": [
            "Commodity price fluctuation creates minor distribution inefficiency",
            "Investment flows shift toward lower-risk asset classes",
        ],
    },
    EventType.ecology: {
        "high": [
            "Ecosystem equilibrium destabilizes across the affected biome",
            "Primary resource yields drop critically, threatening dependency chains",
            "Environmental feedback loops accelerate degradation trajectory",
        ],
        "medium": [
            "Biodiversity indicators register measurable decline",
            "Seasonal patterns shift, disrupting agricultural cycles",
            "Water system stress propagates downstream through dependent regions",
        ],
        "low": [
            "Localized habitat disturbance alters microclimatic conditions",
            "Species distribution shifts in response to environmental pressure",
        ],
    },
    EventType.social: {
        "high": [
            "Social cohesion fractures along pre-existing fault lines",
            "Mass mobilization events destabilize civil governance structures",
            "Cultural identity conflict intensifies, triggering community fragmentation",
        ],
        "medium": [
            "Public sentiment shifts away from institutional trust",
            "Community solidarity erodes under prolonged stress conditions",
            "Information networks amplify grievances beyond local containment",
        ],
        "low": [
            "Minor cultural friction emerges between adjacent social groups",
            "Localized dissatisfaction rises without reaching critical threshold",
        ],
    },
    EventType.weather: {
        "high": [
            "Infrastructure systems fail under extreme environmental load",
            "Population displacement accelerates as habitability thresholds are breached",
            "Agricultural output collapses across the affected climate zone",
        ],
        "medium": [
            "Transportation networks experience significant weather-related disruption",
            "Resource procurement operations are degraded by environmental conditions",
            "Structural integrity of built environment is compromised",
        ],
        "low": [
            "Routine operations experience minor weather-related delays",
            "Environmental conditions shift travel patterns temporarily",
        ],
    },
    EventType.exploration: {
        "high": [
            "Previously unknown territory yields strategically significant discovery",
            "Established geographic assumptions are invalidated by new data",
            "Rival factions accelerate expansion in response to disclosed findings",
        ],
        "medium": [
            "Unexplored region is charted, opening new strategic vectors",
            "Resource survey reveals latent extraction opportunities",
            "Territorial boundaries require renegotiation based on new intelligence",
        ],
        "low": [
            "Scouting mission returns with inconclusive but actionable reconnaissance",
            "Peripheral zone mapped without triggering strategic response",
        ],
    },
}

# ---------------------------------------------------------------------------
# Cascade consequence triggers — purely threshold-based, no randomness
# ---------------------------------------------------------------------------

_CASCADE_TRIGGERS: list[dict] = [
    {
        "condition": lambda dominant, events: (
            dominant == EventType.combat
            and any(e.intensity >= 0.7 for e in events)
        ),
        "text": "Conflict escalation triggers regional destabilization cascade",
    },
    {
        "condition": lambda dominant, events: (
            dominant == EventType.economy
            and any(e.intensity >= 0.6 for e in events)
        ),
        "text": "Economic shock propagates through interdependent resource networks",
    },
    {
        "condition": lambda dominant, events: (
            dominant == EventType.ecology
            and any(e.intensity >= 0.6 for e in events)
        ),
        "text": "Environmental tipping point reached — systemic recovery requires intervention",
    },
    {
        "condition": lambda dominant, events: (
            dominant == EventType.social
            and any(e.intensity >= 0.75 for e in events)
        ),
        "text": "Social pressure exceeds institutional containment — governance intervention required",
    },
]

# ---------------------------------------------------------------------------
# Suggested next-event tables — deterministic intensity deltas
# ---------------------------------------------------------------------------

_NEXT_EVENTS: dict[EventType, list[dict]] = {
    EventType.combat: [
        {"type": EventType.politics, "delta": +0.15, "description": "Political response to military escalation"},
        {"type": EventType.economy,  "delta": -0.10, "description": "Resource drain from sustained combat"},
    ],
    EventType.politics: [
        {"type": EventType.social,   "delta": +0.10, "description": "Civilian response to political shift"},
        {"type": EventType.economy,  "delta": +0.10, "description": "Policy-driven economic realignment"},
    ],
    EventType.economy: [
        {"type": EventType.social,   "delta": +0.15, "description": "Social unrest from economic pressure"},
        {"type": EventType.politics, "delta": +0.10, "description": "Political intervention in economic crisis"},
    ],
    EventType.ecology: [
        {"type": EventType.economy,  "delta": +0.10, "description": "Resource scarcity from ecological damage"},
        {"type": EventType.social,   "delta": +0.08, "description": "Population displacement from habitat loss"},
    ],
    EventType.social: [
        {"type": EventType.politics,    "delta": +0.20, "description": "Social pressure escalates to political crisis"},
        {"type": EventType.exploration, "delta": -0.05, "description": "Displaced populations seek new territories"},
    ],
    EventType.weather: [
        {"type": EventType.ecology,  "delta": +0.12, "description": "Weather-driven ecological stress"},
        {"type": EventType.economy,  "delta": +0.08, "description": "Infrastructure damage to supply networks"},
    ],
    EventType.exploration: [
        {"type": EventType.politics, "delta": +0.10, "description": "Territorial discovery triggers political claim"},
        {"type": EventType.economy,  "delta": -0.08, "description": "New resource zone opens extraction opportunity"},
    ],
}


def _tier(intensity: float) -> str:
    if intensity >= 0.7:
        return "high"
    if intensity >= 0.4:
        return "medium"
    return "low"


def _dominant(events: list[GameEvent]) -> EventType:
    return Counter(e.type for e in events).most_common(1)[0][0]


def generate_consequences(ranked_events: list[GameEvent]) -> list[str]:
    """
    Deterministically derive narrative consequences from pre-ranked events.
    Uses hash(event.id) % pool_size for stable selection — no randomness.
    """
    if not ranked_events:
        return ["No significant events detected — world state remains stable"]

    dominant     = _dominant(ranked_events)
    consequences: list[str] = []

    for event in ranked_events[:3]:
        tier = _tier(event.intensity)
        pool = _POOLS[event.type][tier]
        idx  = hash(event.id) % len(pool)
        text = pool[idx]
        if event.actors:
            text = f"{event.actors[0]}: {text}"
        consequences.append(text)

    for trigger in _CASCADE_TRIGGERS:
        if trigger["condition"](dominant, ranked_events):
            consequences.append(trigger["text"])

    return consequences


def build_suggested_next_events(
    ranked_events: list[GameEvent],
    avg_intensity: float,
) -> list[SuggestedNextEvent]:
    """Deterministic suggestions based on dominant category and avg intensity."""
    dominant = _dominant(ranked_events)
    rows     = _NEXT_EVENTS.get(dominant, [])
    return [
        SuggestedNextEvent(
            type        = row["type"].value,
            intensity   = round(max(0.0, min(1.0, avg_intensity + row["delta"])), 4),
            description = row["description"],
        )
        for row in rows
    ]
