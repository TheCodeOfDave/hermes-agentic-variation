from __future__ import annotations

import hashlib
import json
import math
from dataclasses import dataclass
from typing import Mapping

try:
    from .contracts import Candidate, ContractValidationError, EvaluationResult, RunSpec
except ImportError:  # Direct module execution in local tests.
    from contracts import Candidate, ContractValidationError, EvaluationResult, RunSpec


@dataclass(frozen=True)
class FixtureOutcome:
    """Model-free evaluator input used only by deterministic Phase 0 fixtures."""

    correctness: Mapping[str, bool]
    scores: Mapping[str, float]
    evidence: bytes


class FixtureEvaluator:
    """Evaluate fixture outcomes without shell commands, models, or network access."""

    def evaluate(
        self,
        run_spec: RunSpec,
        candidate: Candidate,
        *,
        baseline_scores: Mapping[str, float],
        outcome: FixtureOutcome,
    ) -> EvaluationResult:
        if candidate.run_spec_hash != run_spec.identity:
            raise ContractValidationError("candidate RunSpec hash does not match")
        if run_spec.comparison not in {"minimize", "maximize"}:
            raise ContractValidationError("fixture evaluator does not implement pareto comparison")
        if not isinstance(outcome.evidence, bytes) or not outcome.evidence:
            raise ContractValidationError("fixture evidence must be non-empty bytes")

        required_correctness = set(run_spec.correctness_predicates)
        if not required_correctness.issubset(outcome.correctness):
            raise ContractValidationError("correctness_predicates are missing from fixture outcome")
        if any(not isinstance(outcome.correctness[key], bool) for key in required_correctness):
            raise ContractValidationError("correctness_predicates must resolve to booleans")

        required_scores = set(run_spec.score_keys)
        if not required_scores.issubset(outcome.scores) or not required_scores.issubset(
            baseline_scores
        ):
            raise ContractValidationError("score_keys are missing from candidate or baseline scores")
        for mapping in (outcome.scores, baseline_scores):
            if any(
                isinstance(mapping[key], bool)
                or not isinstance(mapping[key], (int, float))
                or not math.isfinite(mapping[key])
                for key in required_scores
            ):
                raise ContractValidationError("score_keys must resolve to finite numeric values")

        correctness_passed = all(outcome.correctness[key] for key in run_spec.correctness_predicates)
        if run_spec.comparison == "minimize":
            non_regressing = all(
                outcome.scores[key] <= baseline_scores[key] for key in run_spec.score_keys
            )
        else:
            non_regressing = all(
                outcome.scores[key] >= baseline_scores[key] for key in run_spec.score_keys
            )

        eligible = correctness_passed and non_regressing
        if not correctness_passed:
            reason = "candidate failed at least one correctness predicate"
        elif not non_regressing:
            reason = "candidate regressed at least one required score"
        else:
            reason = "correctness passed and scores are non-regressing"

        evidence_hash = hashlib.sha256(outcome.evidence).hexdigest()
        identity_payload = {
            "run_spec_hash": run_spec.identity,
            "candidate_hash": candidate.identity,
            "evaluator_id": run_spec.evaluator_id,
            "correctness": {
                key: outcome.correctness[key] for key in sorted(required_correctness)
            },
            "scores": {key: outcome.scores[key] for key in sorted(required_scores)},
            "baseline_scores": {
                key: baseline_scores[key] for key in sorted(required_scores)
            },
            "evidence_hash": evidence_hash,
        }
        evaluation_id = hashlib.sha256(
            json.dumps(identity_payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
        ).hexdigest()

        return EvaluationResult(
            evaluation_id=evaluation_id,
            candidate_hash=candidate.identity,
            run_spec_hash=run_spec.identity,
            evaluator_id=run_spec.evaluator_id,
            correctness_passed=correctness_passed,
            scores={key: outcome.scores[key] for key in run_spec.score_keys},
            baseline_scores={key: baseline_scores[key] for key in run_spec.score_keys},
            eligible=eligible,
            reason=reason,
            evidence_hashes=(evidence_hash,),
        )
