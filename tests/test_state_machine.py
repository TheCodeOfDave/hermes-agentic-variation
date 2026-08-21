from __future__ import annotations

import pytest

from contracts import RunSpec
from state_machine import RunState, TransitionError, apply_transition

HEX_A = "a" * 64
HEX_B = "b" * 64


def run_spec(**overrides) -> RunSpec:
    values = {
        "run_id": "run-001",
        "target_root": "/workspace/example",
        "seed_digest": HEX_A,
        "objective": "Improve the fixture.",
        "exclusions": (),
        "evaluator_id": "fixture.score.v1",
        "evaluator_config": {},
        "correctness_predicates": ("tests_pass",),
        "score_keys": ("score",),
        "comparison": "maximize",
        "allowed_toolsets": ("file",),
        "network_policy": "disabled",
        "max_steps": 3,
        "max_wall_seconds": 60,
        "max_cost_usd": 2.0,
        "no_progress_limit": 2,
        "approval_receipt": "approved",
    }
    values.update(overrides)
    return RunSpec(**values)


def approved_state(spec: RunSpec) -> RunState:
    state = RunState.new(spec.identity)
    return apply_transition(state, "approve", spec)


def test_run_cannot_start_before_explicit_approval():
    spec = run_spec()
    state = RunState.new(spec.identity)

    with pytest.raises(TransitionError, match="start_step"):
        apply_transition(state, "start_step", spec)

    approved = apply_transition(state, "approve", spec)
    running = apply_transition(approved, "start_step", spec)
    assert running.status == "running"
    assert running.revision == 2


def test_eligible_evaluation_promotes_candidate_and_resets_stagnation():
    spec = run_spec()
    state = approved_state(spec)
    state = apply_transition(state, "start_step", spec)
    state = apply_transition(state, "candidate_ready", spec)
    state = apply_transition(
        state,
        "evaluation_eligible",
        spec,
        candidate_hash=HEX_B,
        cost_delta=0.25,
    )

    assert state.status == "ready"
    assert state.steps_used == 1
    assert state.consecutive_no_progress == 0
    assert state.best_candidate_hash == HEX_B
    assert state.cost_usd == 0.25


def test_repeated_ineligible_results_trigger_supervision_at_exact_limit():
    spec = run_spec(no_progress_limit=2)
    state = approved_state(spec)

    for expected_status in ("ready", "supervision_required"):
        state = apply_transition(state, "start_step", spec)
        state = apply_transition(state, "candidate_ready", spec)
        state = apply_transition(state, "evaluation_ineligible", spec)
        assert state.status == expected_status

    resumed = apply_transition(state, "supervisor_applied", spec)
    assert resumed.status == "ready"
    assert resumed.consecutive_no_progress == 0


def test_step_budget_terminates_after_recording_final_evaluation():
    spec = run_spec(max_steps=1)
    state = approved_state(spec)
    state = apply_transition(state, "start_step", spec)
    state = apply_transition(state, "candidate_ready", spec)
    state = apply_transition(state, "evaluation_ineligible", spec)

    assert state.status == "budget_exhausted"
    assert state.steps_used == 1


def test_cost_budget_fails_closed_without_starting_another_step():
    spec = run_spec(max_cost_usd=0.5)
    state = approved_state(spec)
    state = apply_transition(state, "start_step", spec)
    state = apply_transition(state, "child_failed", spec, cost_delta=0.5)

    assert state.status == "budget_exhausted"
    with pytest.raises(TransitionError, match="terminal"):
        apply_transition(state, "start_step", spec)


def test_pause_resume_preserves_the_only_safe_reentry_state():
    spec = run_spec()
    state = approved_state(spec)
    paused = apply_transition(state, "pause", spec)
    assert paused.status == "paused"
    assert paused.paused_from == "ready"

    resumed = apply_transition(paused, "resume", spec)
    assert resumed.status == "ready"
    assert resumed.paused_from is None


def test_run_spec_hash_mismatch_is_rejected():
    first = run_spec(run_id="run-one")
    second = run_spec(run_id="run-two")
    state = RunState.new(first.identity)

    with pytest.raises(TransitionError, match="RunSpec"):
        apply_transition(state, "approve", second)


def test_non_finite_cost_delta_is_rejected_before_state_change():
    spec = run_spec()
    state = approved_state(spec)
    state = apply_transition(state, "start_step", spec)

    for invalid in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(TransitionError, match="cost_delta"):
            apply_transition(state, "child_failed", spec, cost_delta=invalid)
