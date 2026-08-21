from __future__ import annotations

import json

import pytest

from contracts import RunSpec
from controller import ChildOutcome
from phase3 import Phase3Controller, Phase3DisabledError
from phase3_workspace import Phase3Workspace
from storage import RunStore


class QueueLifecycle:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def run(self, **request):
        self.requests.append(request)
        return self.outcomes.pop(0)


class CrashAfterEvidenceStore(RunStore):
    def __init__(self, database_path):
        super().__init__(database_path)
        self.crash_on_candidate_ready = True

    def transition(self, run_id, event, **kwargs):
        if event == "candidate_ready" and self.crash_on_candidate_ready:
            self.crash_on_candidate_ready = False
            raise RuntimeError("simulated crash after durable mutation evidence")
        return super().transition(run_id, event, **kwargs)


def child(mutation="filter_even", rationale="Use the trusted even-filter template"):
    return ChildOutcome(
        terminal_state="SUCCEEDED",
        summary=json.dumps({"mutation": mutation, "rationale": rationale}),
        result_hash="a" * 64,
        api_calls=1,
    )


def subject(tmp_path, outcomes, *, enabled=True):
    lifecycle = QueueLifecycle(outcomes)
    workspace = Phase3Workspace(tmp_path / "phase3-runs", test_timeout_seconds=10)
    controller = Phase3Controller(
        store=RunStore(tmp_path / "runs.db"),
        lifecycle=lifecycle,
        workspace=workspace,
        enabled=enabled,
        wait_seconds=30,
    )
    return controller, lifecycle, workspace


def test_phase3_gate_defaults_closed_before_repository_creation(tmp_path):
    controller, lifecycle, workspace = subject(tmp_path, [], enabled=False)

    with pytest.raises(Phase3DisabledError, match="phase3_enabled"):
        controller.create_run(objective="fixture", approval_receipt="approved")

    assert lifecycle.requests == []
    assert not workspace.root.exists()


def test_invalid_create_input_is_rejected_before_repository_creation(tmp_path):
    controller, _, workspace = subject(tmp_path, [])

    for objective, approval in (("", "approved"), ("fixture", ""), ("x" * 1001, "ok")):
        with pytest.raises(ValueError):
            controller.create_run(objective=objective, approval_receipt=approval)

    assert not workspace.root.exists()


def test_create_phase3_run_builds_plugin_owned_no_commit_repository(tmp_path):
    controller, _, workspace = subject(tmp_path, [])

    created = controller.create_run(objective="fix fixture", approval_receipt="approved")

    assert created["status"] == "ready"
    assert created["repository_id"].startswith("phase3-")
    repo = workspace.root / created["repository_id"]
    assert str(repo) == created["repository_path"]
    assert workspace.git_facts(repo) == {"commit_count": 0, "remotes": []}
    spec, _ = controller.store.load_run(created["run_id"])
    assert spec.allowed_toolsets == ("todo",)
    assert spec.network_policy == "disabled"
    assert spec.target_root == str(repo)


def test_successful_canary_mutates_trusted_file_and_records_receipt(tmp_path):
    controller, lifecycle, workspace = subject(tmp_path, [child()])
    created = controller.create_run(objective="fix fixture", approval_receipt="approved")

    result = controller.mutate(created["run_id"])
    receipt = controller.receipt(created["run_id"])

    assert result["status"] == "succeeded"
    assert result["eligible"] is True
    assert result["mutation"] == "filter_even"
    assert result["tests_passed"] is True
    assert receipt["cleanup_status"] == "retained"
    assert receipt["repository_retained"] is True
    assert receipt["command_id"] == "phase3.python-unittest.v1"
    assert receipt["changed_paths"] == ["calculator.py"]
    assert len(controller.store.mutation_receipts(created["run_id"])) == 1
    request = lifecycle.requests[0]
    assert request["allowed_toolsets"] == ("todo",)
    assert "file" not in request["allowed_toolsets"]
    assert "terminal" not in request["allowed_toolsets"]
    assert "working_directory" not in request
    repo = workspace.root / created["repository_id"]
    assert "number % 2 == 0" in (repo / "calculator.py").read_text(encoding="utf-8")
    assert workspace.git_facts(repo) == {"commit_count": 0, "remotes": []}


