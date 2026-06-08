"""
pipeline — single orchestration entry point for the ADM-API core engine.

  run_pipeline(events, world_state) → NarrativeState

Strict call order:
  1. event_ranker          — deterministic ranking, top 10
  2. tension_engine        — tension curve from ranked events
  3. character_focus_engine — dominant actor selection
  4. narrative_engine      — scene_summary + cinematic_description
  5. consequence_engine    — consequences + suggested next events
  6. prompt_generator      — structured LLM context block

No logic lives outside this function. No side effects. No global state.
Same input always produces same output.
"""

from __future__ import annotations

from collections import Counter
from typing import Any

from adm_api.engine.character_focus_engine import resolve_character_focus
from adm_api.engine.consequence_engine import (
    build_suggested_next_events,
    generate_consequences,
)
from adm_api.engine.event_ranker import rank_events
from adm_api.engine.narrative_engine import (
    build_cinematic_description,
    build_scene_summary,
)
from adm_api.engine.prompt_generator import build_llm_prompt
from adm_api.engine.tension_engine import compute_tension_curve
from adm_api.models.schemas import (
    EventType,
    GameEvent,
    NarrativeState,
    RenderMetadata,
)


def run_pipeline(
    events: list[GameEvent],
    world_state: dict[str, Any] | None = None,  # noqa: ARG001 — reserved for future use
) -> NarrativeState:
    """
    Core ADM pipeline — deterministic, stateless, pure.

    Parameters
    ----------
    events:      Pre-validated list of GameEvent objects (min length 1).
    world_state: Reserved for future context enrichment; not used by core engine.

    Returns
    -------
    NarrativeState containing all output fields.
    """

    # ── Step 1: rank ─────────────────────────────────────────────────────────
    ranked = rank_events(events)

    # ── Step 2: tension ───────────────────────────────────────────────────────
    tension_curve = compute_tension_curve(ranked)

    # ── Step 3: character focus ───────────────────────────────────────────────
    character_focus = resolve_character_focus(ranked)

    # ── Step 4: narrative ─────────────────────────────────────────────────────
    avg_intensity = round(
        sum(e.intensity for e in ranked) / len(ranked), 4
    )
    scene_summary         = build_scene_summary(ranked, avg_intensity)
    cinematic_description = build_cinematic_description(ranked, avg_intensity)

    # ── Step 5: consequences + suggestions ────────────────────────────────────
    narrative_consequences = generate_consequences(ranked)
    suggested_next_events  = build_suggested_next_events(ranked, avg_intensity)

    # ── Metadata ──────────────────────────────────────────────────────────────
    dominant_category = Counter(e.type for e in ranked).most_common(1)[0][0].value
    metadata = RenderMetadata(
        avg_intensity     = avg_intensity,
        dominant_category = dominant_category,
        event_count       = len(ranked),
    )

    # ── Assemble intermediate state (without prompt) ──────────────────────────
    state = NarrativeState(
        scene_summary          = scene_summary,
        cinematic_description  = cinematic_description,
        character_focus        = character_focus,
        tension_curve          = tension_curve,
        narrative_consequences = narrative_consequences,
        suggested_next_events  = suggested_next_events,
        llm_prompt             = "",      # populated in step 6
        metadata               = metadata,
    )

    # ── Step 6: prompt ────────────────────────────────────────────────────────
    state.llm_prompt = build_llm_prompt(state, ranked)

    return state
