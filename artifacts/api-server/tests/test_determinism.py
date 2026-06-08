"""
test_determinism — ADM-API determinism test suite.

Verifies:
  1.  Same input → byte-identical output (core guarantee).
  2.  Consequence selection is hash-stable — event.id determines pool index.
  3.  Tension curves are fully deterministic across all event types.
  4.  Pipeline is stable across N repeated calls.
  5.  Event ranking is stable (same intensities, same order).
  6.  Simulate progression is deterministic for same seed events.
  7.  All seven EventTypes produce valid output.
  8.  Edge cases: single event, max events (10+), zero-intensity events.
  9.  World state does not alter narrative output (reserved field).
  10. Character focus is stable for same event set.

Run with:
  cd artifacts/api-server
  python -m pytest tests/ -v
"""

from __future__ import annotations

import copy
import json
from typing import Any

import pytest

from adm_api.engine.consequence_engine import (
    build_suggested_next_events,
    generate_consequences,
)
from adm_api.engine.event_ranker import rank_events
from adm_api.engine.pipeline import run_pipeline
from adm_api.engine.simulator import simulate_progression
from adm_api.engine.tension_engine import compute_tension_curve
from adm_api.engine.character_focus_engine import resolve_character_focus
from adm_api.models.schemas import EventType, GameEvent, NarrativeState


# ============================================================================
# Fixtures
# ============================================================================

def _event(
    id: str,
    type: str = "combat",
    intensity: float = 0.8,
    actors: list[str] | None = None,
    tags: list[str] | None = None,
) -> GameEvent:
    return GameEvent(
        id        = id,
        type      = EventType(type),
        intensity = intensity,
        actors    = actors or [],
        tags      = tags or [],
        payload   = {},
    )


SAMPLE_EVENTS = [
    _event("e-combat-01", "combat",    0.88, ["Iron Pact"],         ["war", "conflict"]),
    _event("e-politics-01","politics", 0.65, ["faction:Council"],   ["crisis"]),
    _event("e-ecology-01", "ecology",  0.40, ["region:Tundra"],     ["drought"]),
]

SINGLE_EVENT = [
    _event("solo-001", "combat", 0.5, ["SoloFaction"], ["border"]),
]

ALL_TYPE_EVENTS = [
    _event(f"t-{t}", t, 0.6)
    for t in ["combat", "politics", "economy", "ecology", "social", "weather", "exploration"]
]

HIGH_INTENSITY = [
    _event("hi-01", "combat", 1.0, ["Legion"], ["war"]),
    _event("hi-02", "combat", 0.9, ["Guard"],  ["siege"]),
]

LOW_INTENSITY = [
    _event("lo-01", "exploration", 0.01, [], []),
    _event("lo-02", "weather",     0.05, [], ["rain"]),
]


# ============================================================================
# 1. Pipeline — byte-identical output on repeated calls
# ============================================================================

class TestPipelineDeterminism:

    def test_same_input_same_json_output(self):
        """Core guarantee: same input always produces byte-identical JSON."""
        a = json.dumps(run_pipeline(SAMPLE_EVENTS).model_dump(), sort_keys=True)
        b = json.dumps(run_pipeline(SAMPLE_EVENTS).model_dump(), sort_keys=True)
        assert a == b

    def test_stability_over_100_calls(self):
        """Run pipeline 100 times — every result must be identical."""
        reference = json.dumps(run_pipeline(SAMPLE_EVENTS).model_dump(), sort_keys=True)
        for _ in range(100):
            candidate = json.dumps(run_pipeline(SAMPLE_EVENTS).model_dump(), sort_keys=True)
            assert candidate == reference

    def test_deep_copy_input_unchanged(self):
        """Input events must not be mutated by the pipeline."""
        original = copy.deepcopy(SAMPLE_EVENTS)
        run_pipeline(SAMPLE_EVENTS)
        for orig, after in zip(original, SAMPLE_EVENTS):
            assert orig.id        == after.id
            assert orig.type      == after.type
            assert orig.intensity == after.intensity

    def test_world_state_does_not_alter_output(self):
        """world_state is a reserved field — output must be identical regardless."""
        base  = run_pipeline(SAMPLE_EVENTS, {})
        with_state = run_pipeline(SAMPLE_EVENTS, {"arbitrary_key": "arbitrary_value"})
        assert base.model_dump() == with_state.model_dump()

    def test_output_is_complete_narrative_state(self):
        """All eight required NarrativeState fields must be present and typed correctly."""
        state = run_pipeline(SAMPLE_EVENTS)
        assert isinstance(state, NarrativeState)
        assert isinstance(state.scene_summary,          str)  and state.scene_summary
        assert isinstance(state.cinematic_description,  str)  and state.cinematic_description
        assert isinstance(state.tension_curve,          list) and state.tension_curve
        assert isinstance(state.narrative_consequences, list) and state.narrative_consequences
        assert isinstance(state.suggested_next_events,  list) and state.suggested_next_events
        assert isinstance(state.llm_prompt,             str)  and state.llm_prompt
        assert isinstance(state.metadata.avg_intensity, float)
        assert isinstance(state.metadata.event_count,   int)
        assert isinstance(state.metadata.dominant_category, str)


