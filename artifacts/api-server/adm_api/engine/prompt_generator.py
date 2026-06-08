"""
prompt_generator — structured LLM context block generation.

Pure function: (NarrativeState, list[GameEvent]) → str

Produces a richly structured prompt for feeding to external LLMs.
Includes: scene_summary, cinematic_description, key events,
tension_curve, character_focus, consequences, and metadata.
"""

from __future__ import annotations

from adm_api.models.schemas import GameEvent, NarrativeState


def build_llm_prompt(state: NarrativeState, ranked_events: list[GameEvent]) -> str:
    event_lines = "\n".join(
        f"  [{i + 1}] type={e.type.value} intensity={e.intensity:.2f} "
        f"actors={','.join(e.actors) or 'none'} "
        f"tags={','.join(e.tags) or 'none'}"
        for i, e in enumerate(ranked_events[:5])
    )
    tension_str      = " → ".join(f"{v:.3f}" for v in state.tension_curve)
    focus_str        = state.character_focus or "none"
    consequences_str = "\n".join(f"  - {c}" for c in state.narrative_consequences)

    return f"""\
[ADM-API NARRATIVE CONTEXT v1]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

SCENE SUMMARY
{state.scene_summary}

CINEMATIC DESCRIPTION
{state.cinematic_description}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

ACTIVE EVENTS (ranked by intensity)
{event_lines}

CHARACTER FOCUS
{focus_str}

TENSION CURVE
{tension_str}

NARRATIVE CONSEQUENCES
{consequences_str}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

METADATA
  avg_intensity:      {state.metadata.avg_intensity:.4f}
  dominant_category:  {state.metadata.dominant_category}
  event_count:        {state.metadata.event_count}

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
[INSTRUCTION FOR LLM]
You are an external narrative expansion engine. Using the structured
context above, expand the scene into vivid, in-world prose. Do not
contradict the structured consequences or tension values. Do not invent
new factions, actors, or world elements beyond those listed. Maintain
tonal consistency with the intensity level ({state.metadata.avg_intensity:.2f}).
[END ADM-API CONTEXT]\
"""
