from __future__ import annotations

import json
from dataclasses import dataclass

import pytest

from controller import ChildOutcome, Phase1Controller, Phase1DisabledError
from storage import RunStore


@dataclass
class FakeLifecycle:
    outcome: ChildOutcome
    requests: list[dict]

    def run(self, **request):
        self.requests.append(request)
        return self.outcome


class RaisingLifecycle:
    def run(self, **request):
        raise ValueError("No active Hermes parent session is available.")


@pytest.fixture
def store(tmp_path):
    return RunStore(tmp_path / "phase1.db")


def controller(store, outcome, *, enabled=True):
    lifecycle = FakeLifecycle(outcome=outcome, requests=[])
    return (
        Phase1Controller(
            store=store,
            lifecycle=lifecycle,
            enabled=enabled,
            wait_seconds=30,
        ),
        lifecycle,
    )


def success_outcome(strategy="memoized_lookup"):
    return ChildOutcome(
        terminal_state="SUCCEEDED",
        summary=json.dumps(
            {
                "strategy": strategy,
                "rationale": "Use the lowest deterministic operation count.",
            }
        ),
        result_hash="b" * 64,
        api_calls=1,
    )


def test_phase1_gate_refuses_run_creation_when_backend_setting_is_off(store):
    subject, _ = controller(store, success_outcome(), enabled=False)

    with pytest.raises(Phase1DisabledError, match="phase1_enabled"):
        subject.create_run(objective="Choose one safe fixture strategy.", approval_receipt="approved")


def test_create_run_freezes_plugin_owned_fixture_and_approves_it(store):
    subject, _ = controller(store, success_outcome())

    created = subject.create_run(
        objective="Choose one safe fixture strategy.",
        approval_receipt="user-approved-phase1",
    )
    spec, state = store.load_run(created["run_id"])

    assert created["status"] == "ready"
    assert state.status == "ready"
    assert spec.target_root == "plugin://agentic-variation/phase1-fixture"
    assert spec.max_steps == 1
    assert spec.allowed_toolsets == ("todo",)
    assert spec.network_policy == "disabled"
    assert spec.evaluator_id == "phase1.strategy.v1"


def test_one_child_step_produces_candidate_evaluation_and_success_receipt(store):
    subject, lifecycle = controller(store, success_outcome())
    created = subject.create_run(
        objective="Choose one safe fixture strategy.", approval_receipt="approved"
    )

    result = subject.step(created["run_id"])

    assert result["status"] == "succeeded"
    assert result["eligible"] is True
    assert result["strategy"] == "memoized_lookup"
    assert result["scores"] == {"operations": 5.0}
    assert len(lifecycle.requests) == 1
    request = lifecycle.requests[0]
    assert request["allowed_toolsets"] == ("todo",)
    assert request["role"] == "leaf"
    assert request["wait_seconds"] == 30
    assert "Return exactly one JSON object" in request["goal"]
    assert "network" in request["context"].lower()

    lineage = subject.lineage(created["run_id"])
    assert len(lineage["candidates"]) == 1
    assert len(lineage["evaluations"]) == 1
    assert lineage["evaluations"][0]["eligible"] is True
    child_events = [
        event for event in store.events(created["run_id"]) if event["event"] == "child_result"
    ]
    assert child_events[0]["payload"]["api_calls"] == 1


def test_invalid_child_payload_fails_closed_without_candidate(store):
    subject, _ = controller(
        store,
        ChildOutcome(
            terminal_state="SUCCEEDED",
            summary="not-json",
            result_hash="c" * 64,
            api_calls=1,
        ),
    )
    created = subject.create_run(objective="fixture", approval_receipt="approved")

    result = subject.step(created["run_id"])

    assert result["status"] == "budget_exhausted"
    assert result["eligible"] is False
    assert result["error"] == "INVALID_CHILD_PAYLOAD"
    assert subject.lineage(created["run_id"])["candidates"] == []


def test_unlisted_strategy_is_ineligible_and_preserved_as_evidence(store):
    subject, _ = controller(store, success_outcome("arbitrary_python"))
    created = subject.create_run(objective="fixture", approval_receipt="approved")

    result = subject.step(created["run_id"])

    assert result["status"] == "budget_exhausted"
    assert result["eligible"] is False
    assert result["error"] == "STRATEGY_NOT_ALLOWED"
    assert subject.lineage(created["run_id"])["candidates"] == []


def test_failed_child_is_terminal_and_does_not_create_candidate(store):
    subject, _ = controller(
        store,
        ChildOutcome(
            terminal_state="FAILED",
            summary=None,
            result_hash="d" * 64,
            api_calls=1,
            error="provider failure",
        ),
    )
    created = subject.create_run(objective="fixture", approval_receipt="approved")

    result = subject.step(created["run_id"])

    assert result["status"] == "budget_exhausted"
    assert result["error"] == "CHILD_FAILED"
    assert subject.lineage(created["run_id"])["candidates"] == []


def test_lifecycle_launch_error_closes_run_instead_of_stranding_running_state(store):
    subject = Phase1Controller(
        store=store,
        lifecycle=RaisingLifecycle(),
        enabled=True,
        wait_seconds=30,
    )
    created = subject.create_run(objective="fixture", approval_receipt="approved")

    result = subject.step(created["run_id"])

    assert result["status"] == "budget_exhausted"
    assert result["error"] == "CHILD_LAUNCH_ERROR"
    assert subject.status(created["run_id"])["status"] == "budget_exhausted"


def test_cancel_before_step_closes_run_without_launching_child(store):
    subject, lifecycle = controller(store, success_outcome())
    created = subject.create_run(objective="fixture", approval_receipt="approved")

    result = subject.cancel(created["run_id"])

    assert result["status"] == "cancelled"
    assert lifecycle.requests == []


def test_cancel_refuses_to_claim_in_flight_child_was_stopped(store):
    subject, _ = controller(store, success_outcome())
    created = subject.create_run(objective="fixture", approval_receipt="approved")
    _, state = store.load_run(created["run_id"])
    store.transition(created["run_id"], "start_step", expected_revision=state.revision)

    with pytest.raises(ValueError, match="in-flight"):
        subject.cancel(created["run_id"])
