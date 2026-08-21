from __future__ import annotations

import sqlite3

import pytest

from contracts import RunSpec
from state_machine import TransitionError
from storage import RunStore, StorageConflictError

HEX_A = "a" * 64


def run_spec() -> RunSpec:
    return RunSpec(
        run_id="run-storage",
        target_root="/workspace/example",
        seed_digest=HEX_A,
        objective="Exercise the Phase 0 state ledger.",
        exclusions=("No network",),
        evaluator_id="fixture.score.v1",
        evaluator_config={"score": 1},
        correctness_predicates=("tests_pass",),
        score_keys=("score",),
        comparison="maximize",
        allowed_toolsets=("file",),
        network_policy="disabled",
        max_steps=3,
        max_wall_seconds=60,
        max_cost_usd=1.0,
        no_progress_limit=2,
        approval_receipt="approved",
    )


def test_store_creates_schema_and_round_trips_immutable_run(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    spec = run_spec()

    created = store.create_run(spec)
    loaded_spec, loaded_state = store.load_run(spec.run_id)

    assert created.status == "created"
    assert loaded_spec.identity == spec.identity
    assert loaded_state == created
    assert store.schema_version() == 1


def test_store_rejects_duplicate_run_id(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    spec = run_spec()
    store.create_run(spec)

    with pytest.raises(StorageConflictError, match="already exists"):
        store.create_run(spec)


def test_transition_is_atomic_and_uses_optimistic_revision_check(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    spec = run_spec()
    store.create_run(spec)

    approved = store.transition(spec.run_id, "approve", expected_revision=0)
    assert approved.status == "ready"
    assert approved.revision == 1

    with pytest.raises(StorageConflictError, match="revision"):
        store.transition(spec.run_id, "start_step", expected_revision=0)

    _, persisted = store.load_run(spec.run_id)
    assert persisted == approved


def test_failed_transition_writes_neither_state_nor_event(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    spec = run_spec()
    store.create_run(spec)

    with pytest.raises(TransitionError):
        store.transition(spec.run_id, "start_step", expected_revision=0)

    _, state = store.load_run(spec.run_id)
    assert state.status == "created"
    assert [event["event"] for event in store.events(spec.run_id)] == ["run_created"]


def test_event_ledger_is_append_only_and_ordered(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    spec = run_spec()
    store.create_run(spec)
    store.transition(spec.run_id, "approve", expected_revision=0)
    store.transition(spec.run_id, "pause", expected_revision=1)

    events = store.events(spec.run_id)
    assert [event["event"] for event in events] == ["run_created", "approve", "pause"]
    assert [event["revision"] for event in events] == [0, 1, 2]

    connection = sqlite3.connect(tmp_path / "runs.db")
    with pytest.raises(sqlite3.DatabaseError):
        connection.execute("UPDATE run_events SET event = 'tampered' WHERE id = 1")
