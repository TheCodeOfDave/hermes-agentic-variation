from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from controller import ChildOutcome
from phase3_workspace import Phase3Workspace
from phase4 import Phase4Controller, Phase4DisabledError

from phase4_sandbox import DEFAULT_IMAGE, SandboxResult, SandboxUnavailable
from storage import RunStore

PATCH = """--- a/calculator.py
+++ b/calculator.py
@@ -1,2 +1,2 @@
 def sum_even(numbers):
-    return sum(numbers)
+    return sum(number for number in numbers if number % 2 == 0)
"""
POLICY = {
    "network": "none",
    "read_only_root": True,
    "cap_drop": "ALL",
    "no_new_privileges": True,
    "memory_mib": 64,
    "cpus": 0.5,
    "pids_limit": 64,
    "user": "65534:65534",
    "tmpfs_bytes": 16777216,
}


class QueueLifecycle:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.requests = []

    def run(self, **request):
        self.requests.append(request)
        return self.outcomes.pop(0)


class CrashAfterSandboxReceiptStore(RunStore):
    def __init__(self, database_path):
        super().__init__(database_path)
        self.crash = True

    def transition(self, run_id, event, **kwargs):
        if event == "candidate_ready" and self.crash:
            self.crash = False
            raise RuntimeError("simulated crash after sandbox receipt")
        return super().transition(run_id, event, **kwargs)


class FakeSandbox:
    def __init__(self, *, tests_passed=True, unavailable=False):
        self.tests_passed = tests_passed
        self.unavailable = unavailable
        self.calls = []

    def preflight(self):
        if self.unavailable:
            raise SandboxUnavailable("pinned image unavailable")
        return {"image": DEFAULT_IMAGE, "runner_hash": "a" * 64, "policy": POLICY}

    def run(self, run_id, baseline_dir, patch):
        self.calls.append((run_id, Path(baseline_dir), patch))
        source = patch.apply((Path(baseline_dir) / "calculator.py").read_text(encoding="utf-8"))
        patch_path = Path(baseline_dir).parent / "patches" / run_id / "input.patch"
        patch_path.parent.mkdir(parents=True)
        patch_path.write_text(patch.raw, encoding="utf-8")
        return SandboxResult(
            candidate_source=source,
            candidate_source_hash=hashlib.sha256(source.encode()).hexdigest(),
            candidate_tree_hash="b" * 64,
            command_id="phase4.python-unittest.v1",
            exit_code=0 if self.tests_passed else 1,
            tests_passed=self.tests_passed,
            stdout_hash="c" * 64,
            stderr_hash="d" * 64,
            policy=POLICY,
            patch_hash=patch.identity,
            patch_path=patch_path,
            image=DEFAULT_IMAGE,
            runner_hash="a" * 64,
        )


class TamperedSandbox(FakeSandbox):
    def run(self, run_id, baseline_dir, patch):
        result = super().run(run_id, baseline_dir, patch)
        return SandboxResult(**{**result.__dict__, "runner_hash": "f" * 64})


def child(patch=PATCH):
    return ChildOutcome(
        terminal_state="SUCCEEDED",
        summary=json.dumps({"patch": patch, "rationale": "Apply the even filter"}),
        result_hash="e" * 64,
        api_calls=1,
    )


def subject(tmp_path, outcomes, *, enabled=True, sandbox=None):
    lifecycle = QueueLifecycle(outcomes)
    workspace = Phase3Workspace(
        tmp_path / "phase4-runs", test_timeout_seconds=10, repository_prefix="phase4"
    )
    controller = Phase4Controller(
        store=RunStore(tmp_path / "runs.db"),
        lifecycle=lifecycle,
        workspace=workspace,
        sandbox=sandbox or FakeSandbox(),
        artifact_root=tmp_path / "phase4-artifacts",
        enabled=enabled,
        wait_seconds=30,
    )
    return controller, lifecycle, workspace


def test_phase4_gate_and_sandbox_preflight_happen_before_repository_creation(tmp_path):
    controller, lifecycle, workspace = subject(tmp_path, [], enabled=False)
    with pytest.raises(Phase4DisabledError):
        controller.create_run(objective="patch", approval_receipt="approved")
    assert not workspace.root.exists()
    assert lifecycle.requests == []

    controller, lifecycle, workspace = subject(
        tmp_path / "unavailable", [], sandbox=FakeSandbox(unavailable=True)
    )
    with pytest.raises(SandboxUnavailable):
        controller.create_run(objective="patch", approval_receipt="approved")
    assert not workspace.root.exists()
    assert lifecycle.requests == []


