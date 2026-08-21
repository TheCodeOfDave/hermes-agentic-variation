from __future__ import annotations

import json
import hashlib

import pytest

from contracts import Candidate
from controller import ChildOutcome
from evaluator import FixtureOutcome
from phase2 import Phase2Controller, Phase2DisabledError
from storage import RunStore


class QueueLifecycle:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def run(self, **request):
        self.requests.append(request)
        return self.outcomes.pop(0)


def failed_child(error="provider failure"):
    return ChildOutcome(
        terminal_state="FAILED",
        summary=None,
        result_hash="d" * 64,
        api_calls=1,
        error=error,
    )


def supervisor_child(payload=None):
    payload = payload or {
        "directions": ["Try a strategy not present in recent failures"],
        "prohibited_repeats": ["baseline"],
    }
    return ChildOutcome(
        terminal_state="SUCCEEDED",
        summary=json.dumps(payload),
        result_hash="e" * 64,
        api_calls=1,
    )


def successful_variation(strategy="memoized_lookup"):
    return ChildOutcome(
        terminal_state="SUCCEEDED",
        summary=json.dumps({"strategy": strategy, "rationale": f"Use {strategy}"}),
        result_hash=("a" if strategy == "memoized_lookup" else "b") * 64,
        api_calls=1,
    )


def subject(tmp_path, outcomes, *, enabled=True):
    lifecycle = QueueLifecycle(outcomes)
    controller = Phase2Controller(
        store=RunStore(tmp_path / "phase2.db"),
        lifecycle=lifecycle,
        enabled=enabled,
        wait_seconds=30,
    )
    return controller, lifecycle


def test_phase2_gate_defaults_closed(tmp_path):
    controller, lifecycle = subject(tmp_path, [], enabled=False)

    with pytest.raises(Phase2DisabledError, match="phase2_enabled"):
        controller.create_run(objective="fixture", approval_receipt="approved")
    assert lifecycle.requests == []


def test_create_phase2_run_persists_initial_continuation_memory(tmp_path):
    controller, _ = subject(tmp_path, [])

    created = controller.create_run(objective="fixture", approval_receipt="approved")
    memory = controller.memory(created["run_id"])

    assert created["status"] == "ready"
    assert created["max_steps"] == 3
    assert memory["memory_revision"] == 1
    assert memory["run_status"] == "ready"
    assert memory["recent_candidate_hashes"] == []


def test_failed_step_requires_supervision_and_refreshes_memory(tmp_path):
    controller, _ = subject(tmp_path, [failed_child()])
    created = controller.create_run(objective="fixture", approval_receipt="approved")

    result = controller.step(created["run_id"])
    memory = controller.memory(created["run_id"])

    assert result["status"] == "supervision_required"
    assert memory["run_status"] == "supervision_required"
    assert "CHILD_FAILED" in memory["recent_failure_signatures"]
    assert memory["memory_revision"] == 2


def test_two_explicit_success_steps_create_distinct_lineage_and_bounded_memory(tmp_path):
    controller, lifecycle = subject(
        tmp_path,
        [successful_variation("single_pass"), successful_variation()],
    )
    created = controller.create_run(objective="fixture", approval_receipt="approved")

    first = controller.step(created["run_id"])
    second = controller.step(created["run_id"])
    memory = controller.memory(created["run_id"])

    assert first["status"] == "ready"
    assert second["status"] == "ready"
    assert len(set(memory["recent_candidate_hashes"])) == 2
    assert memory["tried_hypotheses"] == ["Use single_pass", "Use memoized_lookup"]
    assert len(lifecycle.requests) == 2


def test_regression_against_best_candidate_requires_supervision(tmp_path):
    controller, _ = subject(
        tmp_path,
        [successful_variation(), successful_variation("single_pass")],
    )
    created = controller.create_run(objective="fixture", approval_receipt="approved")
    first = controller.step(created["run_id"])

    second = controller.step(created["run_id"])

    assert first["eligible"] is True
    assert second["eligible"] is False
    assert second["status"] == "supervision_required"
    assert controller.status(created["run_id"])["best_candidate_hash"] == first["candidate_hash"]


def test_reconcile_running_without_durable_attempt_marks_interrupted(tmp_path):
    controller, _ = subject(tmp_path, [])
    created = controller.create_run(objective="fixture", approval_receipt="approved")
    _, state = controller.store.load_run(created["run_id"])
    controller.store.transition(created["run_id"], "start_step", expected_revision=state.revision)

    result = controller.reconcile(created["run_id"])

    assert result["action"] == "interrupted"
    assert result["status"] == "supervision_required"
    assert "INTERRUPTED" in controller.memory(created["run_id"])["recent_failure_signatures"]


