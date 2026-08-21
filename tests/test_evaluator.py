from __future__ import annotations

import pytest

from contracts import Candidate, ContractValidationError, RunSpec
from evaluator import FixtureEvaluator, FixtureOutcome

HEX_A = "a" * 64
HEX_B = "b" * 64


def spec(comparison: str = "minimize", *, strict_improvement: bool = False) -> RunSpec:
    return RunSpec(
        run_id="run-evaluator",
        target_root="/workspace/example",
        seed_digest=HEX_A,
        objective="Exercise deterministic evaluation.",
        exclusions=(),
        evaluator_id="fixture.runtime.v1",
        evaluator_config={"source": "test", "strict_improvement": strict_improvement},
        correctness_predicates=("tests_pass", "output_matches"),
        score_keys=("runtime_ms", "allocations"),
        comparison=comparison,
        allowed_toolsets=("file",),
        network_policy="disabled",
        max_steps=3,
        max_wall_seconds=60,
        max_cost_usd=1.0,
        no_progress_limit=2,
        approval_receipt="approved",
    )


def candidate(run_spec: RunSpec) -> Candidate:
    return Candidate(
        candidate_id="candidate-evaluator",
        run_spec_hash=run_spec.identity,
        parent_candidate_id=None,
        artifact_digest=HEX_B,
        child_result_hash=HEX_A,
        changed_paths=("src/worker.py",),
        hypothesis="Reduce duplicate work.",
    )


def outcome(**overrides) -> FixtureOutcome:
    values = {
        "correctness": {"tests_pass": True, "output_matches": True},
        "scores": {"runtime_ms": 9.0, "allocations": 10.0},
        "evidence": b"deterministic fixture evidence",
    }
    values.update(overrides)
    return FixtureOutcome(**values)


def test_minimize_accepts_non_regressing_candidate():
    run_spec = spec("minimize")
    result = FixtureEvaluator().evaluate(
        run_spec,
        candidate(run_spec),
        baseline_scores={"runtime_ms": 10.0, "allocations": 10.0},
        outcome=outcome(),
    )

    assert result.correctness_passed is True
    assert result.eligible is True
    assert result.reason == "correctness passed and scores are non-regressing"


def test_correctness_failure_is_ineligible_even_when_scores_improve():
    run_spec = spec()
    result = FixtureEvaluator().evaluate(
        run_spec,
        candidate(run_spec),
        baseline_scores={"runtime_ms": 10.0, "allocations": 11.0},
        outcome=outcome(correctness={"tests_pass": False, "output_matches": True}),
    )

    assert result.correctness_passed is False
    assert result.eligible is False
    assert "correctness" in result.reason


def test_regression_is_ineligible():
    run_spec = spec()
    result = FixtureEvaluator().evaluate(
        run_spec,
        candidate(run_spec),
        baseline_scores={"runtime_ms": 8.0, "allocations": 10.0},
        outcome=outcome(),
    )

    assert result.eligible is False
    assert result.reason == "candidate regressed at least one required score"


def test_maximize_uses_inverse_comparison():
    run_spec = spec("maximize")
    result = FixtureEvaluator().evaluate(
        run_spec,
        candidate(run_spec),
        baseline_scores={"runtime_ms": 8.0, "allocations": 9.0},
        outcome=outcome(),
    )

    assert result.eligible is True


def test_missing_required_score_or_correctness_key_fails_closed():
    run_spec = spec()
    evaluator = FixtureEvaluator()

    with pytest.raises(ContractValidationError, match="score_keys"):
        evaluator.evaluate(
            run_spec,
            candidate(run_spec),
            baseline_scores={"runtime_ms": 10.0},
            outcome=outcome(),
        )

    with pytest.raises(ContractValidationError, match="correctness_predicates"):
        evaluator.evaluate(
            run_spec,
            candidate(run_spec),
            baseline_scores={"runtime_ms": 10.0, "allocations": 10.0},
            outcome=outcome(correctness={"tests_pass": True}),
        )


def test_fixture_evaluation_identity_is_deterministic():
    run_spec = spec()
    evaluator = FixtureEvaluator()
    args = {
        "baseline_scores": {"runtime_ms": 10.0, "allocations": 10.0},
        "outcome": outcome(),
    }

    first = evaluator.evaluate(run_spec, candidate(run_spec), **args)
    second = evaluator.evaluate(run_spec, candidate(run_spec), **args)

    assert first.identity == second.identity
    assert first.evaluation_id == second.evaluation_id
    assert first.evidence_hashes == second.evidence_hashes


def test_fixture_evaluator_rejects_non_finite_candidate_or_baseline_scores():
    run_spec = spec()
    evaluator = FixtureEvaluator()

    for invalid in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ContractValidationError, match="finite"):
            evaluator.evaluate(
                run_spec,
                candidate(run_spec),
                baseline_scores={"runtime_ms": 10.0, "allocations": 10.0},
                outcome=outcome(scores={"runtime_ms": invalid, "allocations": 10.0}),
            )
        with pytest.raises(ContractValidationError, match="finite"):
            evaluator.evaluate(
                run_spec,
                candidate(run_spec),
                baseline_scores={"runtime_ms": invalid, "allocations": 10.0},
                outcome=outcome(),
            )
    with pytest.raises(ContractValidationError, match="finite"):
        evaluator.evaluate(
            run_spec,
            candidate(run_spec),
            baseline_scores={"runtime_ms": 10.0, "allocations": 10.0},
            outcome=outcome(scores={"runtime_ms": True, "allocations": 10.0}),
        )


def test_fixture_evaluator_can_require_strict_improvement():
    run_spec = spec(strict_improvement=True)

    result = FixtureEvaluator().evaluate(
        run_spec,
        candidate(run_spec),
        baseline_scores={"runtime_ms": 10.0, "allocations": 10.0},
        outcome=outcome(scores={"runtime_ms": 10.0, "allocations": 10.0}),
    )

    assert result.eligible is False
    assert "strictly improve" in result.reason
