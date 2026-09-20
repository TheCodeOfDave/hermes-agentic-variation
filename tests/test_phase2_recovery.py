"""Checkpoint recovery in fresh interpreters; no Hermes runtime or model calls."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import sqlite3
import subprocess
import sys

import pytest

from contracts import Candidate, SupervisorAdvice
from evaluator import FixtureOutcome
from phase2 import Phase2Controller, Phase2DisabledError
from storage import RunStore


ROOT = Path(__file__).resolve().parents[1]


class NoChildren:
    def __init__(self):
        self.calls = 0

    def run(self, **request):
        self.calls += 1
        raise AssertionError("Recovery must not launch children")


def controller(database, *, enabled=True):
    return Phase2Controller(
        store=RunStore(database), lifecycle=NoChildren(), enabled=enabled, wait_seconds=30
    )


def transition(subject, run_id, event):
    _, state = subject.store.load_run(run_id)
    return subject.store.transition(run_id, event, expected_revision=state.revision)


def dump(database):
    with sqlite3.connect(database) as connection:
        return tuple(connection.iterdump())


# -I prevents ambient PYTHONPATH/user-site modules from shadowing this checkout.
# Only committed SQLite checkpoints cross the process boundary.
RESTART = '''
import json
from pathlib import Path
import sys
sys.path.insert(0, sys.argv[1])
import phase2
from storage import RunStore
assert Path(phase2.__file__).resolve().parent == Path(sys.argv[1]).resolve()
class NoChildren:
    calls = 0
    def run(self, **request):
        self.calls += 1
        raise AssertionError("Recovery must not launch children")
lifecycle = NoChildren()
c = phase2.Phase2Controller(
    store=RunStore(sys.argv[2]), lifecycle=lifecycle, enabled=True, wait_seconds=30
)
rid = sys.argv[3]
first = c.reconcile(rid)
state = c.status(rid)
events = c.store.events(rid)
memory = c.memory(rid)
lineage = c.store.lineage(rid)
advice = c.store.supervisor_advice(rid)
assert c.reconcile(rid)["action"] == "noop"
assert c.status(rid) == state
assert c.store.events(rid) == events
assert c.memory(rid) == memory
assert c.store.lineage(rid) == lineage
assert c.store.supervisor_advice(rid) == advice
assert memory["stale"] is False
assert lifecycle.calls == 0
print(json.dumps({"first": first, "state": state, "memory": memory}))
'''


@pytest.mark.parametrize("checkpoint,action,status", [
    ("running_missing", "interrupted", "supervision_required"),
    ("evaluating_missing", "evaluation_missing", "supervision_required"),
    ("running_eligible", "evaluation_replayed", "ready"),
    ("evaluating_eligible", "evaluation_replayed", "ready"),
    ("evaluating_ineligible", "evaluation_replayed", "supervision_required"),
    ("supervising_missing", "supervisor_missing", "no_result"),
    ("supervising_advice", "supervisor_replayed", "ready"),
])
def test_reconcile_checkpoint_in_fresh_process(tmp_path, checkpoint, action, status):
    database = tmp_path / "recovery.db"
    subject = controller(database)
    run_id = subject.create_run(objective="recovery fixture", approval_receipt="test-only")["run_id"]
    transition(subject, run_id, "start_step")
    candidate = None
    advice = None
    if checkpoint.startswith("supervising"):
        transition(subject, run_id, "interrupt")
        transition(subject, run_id, "start_supervisor")
        if checkpoint == "supervising_advice":
            spec, _ = subject.store.load_run(run_id)
            advice = SupervisorAdvice(
                advice_id=run_id + "-supervisor-1", run_spec_hash=spec.identity,
                stagnation_evidence_hash=subject.store.load_memory(run_id).identity,
                directions=("Try an untried permitted strategy",), prohibited_repeats=(),
            )
            subject.store.record_supervisor_advice(run_id, advice)
    else:
        if checkpoint in {"running_eligible", "evaluating_eligible", "evaluating_ineligible"}:
            spec, _ = subject.store.load_run(run_id)
            artifact = b'{"strategy":"memoized_lookup","rationale":"recovery fixture"}'
            candidate = Candidate(
                candidate_id=run_id + "-candidate-1", run_spec_hash=spec.identity,
                parent_candidate_id=None, artifact_digest=hashlib.sha256(artifact).hexdigest(),
                child_result_hash="a" * 64, changed_paths=("fixtures/strategy.json",),
                hypothesis="recovery fixture",
            )
            evaluation = subject.evaluator.evaluate(
                spec, candidate, baseline_scores={"operations": 10.0},
                outcome=FixtureOutcome(
                    correctness={"strategy_allowed": True, "output_matches": True},
                    scores={"operations": 10.0 if checkpoint == "evaluating_ineligible" else 5.0},
                    evidence=artifact,
                ),
            )
            subject.store.record_attempt(run_id, candidate, evaluation)
        if checkpoint.startswith("evaluating"):
            transition(subject, run_id, "candidate_ready")
    assert subject.memory(run_id)["stale"] is True
    lineage_before = subject.store.lineage(run_id)
    process = subprocess.run(
        [sys.executable, "-I", "-c", RESTART, str(ROOT), str(database), run_id],
        cwd=tmp_path, capture_output=True, text=True, timeout=30, check=False,
    )
    assert process.returncode == 0, process.stdout + process.stderr
    result = json.loads(process.stdout)
    assert result["first"]["action"] == action
    assert result["state"]["status"] == status
    assert result["state"]["steps_used"] == 1
    reopened = controller(database)
    assert reopened.status(run_id) == result["state"]
    assert reopened.memory(run_id) == result["memory"]
    assert reopened.store.lineage(run_id) == lineage_before
    assert subject.lifecycle.calls == reopened.lifecycle.calls == 0
    if candidate is not None and checkpoint != "evaluating_ineligible":
        assert result["state"]["best_candidate_hash"] == candidate.identity
    else:
        assert result["state"]["best_candidate_hash"] is None
    if advice is not None:
        assert result["memory"]["supervisor_advice_hash"] == advice.identity
    failure = {
        "running_missing": "INTERRUPTED",
        "evaluating_missing": "EVALUATION_MISSING",
        "supervising_missing": "SUPERVISOR_MISSING",
    }.get(checkpoint)
    if failure:
        assert failure in result["memory"]["recent_failure_signatures"]


@pytest.mark.parametrize("operation", ["create_run", "step", "supervise", "reconcile"])
def test_closed_gate_does_not_mutate_any_ledger_rows(tmp_path, operation):
    database = tmp_path / "denial.db"
    setup = controller(database)
    run_id = setup.create_run(objective="denial fixture", approval_receipt="test-only")["run_id"]
    transition(setup, run_id, "start_step")
    subject = controller(database, enabled=False)
    before = dump(database)
    with pytest.raises(Phase2DisabledError, match="phase2_enabled"):
        if operation == "create_run":
            subject.create_run(objective="denied", approval_receipt="test-only")
        else:
            getattr(subject, operation)(run_id)
    assert dump(database) == before
    assert subject.lifecycle.calls == 0
