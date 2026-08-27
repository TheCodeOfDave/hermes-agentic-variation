from __future__ import annotations

import hashlib
import json
from pathlib import Path
import pytest

from controller import ChildOutcome
from phase5_fixture import Phase5Fixture, SOURCES
from phase5_sandbox import SUCCESS_TRAILER, StageBResult, tree_hash
from storage import RunStore
from test_phase5_patch import member


class Lifecycle:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def run(self, **kwargs):
        self.requests.append(kwargs)
        return self.outcomes.pop(0)


class Sandbox:
    def __init__(self):
        self.calls = []

    def preflight(self):
        return {
            "image": "python:3.13-alpine@sha256:" + "a" * 64,
            "trusted_applier_hash": "b" * 64,
            "evaluator_hash": "c" * 64,
            "worker_bootstrap_hash": "d" * 64,
            "policy_hash": "e" * 64,
            "stage_a_command_id": "phase5.trusted-applier.v1",
            "stage_b_command_id": "phase5.immutable-evaluator.v1",
            "policy": {
                "network": "none",
                "memory_mib": 64,
                "cpus": 0.5,
                "pids_limit": 64,
                "user": "65534:65534",
                "tmpfs_bytes": 16777216,
                "stage_a_stdout_bytes": 98304,
                "stage_b_stdout_bytes": 4096,
                "worker_pipe_bytes": 65536,
                "stage_a_timeout_seconds": 30,
                "stage_b_timeout_seconds": 30,
            },
        }

    def run(self, run_id, baseline_dir, patchset, artifact_root):
        from phase5_sandbox import Phase5ExecutionResult

        self.calls.append(run_id)
        baselines = {p: (Path(baseline_dir) / p).read_text(encoding="utf-8") for p in SOURCES}
        outputs = patchset.apply(baselines)
        staged = artifact_root / run_id
        staged.mkdir(parents=True)
        for p, v in outputs.items():
            (staged / p).write_text(v, encoding="utf-8")
        return Phase5ExecutionResult(
            outputs,
            tree_hash(outputs),
            staged,
            self.preflight()["image"],
            "b" * 64,
            hashlib.sha256(
                (
                    Path(baseline_dir).parent / f"{run_id}-immutable" / "phase5_cases.json"
                ).read_bytes()
            ).hexdigest(),
            "c" * 64,
            "d" * 64,
            "e" * 64,
            hashlib.sha256(b"envelope").hexdigest(),
            hashlib.sha256(b"").hexdigest(),
            StageBResult(
                True,
                "PASS",
                0,
                hashlib.sha256(SUCCESS_TRAILER).hexdigest(),
                hashlib.sha256(b"").hexdigest(),
                True,
            ),
        )


def child():
    summary = json.dumps(
        {"patches": [member("calculator.py"), member("filters.py")], "rationale": "bounded"}
    )
    return ChildOutcome("SUCCEEDED", summary, "f" * 64, 1)


def subject(tmp_path, enabled=True):
    from phase5 import Phase5Controller

    lifecycle = Lifecycle([child()])
    sandbox = Sandbox()
    controller = Phase5Controller(
        store=RunStore(tmp_path / "runs.db"),
        lifecycle=lifecycle,
        fixture=Phase5Fixture(tmp_path / "runs"),
        sandbox=sandbox,
        artifact_root=tmp_path / "artifacts",
        enabled=enabled,
        wait_seconds=120,
    )
    return controller, lifecycle, sandbox


def test_phase5_controller_gate_success_and_todo_only_child(tmp_path):
    from phase5 import Phase5DisabledError

    disabled, _, _ = subject(tmp_path / "disabled", False)
    with pytest.raises(Phase5DisabledError):
        disabled.create_run(objective="patch", approval_receipt="approved")
    controller, lifecycle, sandbox = subject(tmp_path)
    created = controller.create_run(objective="patch", approval_receipt="approved")
    result = controller.patchset(created["run_id"])
    assert result["status"] == "succeeded" and result["eligible"] is True
    assert lifecycle.requests[0]["allowed_toolsets"] == ("todo",)
    assert controller.receipt(created["run_id"])["cleanup_status"] == "retained"
    assert sandbox.calls == [created["run_id"]]


def test_phase5_controller_rejects_foreign_run_before_effects(tmp_path):
    controller, lifecycle, sandbox = subject(tmp_path)
    with pytest.raises(ValueError, match="Variation Cycle"):
        controller.patchset("phase4-abcdef")
    assert lifecycle.requests == [] and sandbox.calls == []


def test_phase5_recovery_never_replays_effects_and_reports_inert_orphan(tmp_path):
    controller, lifecycle, sandbox = subject(tmp_path)
    created = controller.create_run(objective="patch", approval_receipt="approved")
    _, state = controller.store.load_run(created["run_id"])
    controller.store.transition(created["run_id"], "start_step", expected_revision=state.revision)
    controller.artifact_root.mkdir(parents=True)
    orphan = controller.artifact_root / f".{created['run_id']}.staging-999"
    orphan.mkdir()
    result = controller.reconcile(created["run_id"])
    assert result["action"] == "interrupted"
    assert result["orphans"] == [str(orphan)]
    assert lifecycle.requests == [] and sandbox.calls == [] and orphan.exists()


def test_phase5_fresh_baseline_drift_fails_before_stage_a(tmp_path):
    controller, lifecycle, sandbox = subject(tmp_path)
    created = controller.create_run(objective="patch", approval_receipt="approved")
    target = Path(created["repository_path"]) / "calculator.py"
    target.write_text(target.read_text(encoding="utf-8") + "# tampered\n", encoding="utf-8")

    result = controller.patchset(created["run_id"])

    assert result["error"] == "SANDBOX_FAILED"
    assert len(lifecycle.requests) == 1
    assert sandbox.calls == []


def test_phase5_receipt_binds_every_verified_literal_ceiling(tmp_path):
    from contracts import ContractValidationError, PatchSetReceipt

    controller, _, _ = subject(tmp_path)
    created = controller.create_run(objective="patch", approval_receipt="approved")
    assert controller.patchset(created["run_id"])["status"] == "succeeded"
    receipt = controller.receipt(created["run_id"])
    expected = {
        "memory_mib": 64,
        "cpus": 0.5,
        "pids_limit": 64,
        "tmpfs_bytes": 16777216,
        "user": "65534:65534",
        "stage_a_stdout_bytes": 98304,
        "stage_b_stdout_bytes": 4096,
        "worker_pipe_bytes": 65536,
        "stage_a_timeout_seconds": 30,
        "stage_b_timeout_seconds": 30,
        "wait_seconds": 120,
    }
    assert receipt["literal_ceilings"] == expected
    values = dict(receipt)
    values.pop("contract_version")
    for name in ("baseline_paths", "baseline_hashes", "changed_paths", "member_patch_hashes"):
        values[name] = tuple(values[name])
    values["literal_ceilings"] = {**expected, "memory_mib": 65}
    with pytest.raises(ContractValidationError, match="literal_ceilings"):
        PatchSetReceipt(**values)