from __future__ import annotations

import hashlib
import json
import secrets
from pathlib import Path
from typing import Any

try:
    from .contracts import Candidate, MutationReceipt, RunSpec
    from .controller import ChildLifecycle
    from .evaluator import FixtureEvaluator, FixtureOutcome
    from .phase3_workspace import Phase3Workspace
    from .storage import RunStore
except ImportError:
    from contracts import Candidate, MutationReceipt, RunSpec
    from controller import ChildLifecycle
    from evaluator import FixtureEvaluator, FixtureOutcome
    from phase3_workspace import Phase3Workspace
    from storage import RunStore

_PHASE3_EVALUATOR = "phase3.unittest.v1"
_ALLOWED_MUTATIONS = frozenset({"filter_odd", "filter_even"})


class Phase3DisabledError(RuntimeError):
    """Raised when executable Phase 3 behavior is disabled in backend config."""


def _identity(payload: dict[str, Any]) -> str:
    canonical = json.dumps(
        payload, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


class Phase3Controller:
    """Run one trusted-template mutation in a plugin-owned disposable repository."""

    def __init__(
        self,
        *,
        store: RunStore,
        lifecycle: ChildLifecycle,
        workspace: Phase3Workspace,
        enabled: bool,
        wait_seconds: int,
    ) -> None:
        self.store = store
        self.lifecycle = lifecycle
        self.workspace = workspace
        self.enabled = enabled
        self.wait_seconds = wait_seconds
        self.evaluator = FixtureEvaluator()

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise Phase3DisabledError(
                "Phase 3 execution is disabled; set backend phase3_enabled=true explicitly."
            )

    def _load_phase3_run(self, run_id: str):
        if not isinstance(run_id, str) or not run_id.startswith("phase3-"):
            raise ValueError("run_id must identify a Phase 3 run")
        spec, state = self.store.load_run(run_id)
        target = Path(spec.target_root).resolve()
        if (
            spec.evaluator_id != _PHASE3_EVALUATOR
            or target.name != run_id
            or target.parent != self.workspace.root
        ):
            raise ValueError("run_id must identify a Phase 3 run")
        return spec, state

    def create_run(self, *, objective: str, approval_receipt: str) -> dict[str, Any]:
        self._require_enabled()
        for name, value in (("objective", objective), ("approval_receipt", approval_receipt)):
            if not isinstance(value, str) or not value.strip() or len(value) > 1000:
                raise ValueError(f"{name} must be a non-empty string of at most 1000 characters")
        repository_id = f"phase3-{secrets.token_hex(8)}"
        repo = self.workspace.create(repository_id)
        baseline_tree_hash = self.workspace.tree_hash(repo)
        spec = RunSpec(
            run_id=repository_id,
            target_root=str(repo),
            seed_digest=baseline_tree_hash,
            objective=objective,
            exclusions=(
                "No model-authored source bytes",
                "No child file or terminal tools",
                "No commits, remotes, pushes, or deployment",
                "No network, credentials, deletion, or cleanup",
                "No autonomous recurrence",
            ),
            evaluator_id=_PHASE3_EVALUATOR,
            evaluator_config={
                "mutations": sorted(_ALLOWED_MUTATIONS),
                "command_id": MutationReceipt.COMMAND_ID,
            },
            correctness_predicates=("tests_pass", "mutation_matches"),
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
        state = self.store.transition(repository_id, "approve", expected_revision=state.revision)
        self.store.record_observation(
            repository_id,
            "repo_created",
            {
                "repository_id": repository_id,
                "baseline_tree_hash": baseline_tree_hash,
                "commit_count": 0,
                "remotes": [],
                "cleanup_status": "retained",
            },
        )
        return {
            "run_id": repository_id,
            "repository_id": repository_id,
            "repository_path": str(repo),
            "run_spec_hash": spec.identity,
            "baseline_tree_hash": baseline_tree_hash,
            "status": state.status,
        }

    def mutate(self, run_id: str) -> dict[str, Any]:
        self._require_enabled()
        spec, state = self._load_phase3_run(run_id)
        state = self.store.transition(run_id, "start_step", expected_revision=state.revision)
        try:
            child = self.lifecycle.run(
                goal=(
                    "Choose exactly one closed mutation for the calculator fixture. Return exactly "
                    "one JSON object with string keys mutation and rationale. Allowed mutations: "
                    "filter_even, filter_odd."
                ),
                context=(
                    "You have no file, terminal, repository, credential, or network authority. "
                    "The controller—not you—maps the enum to trusted source bytes and runs the fixed "
                    "test command. The goal is to make sum_even([1,2,3,4,5,6]) return 12."
                ),
                role="leaf",
                correlation_id=f"{run_id}:mutation:1",
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
        mutation, rationale = parsed
        if mutation not in _ALLOWED_MUTATIONS:
            return self._fail_attempt(run_id, state.revision, "MUTATION_NOT_ALLOWED")

        changed_paths = self.workspace.apply(spec.target_root, mutation)
        mutated_tree_hash = self.workspace.tree_hash(spec.target_root)
        self.store.record_observation(
            run_id,
            "mutation_applied",
            {
                "mutation": mutation,
                "changed_paths": list(changed_paths),
                "mutated_tree_hash": mutated_tree_hash,
            },
        )
        command = self.workspace.evaluate(spec.target_root)
        self.store.record_observation(
            run_id,
            "command_result",
            {
                "command_id": MutationReceipt.COMMAND_ID,
                "exit_code": command.exit_code,
                "tests_passed": command.tests_passed,
                "stdout_hash": command.stdout_hash,
                "stderr_hash": command.stderr_hash,
            },
        )
        candidate = Candidate(
            candidate_id=f"{run_id}-candidate-1",
            run_spec_hash=spec.identity,
            parent_candidate_id=None,
            artifact_digest=mutated_tree_hash,
            child_result_hash=child.result_hash,
            changed_paths=changed_paths,
            hypothesis=rationale,
        )
        evidence = json.dumps(
            {
                "command_id": MutationReceipt.COMMAND_ID,
                "exit_code": command.exit_code,
                "stdout_hash": command.stdout_hash,
                "stderr_hash": command.stderr_hash,
                "tree_hash": mutated_tree_hash,
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
                    "tests_pass": command.tests_passed,
                    "mutation_matches": mutation == "filter_even",
                },
                scores={"test_failures": 0.0 if command.tests_passed else 1.0},
                evidence=evidence,
            ),
        )
        receipt = MutationReceipt(
            receipt_id=f"{run_id}-mutation-receipt-1",
            run_spec_hash=spec.identity,
            candidate_hash=candidate.identity,
            evaluation_hash=evaluation.identity,
            repository_id=run_id,
            baseline_tree_hash=spec.seed_digest,
            mutated_tree_hash=mutated_tree_hash,
            mutation=mutation,
            changed_paths=changed_paths,
            command_id=MutationReceipt.COMMAND_ID,
            exit_code=command.exit_code,
            tests_passed=command.tests_passed,
            stdout_hash=command.stdout_hash,
            stderr_hash=command.stderr_hash,
            repository_retained=True,
            cleanup_status="retained",
        )
        self.store.record_mutation_attempt(run_id, candidate, evaluation, receipt)
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
            "repository_path": spec.target_root,
            "status": state.status,
            "mutation": mutation,
            "eligible": evaluation.eligible,
            "tests_passed": command.tests_passed,
            "exit_code": command.exit_code,
            "candidate_hash": candidate.identity,
            "evaluation_hash": evaluation.identity,
            "receipt_hash": receipt.identity,
            "cleanup_status": "retained",
        }

    def receipt(self, run_id: str) -> dict[str, Any]:
        spec, _ = self._load_phase3_run(run_id)
        receipts = self.store.mutation_receipts(run_id)
        if not receipts:
            raise ValueError("mutation receipt is not available")
        return {**receipts[-1], "repository_path": spec.target_root}

    def cancel(self, run_id: str) -> dict[str, Any]:
        self._require_enabled()
        _, state = self._load_phase3_run(run_id)
        if state.status in {"running", "evaluating"}:
            raise ValueError("in-flight Phase 3 cancellation is not claimed")
        state = self.store.transition(run_id, "cancel", expected_revision=state.revision)
        return {"run_id": run_id, "status": state.status, "cleanup_status": "retained"}

    def reconcile(self, run_id: str) -> dict[str, Any]:
        self._require_enabled()
        _, state = self._load_phase3_run(run_id)
        if state.status not in {"running", "evaluating"}:
            return {"run_id": run_id, "status": state.status, "action": "noop"}
        lineage = self.store.lineage(run_id)
        receipts = self.store.mutation_receipts(run_id)
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

    def _fail_attempt(self, run_id: str, revision: int, error: str) -> dict[str, Any]:
        state = self.store.transition(run_id, "child_failed", expected_revision=revision)
        self.store.record_observation(run_id, "phase3_failed", {"classification": error})
        return {"run_id": run_id, "status": state.status, "eligible": False, "error": error}

    @staticmethod
    def _parse_child_payload(summary: str) -> tuple[str, str] | None:
        try:
            payload = json.loads(summary.strip())
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict) or set(payload) != {"mutation", "rationale"}:
            return None
        mutation = payload.get("mutation")
        rationale = payload.get("rationale")
        if (
            not isinstance(mutation, str)
            or not isinstance(rationale, str)
            or not mutation.strip()
            or not rationale.strip()
            or len(rationale) > 1000
        ):
            return None
        return mutation.strip(), rationale.strip()