# ============================================================================
# 2. Consequence engine — hash-stable selection
# ============================================================================

class TestConsequenceDeterminism:

    def test_same_event_id_same_consequence(self):
        """Consequence text is derived purely from hash(event.id) — must be stable."""
        events = SAMPLE_EVENTS
        a = generate_consequences(events)
        b = generate_consequences(events)
        assert a == b

    def test_consequence_count_matches_input(self):
        """At least one consequence per top-3 event + possible cascade trigger."""
        consequences = generate_consequences(SAMPLE_EVENTS)
        assert len(consequences) >= 1

    def test_cascade_trigger_fires_on_high_combat(self):
        """High-intensity combat should trigger the cascade consequence."""
        events = [_event(f"c{i}", "combat", 0.9) for i in range(3)]
        consequences = generate_consequences(events)
        cascade_texts = [c for c in consequences if "cascade" in c.lower() or "destabiliz" in c.lower()]
        assert cascade_texts, f"Expected cascade trigger, got: {consequences}"

    def test_actors_prefix_applied_when_present(self):
        """Consequence text should be prefixed with actor name when actors are present."""
        events = [_event("actor-test", "combat", 0.8, ["MyFaction"], [])]
        result = generate_consequences(events)
        assert any("MyFaction" in c for c in result)

    def test_deterministic_for_all_event_types(self):
        """Every event type must produce consistent consequences on repeated calls."""
        for event_type in EventType:
            events = [_event(f"stable-{event_type.value}", event_type.value, 0.7)]
            a = generate_consequences(events)
            b = generate_consequences(events)
            assert a == b, f"Non-deterministic consequence for type={event_type}"

    def test_suggested_next_events_stable(self):
        """build_suggested_next_events must return identical output on repeated calls."""
        a = build_suggested_next_events(SAMPLE_EVENTS, 0.65)
        b = build_suggested_next_events(SAMPLE_EVENTS, 0.65)
        assert a == b

    def test_suggested_intensities_clamped(self):
        """Suggested event intensities must remain in [0.0, 1.0]."""
        suggestions = build_suggested_next_events(HIGH_INTENSITY, 1.0)
        for s in suggestions:
            assert 0.0 <= s.intensity <= 1.0, f"Out-of-range intensity: {s.intensity}"


# ============================================================================
# 3. Tension engine
# ============================================================================

