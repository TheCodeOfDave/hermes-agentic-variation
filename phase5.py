from __future__ import annotations

import hashlib
import json
import re
import secrets
from pathlib import Path
from typing import Any

try:
    from .contracts import Candidate, EvaluationResult, PatchSetReceipt, RunSpec
    from .phase5_fixture import Phase5Fixture, SOURCE_PATHS
    from .phase5_patch import PatchSetValidationError, ValidatedPatchSet
    from .phase5_sandbox import (
        Phase5ExecutionResult,
        Phase5SandboxUnavailable,
        Phase5SandboxViolation,
        find_inert_orphans,
    )
    from .phase5_stage_a import tree_hash
    from .storage import RunStore
except ImportError:  # Direct module execution in local tests.
    from contracts import Candidate, EvaluationResult, PatchSetReceipt, RunSpec
    from phase5_fixture import Phase5Fixture, SOURCE_PATHS
    from phase5_patch import PatchSetValidationError, ValidatedPatchSet
    from phase5_sandbox import (
        Phase5ExecutionResult,
        Phase5SandboxUnavailable,
        Phase5SandboxViolation,
        find_inert_orphans,
    )
    from phase5_stage_a import tree_hash
    from storage import RunStore

EVALUATOR_ID = "phase5.immutable-evaluator.v1"
_RECEIPT_POLICY_KEYS = (
    "memory_mib",
    "cpus",
    "pids_limit",
    "tmpfs_bytes",
    "user",
    "stage_a_stdout_bytes",
    "stage_b_stdout_bytes",
    "worker_pipe_bytes",
    "stage_a_timeout_seconds",
    "stage_b_timeout_seconds",
)


class Phase5DisabledError(RuntimeError):
    pass