def test_phase4_success_exports_sandbox_candidate_without_mutating_baseline(tmp_path):
    controller, lifecycle, workspace = subject(tmp_path, [child()])
    created = controller.create_run(objective="patch", approval_receipt="approved")
    baseline = Path(created["repository_path"]) / "calculator.py"
    before = baseline.read_text(encoding="utf-8")

    result = controller.patch(created["run_id"])
    receipt = controller.receipt(created["run_id"])

    assert result["status"] == "succeeded"
    assert result["tests_passed"] is True
    assert baseline.read_text(encoding="utf-8") == before
    artifact = Path(result["artifact_path"])
    assert artifact.is_file()
    assert "number % 2 == 0" in artifact.read_text(encoding="utf-8")
    assert receipt["network_policy"] == "none"
    assert receipt["image"] == DEFAULT_IMAGE
    assert receipt["artifact_retained"] is True
    request = lifecycle.requests[0]
    assert request["allowed_toolsets"] == ("todo",)
    assert "file" not in request["allowed_toolsets"]
    assert "terminal" not in request["allowed_toolsets"]
    assert workspace.git_facts(created["repository_path"]) == {"commit_count": 0, "remotes": []}


def test_invalid_patch_never_launches_sandbox_or_writes_artifact(tmp_path):
    sandbox = FakeSandbox()
    controller, _, _ = subject(tmp_path, [child("--- a/other.py\n+++ b/other.py\n")], sandbox=sandbox)
    created = controller.create_run(objective="patch", approval_receipt="approved")

    result = controller.patch(created["run_id"])

    assert result["status"] == "budget_exhausted"
    assert result["error"] == "INVALID_PATCH"
    assert sandbox.calls == []
    assert controller.store.sandbox_receipts(created["run_id"]) == []


def test_tampered_sandbox_identity_is_rejected_before_artifact_export(tmp_path):
    controller, _, _ = subject(tmp_path, [child()], sandbox=TamperedSandbox())
    created = controller.create_run(objective="patch", approval_receipt="approved")

    with pytest.raises(Exception, match="sandbox identity"):
        controller.patch(created["run_id"])

    assert not (controller.artifact_root / created["run_id"]).exists()
    assert controller.store.sandbox_receipts(created["run_id"]) == []


def test_failed_sandbox_tests_record_ineligible_receipt(tmp_path):
    controller, _, _ = subject(tmp_path, [child()], sandbox=FakeSandbox(tests_passed=False))
    created = controller.create_run(objective="patch", approval_receipt="approved")

    result = controller.patch(created["run_id"])

    assert result["status"] == "budget_exhausted"
    assert result["eligible"] is False
    assert controller.receipt(created["run_id"])["tests_passed"] is False


def test_reconcile_without_receipt_never_reruns_child_or_sandbox(tmp_path):
    sandbox = FakeSandbox()
    controller, lifecycle, _ = subject(tmp_path, [], sandbox=sandbox)
    created = controller.create_run(objective="patch", approval_receipt="approved")
    _, state = controller.store.load_run(created["run_id"])
    controller.store.transition(created["run_id"], "start_step", expected_revision=state.revision)

    result = controller.reconcile(created["run_id"])

    assert result["action"] == "interrupted"
    assert result["status"] == "budget_exhausted"
    assert lifecycle.requests == []
    assert sandbox.calls == []


def test_reconcile_replays_atomic_sandbox_receipt_without_rerunning_effects(tmp_path):
    lifecycle = QueueLifecycle([child()])
    workspace = Phase3Workspace(
        tmp_path / "phase4-runs", test_timeout_seconds=10, repository_prefix="phase4"
    )
    sandbox = FakeSandbox()
    controller = Phase4Controller(
        store=CrashAfterSandboxReceiptStore(tmp_path / "runs.db"),
        lifecycle=lifecycle,
        workspace=workspace,
        sandbox=sandbox,
        artifact_root=tmp_path / "phase4-artifacts",
        enabled=True,
        wait_seconds=30,
    )
    created = controller.create_run(objective="patch", approval_receipt="approved")

    with pytest.raises(RuntimeError, match="simulated crash"):
        controller.patch(created["run_id"])
    calls_before = len(sandbox.calls)
    receipt = controller.receipt(created["run_id"])

    result = controller.reconcile(created["run_id"])

    assert result["action"] == "evaluation_replayed"
    assert result["status"] == "succeeded"
    assert len(sandbox.calls) == calls_before
    assert controller.store.load_run(created["run_id"])[1].best_candidate_hash == receipt[
        "candidate_hash"
    ]