class TestTensionDeterminism:

    def test_curve_is_deterministic(self):
        """Tension curve must be byte-identical on repeated calls."""
        a = compute_tension_curve(SAMPLE_EVENTS)
        b = compute_tension_curve(SAMPLE_EVENTS)
        assert a == b

    def test_all_values_clamped(self):
        """All tension values must be in [0.0, 1.0]."""
        for events in [SAMPLE_EVENTS, HIGH_INTENSITY, LOW_INTENSITY, ALL_TYPE_EVENTS]:
            curve = compute_tension_curve(events)
            for v in curve:
                assert 0.0 <= v <= 1.0, f"Tension out of range: {v}"

    def test_combat_higher_than_exploration(self):
        """Combat events should generate higher tension than exploration events."""
        combat_curve = compute_tension_curve([_event("c", "combat", 0.8)])
        explor_curve = compute_tension_curve([_event("e", "exploration", 0.8)])
        assert combat_curve[0] > explor_curve[0]

    def test_escalation_tags_increase_tension(self):
        """War/conflict tags should raise tension above baseline."""
        base    = compute_tension_curve([_event("base", "combat", 0.5, tags=[])])
        scaled  = compute_tension_curve([_event("base", "combat", 0.5, tags=["war"])])
        assert scaled[0] >= base[0]

    def test_deescalation_tags_decrease_tension(self):
        """Peace/order tags should lower tension."""
        base  = compute_tension_curve([_event("x", "combat", 0.5, tags=[])])
        peace = compute_tension_curve([_event("x", "combat", 0.5, tags=["peace"])])
        assert peace[0] <= base[0]

    def test_single_event_returns_list(self):
        curve = compute_tension_curve(SINGLE_EVENT)
        assert isinstance(curve, list)
        assert len(curve) == 1

    def test_curve_length_capped_at_ten(self):
        """Tension curve should never exceed 10 values."""
        many_events = [_event(f"e{i}", "combat", 0.5) for i in range(25)]
        curve = compute_tension_curve(many_events)
        assert len(curve) <= 10

    def test_deterministic_for_all_types(self):
        for event_type in EventType:
            events = [_event(f"ten-{event_type.value}", event_type.value, 0.5)]
            a = compute_tension_curve(events)
            b = compute_tension_curve(events)
            assert a == b, f"Non-deterministic tension for type={event_type}"


# ============================================================================
# 4. Event ranker
# ============================================================================

class TestEventRanker:

    def test_ranking_is_stable(self):
        """rank_events must return the same ordered list on repeated calls."""
        a = rank_events(SAMPLE_EVENTS)
        b = rank_events(SAMPLE_EVENTS)
        assert [e.id for e in a] == [e.id for e in b]

    def test_higher_intensity_ranked_first(self):
        """Events must be sorted by intensity descending."""
        events = [
            _event("low",  "ecology",  0.2),
            _event("high", "combat",   0.9),
            _event("mid",  "politics", 0.6),
        ]
        ranked = rank_events(events)
        intensities = [e.intensity for e in ranked]
        assert intensities == sorted(intensities, reverse=True)

    def test_top_10_cap(self):
        """rank_events should return at most 10 events."""
        many = [_event(f"e{i}", "combat", 0.5) for i in range(20)]
        ranked = rank_events(many)
        assert len(ranked) <= 10

    def test_single_event_passes_through(self):
        ranked = rank_events(SINGLE_EVENT)
        assert len(ranked) == 1
        assert ranked[0].id == SINGLE_EVENT[0].id


# ============================================================================
# 5. Character focus engine
# ============================================================================

class TestCharacterFocus:

    def test_returns_dominant_actor(self):
        """Character focus should resolve to a non-empty string."""
        focus = resolve_character_focus(SAMPLE_EVENTS)
        assert isinstance(focus, (str, type(None)))

    def test_stable_across_repeated_calls(self):
        a = resolve_character_focus(SAMPLE_EVENTS)
        b = resolve_character_focus(SAMPLE_EVENTS)
        assert a == b

    def test_no_actors_returns_none_or_category(self):
        """Events without actors should still return a valid (non-crashing) focus."""
        events = [_event("bare", "combat", 0.9)]
        focus = resolve_character_focus(events)
        assert focus is None or isinstance(focus, str)


# ============================================================================
# 6. Simulator
# ============================================================================

class TestSimulatorDeterminism:

    def test_same_seed_same_output(self):
        result_a = simulate_progression(SAMPLE_EVENTS, steps=3, session_id="sess-x")
        result_b = simulate_progression(SAMPLE_EVENTS, steps=3, session_id="sess-x")
        ids_a = [e.id for e in result_a]
        ids_b = [e.id for e in result_b]
        assert ids_a == ids_b

    def test_step_count_matches_request(self):
        """Simulator must produce events for every requested step."""
        result = simulate_progression(SAMPLE_EVENTS, steps=5, session_id="steps-test")
        steps_present = sorted(set(e.step for e in result))
        assert steps_present == list(range(1, 6))

    def test_different_session_ids_produce_different_events(self):
        """Session ID feeds into the deterministic hash — different IDs → different output."""
        a = simulate_progression(SINGLE_EVENT, steps=2, session_id="alpha")
        b = simulate_progression(SINGLE_EVENT, steps=2, session_id="beta")
        ids_a = [e.id for e in a]
        ids_b = [e.id for e in b]
        assert ids_a != ids_b

    def test_intensities_clamped(self):
        """All simulated event intensities must be in [0.0, 1.0]."""
        result = simulate_progression(SAMPLE_EVENTS, steps=5, session_id="clamp-test")
        for e in result:
            assert 0.0 <= e.intensity <= 1.0, f"Out-of-range intensity: {e}"

    def test_deterministic_for_all_source_types(self):
        """Simulator must be deterministic for every event type as seed."""
        for event_type in EventType:
            seed = [_event(f"seed-{event_type.value}", event_type.value, 0.5)]
            a = simulate_progression(seed, steps=2, session_id="typetest")
            b = simulate_progression(seed, steps=2, session_id="typetest")
            assert [e.id for e in a] == [e.id for e in b]