def test_incorrect_closed_mutation_is_persisted_but_ineligible(tmp_path):
    controller, _, _ = subject(tmp_path, [child("filter_odd")])
    created = controller.create_run(objective="fix fixture", approval_receipt="approved")

    result = controller.mutate(created["run_id"])

    assert result["status"] == "budget_exhausted"
    assert result["eligible"] is False
    assert result["tests_passed"] is False
    assert controller.receipt(created["run_id"])["mutation"] == "filter_odd"


def test_malformed_or_baseline_child_output_never_mutates_repository(tmp_path):
    malformed = ChildOutcome(
        terminal_state="SUCCEEDED",
        summary='{"mutation":"baseline","rationale":"no change"}',
        result_hash="b" * 64,
        api_calls=1,
    )
    controller, _, workspace = subject(tmp_path, [malformed])
    created = controller.create_run(objective="fix fixture", approval_receipt="approved")
    repo = workspace.root / created["repository_id"]
    before = workspace.tree_hash(repo)

    result = controller.mutate(created["run_id"])

    assert result["status"] == "budget_exhausted"
    assert result["error"] == "MUTATION_NOT_ALLOWED"
    assert workspace.tree_hash(repo) == before
    assert controller.store.mutation_receipts(created["run_id"]) == []


def test_reconcile_interrupted_run_does_not_rerun_child_or_mutation(tmp_path):
    controller, lifecycle, workspace = subject(tmp_path, [])
    created = controller.create_run(objective="fix fixture", approval_receipt="approved")
    _, state = controller.store.load_run(created["run_id"])
    controller.store.transition(created["run_id"], "start_step", expected_revision=state.revision)
    repo = workspace.root / created["repository_id"]
    before = workspace.tree_hash(repo)

    result = controller.reconcile(created["run_id"])

    assert result["action"] == "interrupted"
    assert result["status"] == "budget_exhausted"
    assert lifecycle.requests == []
    assert workspace.tree_hash(repo) == before


def test_reconcile_replays_atomic_mutation_evidence_without_rerunning_effects(tmp_path):
    lifecycle = QueueLifecycle([child()])
    workspace = Phase3Workspace(tmp_path / "phase3-runs", test_timeout_seconds=10)
    store = CrashAfterEvidenceStore(tmp_path / "runs.db")
    controller = Phase3Controller(
        store=store,
        lifecycle=lifecycle,
        workspace=workspace,
        enabled=True,
        wait_seconds=30,
    )
    created = controller.create_run(objective="fix fixture", approval_receipt="approved")

    with pytest.raises(RuntimeError, match="simulated crash"):
        controller.mutate(created["run_id"])
    calls_before = len(lifecycle.requests)
    receipt = controller.receipt(created["run_id"])

    result = controller.reconcile(created["run_id"])

    assert result["action"] == "evaluation_replayed"
    assert result["status"] == "succeeded"
    assert len(lifecycle.requests) == calls_before
    assert controller.store.load_run(created["run_id"])[1].best_candidate_hash == receipt[
        "candidate_hash"
    ]


def test_phase3_mutation_rejects_foreign_run_before_child_or_state_change(tmp_path):
    controller, lifecycle, _ = subject(tmp_path, [child()])
    foreign = RunSpec(
        run_id="phase2-foreign",
        target_root="plugin://agentic-variation/phase2-fixture",
        seed_digest="a" * 64,
        objective="foreign fixture",
        exclusions=(),
        evaluator_id="phase2.fixture",
        evaluator_config={},
        correctness_predicates=("tests_pass",),
        score_keys=("score",),
        comparison="minimize",
        allowed_toolsets=("todo",),
        network_policy="disabled",
        max_steps=1,
        max_wall_seconds=30,
        max_cost_usd=1.0,
        no_progress_limit=1,
        approval_receipt="approved",
    )
    state = controller.store.create_run(foreign)
    controller.store.transition(foreign.run_id, "approve", expected_revision=state.revision)

    with pytest.raises(ValueError, match="Phase 3 run"):
        controller.mutate(foreign.run_id)

    assert lifecycle.requests == []
    assert controller.store.load_run(foreign.run_id)[1].status == "ready"
