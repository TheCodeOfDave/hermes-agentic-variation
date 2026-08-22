from __future__ import annotations

import hashlib
import json
import os
import secrets
from pathlib import Path
from typing import Any

try:
    from .contracts import Candidate, RunSpec, SandboxReceipt
    from .controller import ChildLifecycle
    from .evaluator import FixtureEvaluator, FixtureOutcome
    from .phase3_workspace import Phase3Workspace
    from .phase4_patch import PatchValidationError, ValidatedPatch
    from .phase4_sandbox import DockerSandbox, SandboxUnavailable, SandboxViolation
    from .storage import RunStore
except ImportError:
    from contracts import Candidate, RunSpec, SandboxReceipt
    from controller import ChildLifecycle
    from evaluator import FixtureEvaluator, FixtureOutcome
    from phase3_workspace import Phase3Workspace
    from phase4_patch import PatchValidationError, ValidatedPatch
    from phase4_sandbox import DockerSandbox, SandboxUnavailable, SandboxViolation
    from storage import RunStore

_PHASE4_EVALUATOR = "phase4.sandbox-unittest.v1"


class Phase4DisabledError(RuntimeError):
    """Raised when executable Phase 4 behavior is disabled in backend config."""


def _identity(payload: dict[str, Any]) -> str:
    encoded = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