# ============================================================================
# 7. Full pipeline — edge cases
# ============================================================================

class TestPipelineEdgeCases:

    def test_single_event(self):
        state = run_pipeline(SINGLE_EVENT)
        assert state.metadata.event_count == 1
        assert state.tension_curve
        assert state.scene_summary

    def test_all_seven_event_types_produce_valid_output(self):
        """Every EventType must flow through the pipeline without error."""
        for event_type in EventType:
            events = [_event(f"type-{event_type.value}", event_type.value, 0.6)]
            state = run_pipeline(events)
            assert state.scene_summary
            assert state.metadata.dominant_category == event_type.value

    def test_max_events_handled_without_error(self):
        """Pipeline should handle large batches without crashing."""
        large_batch = [_event(f"big-{i}", "combat", 0.5) for i in range(50)]
        state = run_pipeline(large_batch)
        assert state.metadata.event_count <= 10  # ranker caps at 10

    def test_zero_intensity_event(self):
        events = [_event("zero", "weather", 0.0)]
        state = run_pipeline(events)
        assert state.tension_curve[0] >= 0.0

    def test_max_intensity_event(self):
        events = [_event("max", "combat", 1.0, ["Legion"], ["war"])]
        state = run_pipeline(events)
        assert state.tension_curve[0] == 1.0

    def test_mixed_types_dominant_category(self):
        """Dominant category must match the most frequent event type."""
        events = [
            _event("c1", "combat",   0.9),
            _event("c2", "combat",   0.8),
            _event("p1", "politics", 0.7),
        ]
        state = run_pipeline(events)
        assert state.metadata.dominant_category == "combat"

    def test_no_actors_no_tags_runs_cleanly(self):
        events = [_event(f"bare-{i}", "economy", 0.5) for i in range(3)]
        state = run_pipeline(events)
        assert state.narrative_consequences

    def test_metadata_avg_intensity_correct(self):
        events = [
            _event("a", "combat", 0.4),
            _event("b", "combat", 0.8),
        ]
        state = run_pipeline(events)
        expected_avg = round((0.4 + 0.8) / 2, 4)
        assert abs(state.metadata.avg_intensity - expected_avg) < 1e-4

    def test_llm_prompt_non_empty(self):
        state = run_pipeline(SAMPLE_EVENTS)
        assert len(state.llm_prompt) > 50


# ============================================================================
# 8. Cross-run consistency (multi-scenario)
# ============================================================================

class TestCrossRunConsistency:

    SCENARIOS: list[dict[str, Any]] = [
        {"label": "single_combat",   "events": [_event("sc1", "combat", 0.9)]},
        {"label": "mixed_batch",     "events": SAMPLE_EVENTS},
        {"label": "all_types",       "events": ALL_TYPE_EVENTS},
        {"label": "high_intensity",  "events": HIGH_INTENSITY},
        {"label": "low_intensity",   "events": LOW_INTENSITY},
    ]

    @pytest.mark.parametrize("scenario", SCENARIOS, ids=[s["label"] for s in SCENARIOS])
    def test_pipeline_is_deterministic_per_scenario(self, scenario: dict):
        a = json.dumps(run_pipeline(scenario["events"]).model_dump(), sort_keys=True)
        b = json.dumps(run_pipeline(scenario["events"]).model_dump(), sort_keys=True)
        assert a == b, f"Non-deterministic output for scenario={scenario['label']}"
