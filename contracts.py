from __future__ import annotations

import hashlib
import json
import math
import re
from dataclasses import dataclass, fields
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, ClassVar, Mapping

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")


class ContractValidationError(ValueError):
    """Raised when a Phase 0 contract violates a deterministic invariant."""


def _require_text(name: str, value: str) -> None:
    if not isinstance(value, str) or not value.strip():
        raise ContractValidationError(f"{name} must be a non-empty string")


def _require_digest(name: str, value: str) -> None:
    if not isinstance(value, str) or _HEX_64.fullmatch(value) is None:
        raise ContractValidationError(f"{name} must be a lowercase SHA-256 digest")


def _require_text_tuple(name: str, value: tuple[str, ...], *, allow_empty: bool = True) -> None:
    if not isinstance(value, tuple):
        raise ContractValidationError(f"{name} must be a tuple")
    if not allow_empty and not value:
        raise ContractValidationError(f"{name} must not be empty")
    if any(not isinstance(item, str) or not item.strip() for item in value):
        raise ContractValidationError(f"{name} must contain only non-empty strings")


def _freeze_value(name: str, value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(name, value)
    if isinstance(value, (list, tuple)):
        return tuple(_freeze_value(name, item) for item in value)
    if isinstance(value, float) and not math.isfinite(value):
        raise ContractValidationError(f"{name} contains a non-finite number")
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise ContractValidationError(f"{name} contains unsupported value type")


def _freeze_mapping(name: str, value: Mapping[str, Any]) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ContractValidationError(f"{name} must be a mapping")
    frozen: dict[str, Any] = {}
    for key, item in value.items():
        if not isinstance(key, str) or not key:
            raise ContractValidationError(f"{name} keys must be non-empty strings")
        frozen[key] = _freeze_value(name, item)
    return MappingProxyType(frozen)


def _primitive(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {key: _primitive(value[key]) for key in sorted(value)}
    if isinstance(value, tuple):
        return [_primitive(item) for item in value]
    return value


class ContractMixin:
    contract_version: ClassVar[str]

    def to_dict(self) -> dict[str, Any]:
        payload = {field.name: _primitive(getattr(self, field.name)) for field in fields(self)}
        return {"contract_version": self.contract_version, **payload}

    @property
    def identity(self) -> str:
        canonical = json.dumps(
            self.to_dict(),
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=True,
            allow_nan=False,
        ).encode("utf-8")
        return hashlib.sha256(canonical).hexdigest()


@dataclass(frozen=True)
class RunSpec(ContractMixin):
    contract_version: ClassVar[str] = "avo.run-spec.v1"

    run_id: str
    target_root: str
    seed_digest: str
    objective: str
    exclusions: tuple[str, ...]
    evaluator_id: str
    evaluator_config: Mapping[str, Any]
    correctness_predicates: tuple[str, ...]
    score_keys: tuple[str, ...]
    comparison: str
    allowed_toolsets: tuple[str, ...]
    network_policy: str
    max_steps: int
    max_wall_seconds: int
    max_cost_usd: float
    no_progress_limit: int
    approval_receipt: str

    def __post_init__(self) -> None:
        for name in ("run_id", "target_root", "objective", "evaluator_id", "approval_receipt"):
            _require_text(name, getattr(self, name))
        _require_digest("seed_digest", self.seed_digest)
        _require_text_tuple("exclusions", self.exclusions)
        _require_text_tuple("correctness_predicates", self.correctness_predicates, allow_empty=False)
        _require_text_tuple("score_keys", self.score_keys, allow_empty=False)
        _require_text_tuple("allowed_toolsets", self.allowed_toolsets, allow_empty=False)
        if self.comparison not in {"minimize", "maximize", "pareto"}:
            raise ContractValidationError("comparison must be minimize, maximize, or pareto")
        if self.network_policy not in {"disabled", "allowlist"}:
            raise ContractValidationError("network_policy must be disabled or allowlist")
        if type(self.max_steps) is not int or self.max_steps <= 0:
            raise ContractValidationError("max_steps must be a positive integer")
        if type(self.max_wall_seconds) is not int or self.max_wall_seconds <= 0:
            raise ContractValidationError("max_wall_seconds must be a positive integer")
        if (
            isinstance(self.max_cost_usd, bool)
            or not isinstance(self.max_cost_usd, (int, float))
            or not math.isfinite(self.max_cost_usd)
            or self.max_cost_usd < 0
        ):
            raise ContractValidationError("max_cost_usd must be finite and non-negative")
        if type(self.no_progress_limit) is not int or self.no_progress_limit <= 0:
            raise ContractValidationError("no_progress_limit must be a positive integer")
        object.__setattr__(self, "evaluator_config", _freeze_mapping("evaluator_config", self.evaluator_config))


@dataclass(frozen=True)
class Candidate(ContractMixin):
    contract_version: ClassVar[str] = "avo.candidate.v1"

    candidate_id: str
    run_spec_hash: str
    parent_candidate_id: str | None
    artifact_digest: str
    child_result_hash: str
    changed_paths: tuple[str, ...]
    hypothesis: str

    def __post_init__(self) -> None:
        _require_text("candidate_id", self.candidate_id)
        _require_digest("run_spec_hash", self.run_spec_hash)
        _require_digest("artifact_digest", self.artifact_digest)
        _require_digest("child_result_hash", self.child_result_hash)
        _require_text("hypothesis", self.hypothesis)
        _require_text_tuple("changed_paths", self.changed_paths, allow_empty=False)
        for raw_path in self.changed_paths:
            normalized = raw_path.replace("\\", "/")
            path = PurePosixPath(normalized)
            if path.is_absolute() or re.match(r"^[A-Za-z]:", normalized) or ".." in path.parts:
                raise ContractValidationError("changed_paths must be relative and traversal-free")


@dataclass(frozen=True)
class EvaluationResult(ContractMixin):
    contract_version: ClassVar[str] = "avo.evaluation-result.v1"

    evaluation_id: str
    candidate_hash: str
    run_spec_hash: str
    evaluator_id: str
    correctness_passed: bool
    scores: Mapping[str, float]
    baseline_scores: Mapping[str, float]
    eligible: bool
    reason: str
    evidence_hashes: tuple[str, ...]

    def __post_init__(self) -> None:
        for name in ("evaluation_id", "evaluator_id", "reason"):
            _require_text(name, getattr(self, name))
        _require_digest("candidate_hash", self.candidate_hash)
        _require_digest("run_spec_hash", self.run_spec_hash)
        _require_text_tuple("evidence_hashes", self.evidence_hashes, allow_empty=False)
        for digest in self.evidence_hashes:
            _require_digest("evidence_hashes", digest)
        if self.eligible and not self.correctness_passed:
            raise ContractValidationError("eligible cannot be true when correctness failed")
        for name in ("scores", "baseline_scores"):
            mapping = _freeze_mapping(name, getattr(self, name))
            if not mapping or any(
                isinstance(value, bool)
                or not isinstance(value, (int, float))
                or not math.isfinite(value)
                for value in mapping.values()
            ):
                raise ContractValidationError(f"{name} must contain finite numeric scores")
            object.__setattr__(self, name, mapping)


@dataclass(frozen=True)
class SupervisorAdvice(ContractMixin):
    contract_version: ClassVar[str] = "avo.supervisor-advice.v1"

    advice_id: str
    run_spec_hash: str
    stagnation_evidence_hash: str
    directions: tuple[str, ...]
    prohibited_repeats: tuple[str, ...]

    def __post_init__(self) -> None:
        _require_text("advice_id", self.advice_id)
        _require_digest("run_spec_hash", self.run_spec_hash)
        _require_digest("stagnation_evidence_hash", self.stagnation_evidence_hash)
        _require_text_tuple("directions", self.directions, allow_empty=False)
        _require_text_tuple("prohibited_repeats", self.prohibited_repeats)
        if len(self.directions) > 3:
            raise ContractValidationError("directions must contain at most three items")


@dataclass(frozen=True)
class ContinuationMemory(ContractMixin):
    contract_version: ClassVar[str] = "avo.continuation-memory.v1"

    run_spec_hash: str
    memory_revision: int
    run_status: str
    state_revision: int
    best_candidate_hash: str | None
    recent_candidate_hashes: tuple[str, ...]
    recent_evaluation_hashes: tuple[str, ...]
    recent_failure_signatures: tuple[str, ...]
    tried_hypotheses: tuple[str, ...]
    supervisor_advice_hash: str | None

    def __post_init__(self) -> None:
        _require_digest("run_spec_hash", self.run_spec_hash)
        _require_text("run_status", self.run_status)
        if type(self.memory_revision) is not int or self.memory_revision <= 0:
            raise ContractValidationError("memory_revision must be a positive integer")
        if type(self.state_revision) is not int or self.state_revision < 0:
            raise ContractValidationError("state_revision must be a non-negative integer")
        if self.best_candidate_hash is not None:
            _require_digest("best_candidate_hash", self.best_candidate_hash)
        if self.supervisor_advice_hash is not None:
            _require_digest("supervisor_advice_hash", self.supervisor_advice_hash)
        for name in ("recent_candidate_hashes", "recent_evaluation_hashes"):
            values = getattr(self, name)
            _require_text_tuple(name, values)
            if len(values) > 5:
                raise ContractValidationError(f"{name} must contain at most five items")
            for digest in values:
                _require_digest(name, digest)
        for name in ("recent_failure_signatures", "tried_hypotheses"):
            values = getattr(self, name)
            _require_text_tuple(name, values)
            if len(values) > 5:
                raise ContractValidationError(f"{name} must contain at most five items")
            if any(len(item) > 300 for item in values):
                raise ContractValidationError(f"{name} entries must be at most 300 characters")


@dataclass(frozen=True)
class TerminalReceipt(ContractMixin):
    contract_version: ClassVar[str] = "avo.terminal-receipt.v1"
    TERMINAL_STATES: ClassVar[frozenset[str]] = frozenset(
        {"succeeded", "no_result", "cancelled", "budget_exhausted", "failed"}
    )

    receipt_id: str
    run_spec_hash: str
    terminal_state: str
    best_candidate_hash: str | None
    steps_used: int
    cost_usd: float
    unresolved_failures: tuple[str, ...]
    export_manifest_hash: str

    def __post_init__(self) -> None:
        _require_text("receipt_id", self.receipt_id)
        _require_digest("run_spec_hash", self.run_spec_hash)
        _require_digest("export_manifest_hash", self.export_manifest_hash)
        if self.terminal_state not in self.TERMINAL_STATES:
            raise ContractValidationError("terminal_state must be a supported terminal state")
        if self.best_candidate_hash is not None:
            _require_digest("best_candidate_hash", self.best_candidate_hash)
        if self.terminal_state == "succeeded" and self.best_candidate_hash is None:
            raise ContractValidationError("succeeded terminal receipt requires best_candidate_hash")
        if not isinstance(self.steps_used, int) or self.steps_used < 0:
            raise ContractValidationError("steps_used must be non-negative")
        if (
            isinstance(self.cost_usd, bool)
            or not isinstance(self.cost_usd, (int, float))
            or not math.isfinite(self.cost_usd)
            or self.cost_usd < 0
        ):
            raise ContractValidationError("cost_usd must be finite and non-negative")
        _require_text_tuple("unresolved_failures", self.unresolved_failures)
