from __future__ import annotations

import re

import pytest

from contracts import (
    Candidate,
    ContractValidationError,
    EvaluationResult,
    RunSpec,
    SupervisorAdvice,
    TerminalReceipt,
)

HEX_A = "a" * 64
HEX_B = "b" * 64


def make_run_spec(**overrides) -> RunSpec:
    values = {
        "run_id": "run-001",
        "target_root": "/workspace/example",
        "seed_digest": HEX_A,
        "objective": "Reduce deterministic fixture runtime without changing behavior.",
        "exclusions": ("No network access", "No deployment"),
        "evaluator_id": "fixture.runtime.v1",
        "evaluator_config": {"fixture": "tests/fixtures/runtime.json"},
        "correctness_predicates": ("tests_pass",),
        "score_keys": ("runtime_ms",),
        "comparison": "minimize",
        "allowed_toolsets": ("file", "terminal"),
        "network_policy": "disabled",
        "max_steps": 5,
        "max_wall_seconds": 600,
        "max_cost_usd": 1.0,
        "no_progress_limit": 2,
        "approval_receipt": "approved-phase0-fixture",
    }
    values.update(overrides)
    return RunSpec(**values)


def test_run_spec_is_immutable_and_has_stable_sha256_identity():
    first = make_run_spec(evaluator_config={"b": 2, "a": 1})
    second = make_run_spec(evaluator_config={"a": 1, "b": 2})

    assert first.contract_version == "avo.run-spec.v1"
    assert first.identity == second.identity
    assert re.fullmatch(r"[0-9a-f]{64}", first.identity)

    with pytest.raises(Exception):
        first.max_steps = 10


def test_run_spec_deep_freezes_nested_evaluator_configuration():
    source = {"thresholds": [{"runtime_ms": 10.0}]}
    run_spec = make_run_spec(evaluator_config=source)
    identity = run_spec.identity

    source["thresholds"][0]["runtime_ms"] = 999.0
    assert run_spec.identity == identity
    with pytest.raises(TypeError):
        run_spec.evaluator_config["thresholds"][0]["runtime_ms"] = 5.0


def test_run_spec_rejects_invalid_security_and_budget_fields():
    with pytest.raises(ContractValidationError, match="seed_digest"):
        make_run_spec(seed_digest="not-a-digest")
    with pytest.raises(ContractValidationError, match="network_policy"):
        make_run_spec(network_policy="open")
    with pytest.raises(ContractValidationError, match="max_steps"):
        make_run_spec(max_steps=0)
    with pytest.raises(ContractValidationError, match="approval_receipt"):
        make_run_spec(approval_receipt="")
    for invalid in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ContractValidationError, match="max_cost_usd"):
            make_run_spec(max_cost_usd=invalid)
        with pytest.raises(ContractValidationError, match="evaluator_config"):
            make_run_spec(evaluator_config={"threshold": invalid})


def test_candidate_requires_content_hashes_and_relative_changed_paths():
    candidate = Candidate(
        candidate_id="candidate-001",
        run_spec_hash=HEX_A,
        parent_candidate_id=None,
        artifact_digest=HEX_B,
        child_result_hash=HEX_A,
        changed_paths=("src/worker.py", "tests/test_worker.py"),
        hypothesis="Remove duplicate parsing work.",
    )

    assert candidate.contract_version == "avo.candidate.v1"
    assert candidate.identity

    with pytest.raises(ContractValidationError, match="changed_paths"):
        Candidate(
            candidate_id="candidate-002",
            run_spec_hash=HEX_A,
            parent_candidate_id=None,
            artifact_digest=HEX_B,
            child_result_hash=HEX_A,
            changed_paths=("../escape.py",),
            hypothesis="Invalid path",
        )


def test_evaluation_result_cannot_mark_failed_correctness_as_eligible():
    with pytest.raises(ContractValidationError, match="eligible"):
        EvaluationResult(
            evaluation_id="eval-001",
            candidate_hash=HEX_A,
            run_spec_hash=HEX_B,
            evaluator_id="fixture.runtime.v1",
            correctness_passed=False,
            scores={"runtime_ms": 9.0},
            baseline_scores={"runtime_ms": 10.0},
            eligible=True,
            reason="This must be rejected.",
            evidence_hashes=(HEX_A,),
        )


def test_evaluation_result_rejects_non_finite_scores():
    for invalid in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ContractValidationError, match="scores"):
            EvaluationResult(
                evaluation_id="eval-non-finite",
                candidate_hash=HEX_A,
                run_spec_hash=HEX_B,
                evaluator_id="fixture.runtime.v1",
                correctness_passed=True,
                scores={"runtime_ms": invalid},
                baseline_scores={"runtime_ms": 10.0},
                eligible=False,
                reason="Non-finite values are not evidence.",
                evidence_hashes=(HEX_A,),
            )


def test_supervisor_advice_is_bounded_to_three_nonempty_directions():
    advice = SupervisorAdvice(
        advice_id="advice-001",
        run_spec_hash=HEX_A,
        stagnation_evidence_hash=HEX_B,
        directions=("Inspect allocation profile", "Revisit parser boundary"),
        prohibited_repeats=("Do not repeat candidate-003",),
    )
    assert advice.contract_version == "avo.supervisor-advice.v1"

    with pytest.raises(ContractValidationError, match="directions"):
        SupervisorAdvice(
            advice_id="advice-002",
            run_spec_hash=HEX_A,
            stagnation_evidence_hash=HEX_B,
            directions=("a", "b", "c", "d"),
            prohibited_repeats=(),
        )


def test_terminal_receipt_accepts_only_terminal_states():
    receipt = TerminalReceipt(
        receipt_id="receipt-001",
        run_spec_hash=HEX_A,
        terminal_state="succeeded",
        best_candidate_hash=HEX_B,
        steps_used=4,
        cost_usd=0.4,
        unresolved_failures=(),
        export_manifest_hash=HEX_A,
    )
    assert receipt.contract_version == "avo.terminal-receipt.v1"

    with pytest.raises(ContractValidationError, match="terminal_state"):
        TerminalReceipt(
            receipt_id="receipt-002",
            run_spec_hash=HEX_A,
            terminal_state="running",
            best_candidate_hash=None,
            steps_used=1,
            cost_usd=0.0,
            unresolved_failures=(),
            export_manifest_hash=HEX_B,
        )

    for invalid in (float("nan"), float("inf"), float("-inf")):
        with pytest.raises(ContractValidationError, match="cost_usd"):
            TerminalReceipt(
                receipt_id="receipt-non-finite",
                run_spec_hash=HEX_A,
                terminal_state="failed",
                best_candidate_hash=None,
                steps_used=1,
                cost_usd=invalid,
                unresolved_failures=(),
                export_manifest_hash=HEX_B,
            )
