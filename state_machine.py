from __future__ import annotations

import re
import math
from dataclasses import dataclass, replace

try:
    from .contracts import RunSpec
except ImportError:  # Direct module execution in local tests.
    from contracts import RunSpec

_HEX_64 = re.compile(r"^[0-9a-f]{64}$")
_TERMINAL = frozenset({"succeeded", "no_result", "cancelled", "budget_exhausted", "failed"})
_ALLOWED = {
    "created": {"approve", "cancel"},
    "ready": {"start_step", "pause", "cancel", "complete"},
    "running": {"candidate_ready", "child_failed", "interrupt", "cancel"},
    "evaluating": {
        "evaluation_eligible",
        "evaluation_ineligible",
        "evaluation_missing",
        "cancel",
    },
    "supervision_required": {"start_supervisor", "pause", "cancel", "complete"},
    "supervising": {"supervisor_applied", "supervisor_failed", "cancel"},
    "paused": {"resume", "cancel"},
}


class TransitionError(ValueError):
    """Raised when a run transition violates the Phase 0 state machine."""


@dataclass(frozen=True)
class RunState:
    run_spec_hash: str
    status: str
    revision: int
    steps_used: int
    consecutive_no_progress: int
    best_candidate_hash: str | None
    cost_usd: float
    paused_from: str | None = None

    @classmethod
    def new(cls, run_spec_hash: str) -> "RunState":
        if _HEX_64.fullmatch(run_spec_hash) is None:
            raise TransitionError("run_spec_hash must be a lowercase SHA-256 digest")
        return cls(
            run_spec_hash=run_spec_hash,
            status="created",
            revision=0,
            steps_used=0,
            consecutive_no_progress=0,
            best_candidate_hash=None,
            cost_usd=0.0,
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in _TERMINAL


def _next_after_attempt(
    state: RunState,
    spec: RunSpec,
    *,
    progressed: bool,
    candidate_hash: str | None,
    cost_delta: float,
) -> RunState:
    steps = state.steps_used + 1
    cost = state.cost_usd + cost_delta
    if not math.isfinite(cost):
        raise TransitionError("accumulated cost must remain finite")
    no_progress = 0 if progressed else state.consecutive_no_progress + 1

    if candidate_hash is not None and _HEX_64.fullmatch(candidate_hash) is None:
        raise TransitionError("candidate_hash must be a lowercase SHA-256 digest")

    if progressed and (steps >= spec.max_steps or cost >= spec.max_cost_usd):
        status = "succeeded"
    elif steps >= spec.max_steps or cost >= spec.max_cost_usd:
        status = "budget_exhausted"
    elif no_progress >= spec.no_progress_limit:
        status = "supervision_required"
    else:
        status = "ready"

    return replace(
        state,
        status=status,
        revision=state.revision + 1,
        steps_used=steps,
        consecutive_no_progress=no_progress,
        best_candidate_hash=candidate_hash if progressed else state.best_candidate_hash,
        cost_usd=cost,
    )


def apply_transition(
    state: RunState,
    event: str,
    spec: RunSpec,
    *,
    candidate_hash: str | None = None,
    cost_delta: float = 0.0,
) -> RunState:
    """Apply one deterministic state transition and return a new immutable state."""
    if state.run_spec_hash != spec.identity:
        raise TransitionError("RunSpec identity does not match the run state")
    if state.is_terminal:
        raise TransitionError(f"terminal run cannot accept {event}")
    if (
        isinstance(cost_delta, bool)
        or not isinstance(cost_delta, (int, float))
        or not math.isfinite(cost_delta)
        or cost_delta < 0
    ):
        raise TransitionError("cost_delta must be finite and non-negative")
    if event not in _ALLOWED.get(state.status, set()):
        raise TransitionError(f"event {event!r} is not allowed from status {state.status!r}")

    if event == "approve":
        return replace(state, status="ready", revision=state.revision + 1)
    if event == "start_step":
        if state.steps_used >= spec.max_steps or state.cost_usd >= spec.max_cost_usd:
            return replace(state, status="budget_exhausted", revision=state.revision + 1)
        return replace(state, status="running", revision=state.revision + 1)
    if event == "candidate_ready":
        return replace(state, status="evaluating", revision=state.revision + 1)
    if event in {"child_failed", "interrupt", "evaluation_missing"}:
        return _next_after_attempt(
            state, spec, progressed=False, candidate_hash=None, cost_delta=cost_delta
        )
    if event == "evaluation_eligible":
        if candidate_hash is None:
            raise TransitionError("evaluation_eligible requires candidate_hash")
        return _next_after_attempt(
            state,
            spec,
            progressed=True,
            candidate_hash=candidate_hash,
            cost_delta=cost_delta,
        )
    if event == "evaluation_ineligible":
        return _next_after_attempt(
            state, spec, progressed=False, candidate_hash=None, cost_delta=cost_delta
        )
    if event == "start_supervisor":
        return replace(state, status="supervising", revision=state.revision + 1)
    if event == "supervisor_applied":
        return replace(
            state,
            status="ready",
            revision=state.revision + 1,
            consecutive_no_progress=0,
        )
    if event == "supervisor_failed":
        status = "succeeded" if state.best_candidate_hash else "no_result"
        return replace(state, status=status, revision=state.revision + 1)
    if event == "pause":
        return replace(
            state,
            status="paused",
            revision=state.revision + 1,
            paused_from=state.status,
        )
    if event == "resume":
        if state.paused_from not in {"ready", "supervision_required"}:
            raise TransitionError("paused run has no safe resume state")
        return replace(
            state,
            status=state.paused_from,
            revision=state.revision + 1,
            paused_from=None,
        )
    if event == "cancel":
        return replace(state, status="cancelled", revision=state.revision + 1)
    if event == "complete":
        status = "succeeded" if state.best_candidate_hash else "no_result"
        return replace(state, status=status, revision=state.revision + 1)

    raise TransitionError(f"unsupported event: {event}")
