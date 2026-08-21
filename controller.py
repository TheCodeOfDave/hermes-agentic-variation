from __future__ import annotations

import hashlib
import json
import secrets
from dataclasses import dataclass
from typing import Any, Protocol

try:
    from .contracts import Candidate, RunSpec
    from .evaluator import FixtureEvaluator, FixtureOutcome
    from .storage import RunStore
except ImportError:  # Direct module execution in local tests.
    from contracts import Candidate, RunSpec
    from evaluator import FixtureEvaluator, FixtureOutcome
    from storage import RunStore

_FIXTURE_ID = "phase1.strategy.v1"
_FIXTURE_TARGET = "plugin://agentic-variation/phase1-fixture"
_FIXTURE_SEED = hashlib.sha256(b"agentic-variation-phase1-fixture-v1").hexdigest()
_STRATEGY_SCORES = {
    "baseline": 10.0,
    "single_pass": 7.0,
    "memoized_lookup": 5.0,
}


class Phase1DisabledError(RuntimeError):
    """Raised when executable Phase 1 behavior is disabled in backend config."""


class ChildLifecycle(Protocol):
    def run(self, **request: Any) -> "ChildOutcome": ...


@dataclass(frozen=True)
class ChildOutcome:
    terminal_state: str
    summary: str | None
    result_hash: str
    api_calls: int
    error: str | None = None