def test_memory_read_reports_staleness_without_mutating_snapshot(tmp_path):
    controller, _ = subject(tmp_path, [])
    created = controller.create_run(objective="fixture", approval_receipt="approved")
    before = controller.store.load_memory(created["run_id"])
    _, state = controller.store.load_run(created["run_id"])
    controller.store.transition(created["run_id"], "start_step", expected_revision=state.revision)

    result = controller.memory(created["run_id"])
    after = controller.store.load_memory(created["run_id"])

    assert result["stale"] is True
    assert after == before


def test_reconcile_replays_durable_evaluation_after_prior_unrecorded_failure(tmp_path):
    controller, _ = subject(tmp_path, [failed_child(), supervisor_child()])
    created = controller.create_run(objective="fixture", approval_receipt="approved")
    controller.step(created["run_id"])
    controller.supervise(created["run_id"])
    spec, state = controller.store.load_run(created["run_id"])
    state = controller.store.transition(
        created["run_id"], "start_step", expected_revision=state.revision
    )
    artifact = json.dumps(
        {"strategy": "memoized_lookup", "rationale": "Use memoized lookup"},
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    candidate = Candidate(
        candidate_id=f"{created['run_id']}-candidate-2",
        run_spec_hash=spec.identity,
        parent_candidate_id=state.best_candidate_hash,
        artifact_digest=hashlib.sha256(artifact).hexdigest(),
        child_result_hash="a" * 64,
        changed_paths=("fixtures/strategy.json",),
        hypothesis="Use memoized lookup",
    )
    evaluation = controller.evaluator.evaluate(
        spec,
        candidate,
        baseline_scores={"operations": 10.0},
        outcome=FixtureOutcome(
            correctness={"strategy_allowed": True, "output_matches": True},
            scores={"operations": 5.0},
            evidence=artifact,
        ),
    )
    controller.store.record_attempt(created["run_id"], candidate, evaluation)

    result = controller.reconcile(created["run_id"])

    assert result["action"] == "evaluation_replayed"
    assert result["status"] == "ready"
    assert controller.status(created["run_id"])["best_candidate_hash"] == candidate.identity


def test_reconcile_is_noop_outside_active_states(tmp_path):
    controller, _ = subject(tmp_path, [])
    created = controller.create_run(objective="fixture", approval_receipt="approved")

    result = controller.reconcile(created["run_id"])

    assert result == {"run_id": created["run_id"], "status": "ready", "action": "noop"}


def test_reconcile_supervising_without_advice_fails_closed(tmp_path):
    controller, _ = subject(tmp_path, [failed_child()])
    created = controller.create_run(objective="fixture", approval_receipt="approved")
    controller.step(created["run_id"])
    _, state = controller.store.load_run(created["run_id"])
    controller.store.transition(
        created["run_id"], "start_supervisor", expected_revision=state.revision
    )

    result = controller.reconcile(created["run_id"])

    assert result["action"] == "supervisor_missing"
    assert result["status"] == "no_result"


def test_one_supervisor_advice_is_persisted_and_applied(tmp_path):
    controller, lifecycle = subject(tmp_path, [failed_child(), supervisor_child()])
    created = controller.create_run(objective="fixture", approval_receipt="approved")
    controller.step(created["run_id"])

    result = controller.supervise(created["run_id"])
    memory = controller.memory(created["run_id"])

    assert result["status"] == "ready"
    assert result["directions"] == ["Try a strategy not present in recent failures"]
    assert memory["supervisor_advice_hash"] == result["advice_hash"]
    assert len(controller.store.supervisor_advice(created["run_id"])) == 1
    request = lifecycle.requests[-1]
    assert request["allowed_toolsets"] == ("todo",)
    assert request["role"] == "leaf"
    assert "target" not in request
    assert "model" not in request
    assert "CHILD_FAILED" in request["context"]
    assert memory["run_spec_hash"] in request["context"]


def test_malformed_supervisor_output_fails_closed(tmp_path):
    controller, _ = subject(
        tmp_path,
        [failed_child(), supervisor_child({"directions": [], "prohibited_repeats": []})],
    )
    created = controller.create_run(objective="fixture", approval_receipt="approved")
    controller.step(created["run_id"])

    result = controller.supervise(created["run_id"])

    assert result["status"] == "no_result"
    assert result["error"] == "INVALID_SUPERVISOR_PAYLOAD"


def test_second_supervision_terminates_without_launching_another_supervisor(tmp_path):
    controller, lifecycle = subject(
        tmp_path,
        [failed_child(), supervisor_child(), failed_child("same failure")],
    )
    created = controller.create_run(objective="fixture", approval_receipt="approved")
    controller.step(created["run_id"])
    controller.supervise(created["run_id"])
    controller.step(created["run_id"])
    assert "Try a strategy not present in recent failures" in lifecycle.requests[-1]["context"]
    calls_before = len(lifecycle.requests)

    result = controller.supervise(created["run_id"])

    assert result["status"] == "no_result"
    assert result["error"] == "SUPERVISOR_BUDGET_EXHAUSTED"
    assert len(lifecycle.requests) == calls_before