def _sha(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _identity(value: Any) -> str:
    return _sha(
        json.dumps(
            value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False
        ).encode("utf-8")
    )


class Phase5Controller:
    def __init__(
        self,
        *,
        store: RunStore,
        lifecycle: Any,
        fixture: Phase5Fixture,
        sandbox: Any,
        artifact_root: str | Path,
        enabled: bool,
        wait_seconds: int,
    ) -> None:
        self.store = store
        self.lifecycle = lifecycle
        self.fixture = fixture
        self.sandbox = sandbox
        self.artifact_root = Path(artifact_root).resolve()
        self.enabled = enabled
        self.wait_seconds = wait_seconds

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise Phase5DisabledError(
                "Variation Cycle execution is disabled; enable it explicitly in backend configuration."
            )

    def _load(self, run_id: str):
        if not isinstance(run_id, str) or re.fullmatch(r"phase5-[0-9a-f]{6,32}", run_id) is None:
            raise ValueError("run_id must identify a Variation Cycle")
        spec, state = self.store.load_run(run_id)
        target = Path(spec.target_root).resolve()
        if (
            spec.evaluator_id != EVALUATOR_ID
            or target.name != run_id
            or target.parent != self.fixture.root
        ):
            raise ValueError("run_id must identify a Variation Cycle")
        return spec, state

    def create_run(self, *, objective: str, approval_receipt: str) -> dict[str, Any]:
        self._require_enabled()
        for name, value in (("objective", objective), ("approval_receipt", approval_receipt)):
            if not isinstance(value, str) or not value.strip() or len(value) > 1000:
                raise ValueError(f"{name} must be non-empty and at most 1000 characters")
        preflight = self.sandbox.preflight()
        run_id = f"phase5-{secrets.token_hex(8)}"
        facts = self.fixture.create(run_id)
        baselines = {
            p: (facts.repository_path / p).read_text(encoding="utf-8") for p in SOURCE_PATHS
        }
        baseline_tree = tree_hash(baselines)
        config = {
            **preflight,
            "baseline_paths": list(SOURCE_PATHS),
            "baseline_hashes": [facts.source_hashes[p] for p in SOURCE_PATHS],
            "immutable_cases_hash": facts.cases_hash,
        }
        spec = RunSpec(
            run_id=run_id,
            target_root=str(facts.repository_path),
            seed_digest=baseline_tree,
            objective=objective,
            exclusions=(
                "No network or credentials",
                "No host Docker socket",
                "No tests, repository metadata, commit, push, deploy, cleanup, retry, or recurrence",
            ),
            evaluator_id=EVALUATOR_ID,
            evaluator_config=config,
            correctness_predicates=("stage_a_verified", "stage_b_protocol_passed"),
            score_keys=("failures",),
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
        return {
            "run_id": run_id,
            "repository_path": str(facts.repository_path),
            "run_spec_hash": spec.identity,
            "baseline_tree_hash": baseline_tree,
            "status": state.status,
            **preflight,
        }

    def patchset(self, run_id: str) -> dict[str, Any]:
        self._require_enabled()
        spec, state = self._load(run_id)
        state = self.store.transition(run_id, "start_step", expected_revision=state.revision)
        try:
            child = self.lifecycle.run(
                goal="Return one exact Variation Proposal JSON object for the fixed two-artifact canary.",
                context=(
                    "Todo only. Canonical baselines are calculator.py: anchor = 0; value = 1; def total(values): return sum(values) + 1. "
                    "filters.py: anchor = 0; value = 1; def select(values): return odd values. "
                    "formatting.py: anchor = 0; value = 1; def format_result(value): return f'total={value}'. "
                    "Change calculator.py to remove + 1 and filters.py to select even values. No file, terminal, Docker, network, credentials, Git, tests, or retry."
                ),
                role="leaf",
                correlation_id=f"{run_id}:patchset:1",
                allowed_toolsets=("todo",),
                wait_seconds=self.wait_seconds,
            )
        except Exception:
            return self._fail(run_id, state.revision, "CHILD_LAUNCH_ERROR")
        self.store.record_observation(
            run_id,
            "phase5_child_result",
            {
                "terminal_state": child.terminal_state,
                "result_hash": child.result_hash,
                "api_calls": child.api_calls,
            },
        )
        if child.terminal_state != "SUCCEEDED" or not child.summary:
            return self._fail(run_id, state.revision, "CHILD_FAILED")
        try:
            patchset = ValidatedPatchSet.parse(child.summary)
        except PatchSetValidationError:
            return self._fail(run_id, state.revision, "INVALID_PATCH_SET")
        try:
            baseline_paths = tuple(spec.evaluator_config["baseline_paths"])
            expected_hashes = tuple(spec.evaluator_config["baseline_hashes"])
            fresh_hashes = tuple(
                _sha((Path(spec.target_root) / path).read_bytes()) for path in baseline_paths
            )
            if baseline_paths != SOURCE_PATHS or fresh_hashes != expected_hashes:
                raise Phase5SandboxViolation("fresh baseline differs from approved RunSpec")
        except (KeyError, OSError, TypeError, ValueError, Phase5SandboxViolation):
            return self._fail(run_id, state.revision, "SANDBOX_FAILED")
        try:
            result: Phase5ExecutionResult = self.sandbox.run(
                run_id, spec.target_root, patchset, self.artifact_root
            )
        except (Phase5SandboxUnavailable, Phase5SandboxViolation, ValueError):
            return self._fail(run_id, state.revision, "SANDBOX_FAILED")
        config = spec.evaluator_config
        if (
            result.image != config["image"]
            or result.trusted_applier_hash != config["trusted_applier_hash"]
            or result.evaluator_hash != config["evaluator_hash"]
            or result.worker_bootstrap_hash != config["worker_bootstrap_hash"]
            or result.policy_hash != config["policy_hash"]
            or result.immutable_cases_hash != config["immutable_cases_hash"]
        ):
            raise Phase5SandboxViolation("sandbox identity differs from approved RunSpec")
        candidate = Candidate(
            f"{run_id}-candidate-1",
            spec.identity,
            None,
            result.candidate_tree_hash,
            child.result_hash,
            patchset.paths,
            patchset.rationale,
        )
        evaluation = EvaluationResult(
            f"{run_id}-evaluation-1",
            candidate.identity,
            spec.identity,
            EVALUATOR_ID,
            result.stage_b.eligible,
            {"failures": 0.0 if result.stage_b.eligible else 1.0},
            {"failures": 1.0},
            result.stage_b.eligible,
            result.stage_b.classification,
            (result.stage_a_envelope_hash, result.stage_b.stdout_hash, result.stage_b.stderr_hash),
        )
        output_hashes = {p: _sha(result.sources[p].encode("utf-8")) for p in SOURCE_PATHS}
        receipt = PatchSetReceipt(
            receipt_id=f"{run_id}-patch-set-receipt-1",
            run_spec_hash=spec.identity,
            candidate_hash=candidate.identity,
            evaluation_hash=evaluation.identity,
            baseline_paths=SOURCE_PATHS,
            baseline_hashes=tuple(config["baseline_hashes"]),
            changed_paths=patchset.paths,
            patch_set_hash=patchset.identity,
            rationale_hash=patchset.rationale_hash,
            member_patch_hashes=patchset.member_hashes,
            image=result.image,
            trusted_applier_hash=result.trusted_applier_hash,
            immutable_cases_hash=result.immutable_cases_hash,
            evaluator_hash=result.evaluator_hash,
            worker_bootstrap_hash=result.worker_bootstrap_hash,
            policy_hash=result.policy_hash,
            stage_a_command_id="phase5.trusted-applier.v1",
            stage_b_command_id="phase5.immutable-evaluator.v1",
            output_tree_hash=result.candidate_tree_hash,
            output_source_hashes=output_hashes,
            literal_ceilings={
                **{key: config["policy"][key] for key in _RECEIPT_POLICY_KEYS},
                "wait_seconds": spec.max_wall_seconds,
            },
            stage_a_envelope_hash=result.stage_a_envelope_hash,
            stage_a_status="applied",
            stage_a_stderr_hash=result.stage_a_stderr_hash,
            stage_a_classification="PASS",
            stage_b_exit_code=result.stage_b.exit_code
            if result.stage_b.exit_code is not None
            else -1,
            success_trailer_matched=result.stage_b.trailer_matched,
            evaluator_stdout_hash=result.stage_b.stdout_hash,
            evaluator_stderr_hash=result.stage_b.stderr_hash,
            worker_classification=result.stage_b.classification,
            artifact_relative_path=f"phase5-artifacts/{run_id}",
            network_policy="none",
            cleanup_status="retained",
        )
        self.store.record_patch_set_attempt(run_id, candidate, evaluation, receipt)
        state = self.store.transition(run_id, "candidate_ready", expected_revision=state.revision)
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
            "candidate_hash": candidate.identity,
            "evaluation_hash": evaluation.identity,
            "receipt_hash": receipt.identity,
            "artifact_path": str(result.artifact_path),
            "cleanup_status": "retained",
        }

    def receipt(self, run_id: str) -> dict[str, Any]:
        self._load(run_id)
        receipts = self.store.patch_set_receipts(run_id)
        if not receipts:
            raise ValueError("patch-set receipt is not available")
        return receipts[-1]

    def reconcile(self, run_id: str) -> dict[str, Any]:
        self._require_enabled()
        _, state = self._load(run_id)
        committed = {run_id} if self.store.patch_set_receipts(run_id) else set()
        orphan_roots: tuple[str | Path, ...] = (self.artifact_root,)
        runtime_root = getattr(self.sandbox, "runtime_root", None)
        if runtime_root is not None:
            orphan_roots = (Path(runtime_root).resolve() / "candidates", *orphan_roots)
        orphans = [str(path) for path in find_inert_orphans(orphan_roots, committed)]
        if state.status not in {"running", "evaluating"}:
            return {"run_id": run_id, "status": state.status, "action": "noop", "orphans": orphans}
        lineage = self.store.lineage(run_id)
        receipts = self.store.patch_set_receipts(run_id)
        applied = sum(
            e["event"] in {"evaluation_eligible", "evaluation_ineligible"}
            for e in self.store.events(run_id)
        )
        if len(lineage["evaluations"]) > applied and len(receipts) > applied:
            cp = lineage["candidates"][-1]
            ep = lineage["evaluations"][-1]
            if state.status == "running":
                state = self.store.transition(
                    run_id, "candidate_ready", expected_revision=state.revision
                )
            event = "evaluation_eligible" if ep.get("eligible") is True else "evaluation_ineligible"
            state = self.store.transition(
                run_id,
                event,
                expected_revision=state.revision,
                candidate_hash=_identity(cp) if event == "evaluation_eligible" else None,
            )
            return {
                "run_id": run_id,
                "status": state.status,
                "action": "evaluation_replayed",
                "orphans": orphans,
            }
        event = "interrupt" if state.status == "running" else "evaluation_missing"
        state = self.store.transition(run_id, event, expected_revision=state.revision)
        return {
            "run_id": run_id,
            "status": state.status,
            "action": "interrupted" if event == "interrupt" else event,
            "orphans": orphans,
        }

    def _fail(self, run_id: str, revision: int, error: str) -> dict[str, Any]:
        state = self.store.transition(run_id, "child_failed", expected_revision=revision)
        self.store.record_observation(run_id, "phase5_failed", {"classification": error})
        return {"run_id": run_id, "status": state.status, "eligible": False, "error": error}