class Phase1Controller:
    """Run exactly one model-directed, no-tool fixture variation step."""

    def __init__(
        self,
        *,
        store: RunStore,
        lifecycle: ChildLifecycle,
        enabled: bool,
        wait_seconds: int,
    ) -> None:
        self.store = store
        self.lifecycle = lifecycle
        self.enabled = enabled
        self.wait_seconds = wait_seconds
        self.evaluator = FixtureEvaluator()

    def _require_enabled(self) -> None:
        if not self.enabled:
            raise Phase1DisabledError(
                "Phase 1 execution is disabled; set backend phase1_enabled=true explicitly."
            )

    def create_run(self, *, objective: str, approval_receipt: str) -> dict[str, Any]:
        self._require_enabled()
        run_id = f"phase1-{secrets.token_hex(8)}"
        spec = RunSpec(
            run_id=run_id,
            target_root=_FIXTURE_TARGET,
            seed_digest=_FIXTURE_SEED,
            objective=objective,
            exclusions=(
                "No file or repository mutation",
                "No command execution",
                "No network access",
                "No external effects",
            ),
            evaluator_id=_FIXTURE_ID,
            evaluator_config={"strategies": _STRATEGY_SCORES},
            correctness_predicates=("strategy_allowed", "output_matches"),
            score_keys=("operations",),
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
        return {"run_id": run_id, "run_spec_hash": spec.identity, "status": state.status}

    def step(self, run_id: str) -> dict[str, Any]:
        self._require_enabled()
        spec, state = self.store.load_run(run_id)
        state = self.store.transition(run_id, "start_step", expected_revision=state.revision)

        try:
            child = self.lifecycle.run(
                goal=(
                    "Choose the best deterministic strategy for the supplied fixture. "
                    "Return exactly one JSON object with string fields strategy and rationale. "
                    "Allowed strategy values: baseline, single_pass, memoized_lookup."
                ),
                context=(
                    "This is an isolated reasoning fixture. You have no file, command, repository, "
                    "credential, or network authority. The only permitted output is the requested JSON. "
                    "Scores are deterministic operations: baseline=10, single_pass=7, "
                    "memoized_lookup=5. Lower is better."
                ),
                role="leaf",
                correlation_id=f"{run_id}:revision:{state.revision}",
                allowed_toolsets=("todo",),
                wait_seconds=self.wait_seconds,
            )
        except Exception:
            failed = self.store.transition(
                run_id, "child_failed", expected_revision=state.revision
            )
            self.store.record_observation(
                run_id,
                "child_launch_error",
                {"error_classification": "CHILD_LAUNCH_ERROR"},
            )
            return {
                "run_id": run_id,
                "status": failed.status,
                "eligible": False,
                "error": "CHILD_LAUNCH_ERROR",
            }
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
            failed = self.store.transition(
                run_id, "child_failed", expected_revision=state.revision
            )
            return {
                "run_id": run_id,
                "status": failed.status,
                "eligible": False,
                "error": "CHILD_FAILED",
            }

        parsed = self._parse_child_payload(child.summary)
        if parsed is None:
            failed = self.store.transition(
                run_id, "child_failed", expected_revision=state.revision
            )
            return {
                "run_id": run_id,
                "status": failed.status,
                "eligible": False,
                "error": "INVALID_CHILD_PAYLOAD",
            }
        strategy, rationale = parsed
        if strategy not in _STRATEGY_SCORES:
            failed = self.store.transition(
                run_id, "child_failed", expected_revision=state.revision
            )
            return {
                "run_id": run_id,
                "status": failed.status,
                "eligible": False,
                "error": "STRATEGY_NOT_ALLOWED",
            }

        artifact = json.dumps(
            {"strategy": strategy, "rationale": rationale},
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        candidate = Candidate(
            candidate_id=f"{run_id}-candidate-1",
            run_spec_hash=spec.identity,
            parent_candidate_id=None,
            artifact_digest=hashlib.sha256(artifact).hexdigest(),
            child_result_hash=child.result_hash,
            changed_paths=("fixtures/strategy.json",),
            hypothesis=rationale,
        )
        outcome = FixtureOutcome(
            correctness={"strategy_allowed": True, "output_matches": True},
            scores={"operations": _STRATEGY_SCORES[strategy]},
            evidence=artifact,
        )
        evaluation = self.evaluator.evaluate(
            spec,
            candidate,
            baseline_scores={"operations": _STRATEGY_SCORES["baseline"]},
            outcome=outcome,
        )
        self.store.record_attempt(run_id, candidate, evaluation)
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
            "strategy": strategy,
            "scores": dict(evaluation.scores),
            "candidate_hash": candidate.identity,
            "evaluation_hash": evaluation.identity,
        }

    def status(self, run_id: str) -> dict[str, Any]:
        spec, state = self.store.load_run(run_id)
        return {
            "run_id": run_id,
            "run_spec_hash": spec.identity,
            "status": state.status,
            "revision": state.revision,
            "steps_used": state.steps_used,
            "best_candidate_hash": state.best_candidate_hash,
        }

    def lineage(self, run_id: str) -> dict[str, Any]:
        self.store.load_run(run_id)
        return {"run_id": run_id, **self.store.lineage(run_id)}

    def cancel(self, run_id: str) -> dict[str, Any]:
        self._require_enabled()
        _, state = self.store.load_run(run_id)
        if state.status in {"running", "evaluating"}:
            raise ValueError(
                "in-flight cancellation is not claimed in Phase 1; use the active lifecycle owner"
            )
        state = self.store.transition(run_id, "cancel", expected_revision=state.revision)
        return {"run_id": run_id, "status": state.status}

    @staticmethod
    def _parse_child_payload(summary: str) -> tuple[str, str] | None:
        text = summary.strip()
        if text.startswith("```"):
            lines = text.splitlines()
            if lines and lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].strip() == "```":
                lines = lines[:-1]
            text = "\n".join(lines).strip()
        try:
            payload = json.loads(text)
        except (TypeError, ValueError):
            return None
        if not isinstance(payload, dict) or set(payload) != {"strategy", "rationale"}:
            return None
        strategy = payload.get("strategy")
        rationale = payload.get("rationale")
        if (
            not isinstance(strategy, str)
            or not isinstance(rationale, str)
            or not strategy.strip()
            or not rationale.strip()
            or len(rationale) > 1000
        ):
            return None
        return strategy.strip(), rationale.strip()