class Phase4Controller:
    """Apply one model-authored patch only inside a fixed Docker sandbox."""

    def __init__(
        self,
        *,
        store: RunStore,
        lifecycle: ChildLifecycle,
        workspace: Phase3Workspace,
        sandbox: DockerSandbox,
        artifact_root: str | Path,
        enabled: bool,
        wait_seconds: int,
    ) -> None:
        self.store = store
        self.lifecycle = lifecycle
        self.workspace = workspace
        self.sandbox = sandbox
        self.artifact_root = Path(artifact_root).resolve()
        self.enabled = enabled
        self.wait_seconds = wait_seconds
        self.evaluator = FixtureEvaluator()

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise Phase4DisabledError(
                "Phase 4 execution is disabled; set backend phase4_enabled=true explicitly."
            )

    def _load_phase4_run(self, run_id: str):
        if not isinstance(run_id, str) or not run_id.startswith("phase4-"):
            raise ValueError("run_id must identify a Phase 4 run")
        spec, state = self.store.load_run(run_id)
        target = Path(spec.target_root).resolve()
        if (
            spec.evaluator_id != _PHASE4_EVALUATOR
            or target.name != run_id
            or target.parent != self.workspace.root
        ):
            raise ValueError("run_id must identify a Phase 4 run")
        return spec, state

    def create_run(self, *, objective: str, approval_receipt: str) -> dict[str, Any]:
        self._require_enabled()
        for name, value in (("objective", objective), ("approval_receipt", approval_receipt)):
            if not isinstance(value, str) or not value.strip() or len(value) > 1000:
                raise ValueError(f"{name} must be a non-empty string of at most 1000 characters")
        preflight = self.sandbox.preflight()
        run_id = f"phase4-{secrets.token_hex(8)}"
        repo = self.workspace.create(run_id)
        baseline_tree_hash = self.workspace.tree_hash(repo)
        policy_hash = _identity(dict(preflight["policy"]))
        spec = RunSpec(
            run_id=run_id,
            target_root=str(repo),
            seed_digest=baseline_tree_hash,
            objective=objective,
            exclusions=(
                "No patch execution outside pinned Docker sandbox",
                "No child file or terminal tools",
                "No network, package installation, credentials, or host Docker socket exposure",
                "No commits, remotes, pushes, deployment, cleanup, or deletion",
                "No autonomous recurrence",
            ),
            evaluator_id=_PHASE4_EVALUATOR,
            evaluator_config={
                "image": preflight["image"],
                "runner_hash": preflight["runner_hash"],
                "policy_hash": policy_hash,
                "command_id": SandboxReceipt.COMMAND_ID,
                "target": "calculator.py",
            },
            correctness_predicates=("tests_pass", "output_matches"),
            score_keys=("test_failures",),
            comparison="minimize",
            allowed_toolsets=("todo",),
            network_policy="disabled",
            max_steps=1,
            max_wall_seconds=self.wait_seconds,
            max_cost_usd=1.0,
            no_progress_limit=1,
            approval_receipt=approval_receipt,
        )
        state = self.store.create_run(spec)
        state = self.store.transition(run_id, "approve", expected_revision=state.revision)
        self.store.record_observation(
            run_id,
            "sandbox_preflight",
            {
                "image": preflight["image"],
                "runner_hash": preflight["runner_hash"],
                "policy_hash": policy_hash,
                "baseline_tree_hash": baseline_tree_hash,
            },
        )
        return {
            "run_id": run_id,
            "repository_path": str(repo),
            "run_spec_hash": spec.identity,
            "baseline_tree_hash": baseline_tree_hash,
            "image": preflight["image"],
            "runner_hash": preflight["runner_hash"],
            "policy_hash": policy_hash,
            "status": state.status,
        }

    def patch(self, run_id: str) -> dict[str, Any]:
        self._require_enabled()
        spec, state = self._load_phase4_run(run_id)
        state = self.store.transition(run_id, "start_step", expected_revision=state.revision)
        try:
            child = self.lifecycle.run(
                goal=(
                    "Return exactly one JSON object with string keys patch and rationale. "
                    "Patch calculator.py so sum_even([1,2,3,4,5,6]) returns 12. "
                    "Use exactly one unified-diff hunk and no other file."
                ),
                context=(
                    "You have todo only: no file, terminal, Docker, network, credentials, or host access. "
                    "Baseline source is: def sum_even(numbers): newline four spaces return sum(numbers). "
                    "The controller validates your patch, and only a pinned networkless sandbox applies it."
                ),
                role="leaf",
                correlation_id=f"{run_id}:patch:1",
                allowed_toolsets=("todo",),
                wait_seconds=self.wait_seconds,
            )
        except Exception:
            return self._fail_attempt(run_id, state.revision, "CHILD_LAUNCH_ERROR")
        self.store.record_observation(
            run_id,
            "child_result",
            {
                "terminal_state": child.terminal_state,
                "result_hash": child.result_hash,
                "api_calls": child.api_calls,
            },
        )
        if child.terminal_state != "SUCCEEDED" or not child.summary:
            return self._fail_attempt(run_id, state.revision, "CHILD_FAILED")
        parsed = self._parse_child_payload(child.summary)
        if parsed is None:
            return self._fail_attempt(run_id, state.revision, "INVALID_CHILD_PAYLOAD")
        patch_text, rationale = parsed
        try:
            validated = ValidatedPatch.parse(patch_text)
        except PatchValidationError:
            return self._fail_attempt(run_id, state.revision, "INVALID_PATCH")
        try:
            sandbox_result = self.sandbox.run(run_id, spec.target_root, validated)
        except (SandboxUnavailable, SandboxViolation):
            return self._fail_attempt(run_id, state.revision, "SANDBOX_FAILED")

        policy_hash = _identity(sandbox_result.policy)
        if (
            sandbox_result.image != spec.evaluator_config["image"]
            or sandbox_result.runner_hash != spec.evaluator_config["runner_hash"]
            or policy_hash != spec.evaluator_config["policy_hash"]
            or sandbox_result.patch_hash != validated.identity
            or sandbox_result.candidate_source_hash
            != hashlib.sha256(sandbox_result.candidate_source.encode("utf-8")).hexdigest()
        ):
            raise SandboxViolation("sandbox identity differs from approved RunSpec")
        artifact_relative = f"phase4-artifacts/{run_id}/calculator.py"
        artifact_path = self._write_artifact(run_id, sandbox_result.candidate_source)
        candidate = Candidate(
            candidate_id=f"{run_id}-candidate-1",
            run_spec_hash=spec.identity,
            parent_candidate_id=None,
            artifact_digest=sandbox_result.candidate_tree_hash,
            child_result_hash=child.result_hash,
            changed_paths=("calculator.py",),
            hypothesis=rationale,
        )
        evidence = json.dumps(
            {
                "image": sandbox_result.image,
                "runner_hash": sandbox_result.runner_hash,
                "patch_hash": sandbox_result.patch_hash,
                "tree_hash": sandbox_result.candidate_tree_hash,
                "command_id": sandbox_result.command_id,
                "exit_code": sandbox_result.exit_code,
                "stdout_hash": sandbox_result.stdout_hash,
                "stderr_hash": sandbox_result.stderr_hash,
            },
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        evaluation = self.evaluator.evaluate(
            spec,
            candidate,
            baseline_scores={"test_failures": 1.0},
            outcome=FixtureOutcome(
                correctness={
                    "tests_pass": sandbox_result.tests_passed,
                    "output_matches": True,
                },
                scores={"test_failures": 0.0 if sandbox_result.tests_passed else 1.0},
                evidence=evidence,
            ),
        )
        receipt = SandboxReceipt(
            receipt_id=f"{run_id}-sandbox-receipt-1",
            run_spec_hash=spec.identity,
            candidate_hash=candidate.identity,
            evaluation_hash=evaluation.identity,
            image=sandbox_result.image,
            runner_hash=sandbox_result.runner_hash,
            baseline_tree_hash=spec.seed_digest,
            patch_hash=sandbox_result.patch_hash,
            output_tree_hash=sandbox_result.candidate_tree_hash,
            output_source_hash=sandbox_result.candidate_source_hash,
            policy_hash=policy_hash,
            command_id=sandbox_result.command_id,
            exit_code=sandbox_result.exit_code,
            tests_passed=sandbox_result.tests_passed,
            stdout_hash=sandbox_result.stdout_hash,
            stderr_hash=sandbox_result.stderr_hash,
            artifact_relative_path=artifact_relative,
            network_policy="none",
            artifact_retained=True,
            cleanup_status="retained",
        )

        self.store.record_sandbox_attempt(run_id, candidate, evaluation, receipt)
        self.store.record_observation(
            run_id,
            "sandbox_result",
            {
                "receipt_hash": receipt.identity,
                "patch_hash": validated.identity,
                "output_tree_hash": sandbox_result.candidate_tree_hash,
                "artifact_relative_path": artifact_relative,
            },
        )
        state = self.store.transition(
            run_id, "candidate_ready", expected_revision=state.revision
        )
        event = "evaluation_eligible" if evaluation.eligible else "evaluation_ineligible"
        state = self.store.transition(
            run_id,
            event,
            expected_revision=state.revision,
            candidate_hash=candidate.identity if evaluation.eligible else None,
        )
        return {
            "run_id": run_id,
            "status": state.status,
            "eligible": evaluation.eligible,
            "tests_passed": sandbox_result.tests_passed,
            "exit_code": sandbox_result.exit_code,
            "patch_hash": validated.identity,
            "candidate_hash": candidate.identity,
            "evaluation_hash": evaluation.identity,
            "receipt_hash": receipt.identity,
            "artifact_path": str(artifact_path),
            "baseline_unchanged": self.workspace.tree_hash(spec.target_root) == spec.seed_digest,
            "cleanup_status": "retained",
        }

    def receipt(self, run_id: str) -> dict[str, Any]:
        self._load_phase4_run(run_id)
        receipts = self.store.sandbox_receipts(run_id)
        if not receipts:
            raise ValueError("sandbox receipt is not available")
        return receipts[-1]

    def reconcile(self, run_id: str) -> dict[str, Any]:
        self._require_enabled()
        _, state = self._load_phase4_run(run_id)
        if state.status not in {"running", "evaluating"}:
            return {"run_id": run_id, "status": state.status, "action": "noop"}
        lineage = self.store.lineage(run_id)
        receipts = self.store.sandbox_receipts(run_id)
        applied = sum(
            event["event"] in {"evaluation_eligible", "evaluation_ineligible"}
            for event in self.store.events(run_id)
        )
        if len(lineage["evaluations"]) > applied and len(receipts) > applied:
            candidate_payload = lineage["candidates"][-1]
            evaluation_payload = lineage["evaluations"][-1]
            candidate_hash = _identity(candidate_payload)
            if state.status == "running":
                state = self.store.transition(
                    run_id, "candidate_ready", expected_revision=state.revision
                )
            event = (
                "evaluation_eligible"
                if evaluation_payload.get("eligible") is True
                else "evaluation_ineligible"
            )
            state = self.store.transition(
                run_id,
                event,
                expected_revision=state.revision,
                candidate_hash=candidate_hash if event == "evaluation_eligible" else None,
            )
            return {"run_id": run_id, "status": state.status, "action": "evaluation_replayed"}
        event = "interrupt" if state.status == "running" else "evaluation_missing"
        state = self.store.transition(run_id, event, expected_revision=state.revision)
        action = "interrupted" if event == "interrupt" else "evaluation_missing"
        self.store.record_observation(run_id, action, {"classification": action.upper()})
        return {"run_id": run_id, "status": state.status, "action": action}

    def cancel(self, run_id: str) -> dict[str, Any]:
        self._require_enabled()
        _, state = self._load_phase4_run(run_id)
        if state.status in {"running", "evaluating"}:
            raise ValueError("in-flight Phase 4 cancellation is not claimed")
        state = self.store.transition(run_id, "cancel", expected_revision=state.revision)
        return {"run_id": run_id, "status": state.status, "cleanup_status": "retained"}

    def _write_artifact(self, run_id: str, source: str) -> Path:
        if self.artifact_root.exists() and self.artifact_root.is_symlink():
            raise SandboxViolation("artifact root must not be a symlink")
        self.artifact_root.mkdir(parents=True, exist_ok=True)
        run_root = self.artifact_root / run_id
        run_root.mkdir(parents=False, exist_ok=False)
        if run_root.resolve().parent != self.artifact_root or run_root.is_symlink():
            raise SandboxViolation("artifact path escaped its root")
        target = run_root / "calculator.py"
        temporary = run_root / ".calculator.py.phase4-new"
        temporary.write_text(source, encoding="utf-8", newline="\n")
        os.replace(temporary, target)
        if target.resolve().parent != run_root or target.is_symlink():
            raise SandboxViolation("artifact path is invalid")
        return target

    def _fail_attempt(self, run_id: str, revision: int, error: str) -> dict[str, Any]:
        state = self.store.transition(run_id, "child_failed", expected_revision=revision)
        self.store.record_observation(run_id, "phase4_failed", {"classification": error})
        return {"run_id": run_id, "status": state.status, "eligible": False, "error": error}

    @staticmethod
    def _parse_child_payload(summary: str) -> tuple[str, str] | None:
        try:
            payload = json.loads(summary.strip())
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict) or set(payload) != {"patch", "rationale"}:
            return None
        patch = payload.get("patch")
        rationale = payload.get("rationale")
        if (
            not isinstance(patch, str)
            or not isinstance(rationale, str)
            or not patch
            or not rationale.strip()
            or len(patch.encode("utf-8")) > 8192
            or len(rationale) > 1000
        ):
            return None
        return patch, rationale.strip()
