from __future__ import annotations

import sqlite3

import pytest

from contracts import (
    ContinuationMemory,
    MutationReceipt,
    RunSpec,
    SandboxReceipt,
    SupervisorAdvice,
)
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
    assert store.schema_version() == 5


def test_store_migrates_phase0_schema_metadata_and_adds_phase1_tables(tmp_path):
    database = tmp_path / "legacy.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO schema_metadata(key, value) VALUES ('schema_version', '1');
        """
    )
    connection.close()

    store = RunStore(database)

    assert store.schema_version() == 5
    check = sqlite3.connect(database)
    tables = {
        row[0]
        for row in check.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name IN ('candidates','evaluations')"
        )
    }
    check.close()
    assert tables == {"candidates", "evaluations"}


def test_store_migrates_populated_v2_without_changing_existing_rows(tmp_path):
    database = tmp_path / "phase2-legacy.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO schema_metadata(key, value) VALUES ('schema_version', '2');
        CREATE TABLE runs (
            run_id TEXT PRIMARY KEY, run_spec_hash TEXT NOT NULL,
            spec_json TEXT NOT NULL, state_json TEXT NOT NULL
        );
        CREATE TABLE run_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT, run_id TEXT NOT NULL,
            event TEXT NOT NULL, revision INTEGER NOT NULL,
            state_hash TEXT NOT NULL, payload_json TEXT NOT NULL
        );
        CREATE TABLE candidates (
            candidate_hash TEXT PRIMARY KEY, run_id TEXT NOT NULL,
            candidate_json TEXT NOT NULL
        );
        CREATE TABLE evaluations (
            evaluation_hash TEXT PRIMARY KEY, run_id TEXT NOT NULL,
            candidate_hash TEXT NOT NULL, evaluation_json TEXT NOT NULL
        );
        INSERT INTO runs VALUES ('legacy-run', 'hash', '{}', '{}');
        INSERT INTO run_events(run_id,event,revision,state_hash,payload_json)
            VALUES ('legacy-run','approve',1,'state-hash','{}');
        INSERT INTO candidates VALUES ('candidate-hash','legacy-run','{}');
        INSERT INTO evaluations VALUES ('evaluation-hash','legacy-run','candidate-hash','{}');
        """
    )
    connection.close()

    store = RunStore(database)
    check = sqlite3.connect(database)
    counts = {
        "runs": check.execute("SELECT COUNT(*) FROM runs").fetchone()[0],
        "run_events": check.execute("SELECT COUNT(*) FROM run_events").fetchone()[0],
        "candidates": check.execute("SELECT COUNT(*) FROM candidates").fetchone()[0],
        "evaluations": check.execute("SELECT COUNT(*) FROM evaluations").fetchone()[0],
    }
    phase2_tables = {
        row[0]
        for row in check.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('continuation_memory','supervisor_advice')"
        )
    }
    check.close()

    assert store.schema_version() == 5
    assert counts == {"runs": 1, "run_events": 1, "candidates": 1, "evaluations": 1}
    assert phase2_tables == {"continuation_memory", "supervisor_advice"}


def continuation(spec, revision=1):
    return ContinuationMemory(
        run_spec_hash=spec.identity,
        memory_revision=revision,
        run_status="created",
        state_revision=0,
        best_candidate_hash=None,
        recent_candidate_hashes=(),
        recent_evaluation_hashes=(),
        recent_failure_signatures=(),
        tried_hypotheses=(),
        supervisor_advice_hash=None,
    )


def test_store_round_trips_revisioned_continuation_memory(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    spec = run_spec()
    store.create_run(spec)

    store.save_memory(spec.run_id, continuation(spec), expected_revision=0)

    assert store.load_memory(spec.run_id) == continuation(spec)


def test_store_rejects_stale_memory_revision(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    spec = run_spec()
    store.create_run(spec)
    store.save_memory(spec.run_id, continuation(spec), expected_revision=0)

    with pytest.raises(StorageConflictError, match="memory revision"):
        store.save_memory(spec.run_id, continuation(spec, 2), expected_revision=0)


def test_store_records_supervisor_advice(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    spec = run_spec()
    store.create_run(spec)
    advice = SupervisorAdvice(
        advice_id="advice-1",
        run_spec_hash=spec.identity,
        stagnation_evidence_hash="b" * 64,
        directions=("Try a distinct strategy",),
        prohibited_repeats=("baseline",),
    )

    store.record_supervisor_advice(spec.run_id, advice)

    assert store.supervisor_advice(spec.run_id) == [advice.to_dict()]


def test_store_records_append_only_mutation_receipt(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    spec = run_spec()
    store.create_run(spec)
    receipt = MutationReceipt(
        receipt_id="mutation-1",
        run_spec_hash=spec.identity,
        candidate_hash="b" * 64,
        evaluation_hash="c" * 64,
        repository_id="phase3-abcdef",
        baseline_tree_hash="d" * 64,
        mutated_tree_hash="e" * 64,
        mutation="filter_even",
        changed_paths=("calculator.py",),
        command_id="phase3.python-unittest.v1",
        exit_code=0,
        tests_passed=True,
        stdout_hash="f" * 64,
        stderr_hash="a" * 64,
        repository_retained=True,
        cleanup_status="retained",
    )

    store.record_mutation_receipt(spec.run_id, receipt)

    assert store.mutation_receipts(spec.run_id) == [receipt.to_dict()]
    assert RunStore(store.database_path).mutation_receipts(spec.run_id) == [receipt.to_dict()]
    connection = sqlite3.connect(store.database_path)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        connection.execute("UPDATE mutation_receipts SET receipt_json='{}'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        connection.execute("DELETE FROM mutation_receipts")
    connection.close()


def test_store_records_append_only_sandbox_receipt(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    spec = run_spec()
    store.create_run(spec)
    receipt = SandboxReceipt(
        receipt_id="sandbox-1",
        run_spec_hash=spec.identity,
        candidate_hash="b" * 64,
        evaluation_hash="c" * 64,
        image="python:3.13-alpine@sha256:" + "d" * 64,
        runner_hash="e" * 64,
        baseline_tree_hash="f" * 64,
        patch_hash="a" * 64,
        output_tree_hash="b" * 64,
        output_source_hash="c" * 64,
        policy_hash="d" * 64,
        command_id="phase4.python-unittest.v1",
        exit_code=0,
        tests_passed=True,
        stdout_hash="e" * 64,
        stderr_hash="f" * 64,
        artifact_relative_path="phase4-artifacts/phase4-abcdef/calculator.py",
        network_policy="none",
        artifact_retained=True,
        cleanup_status="retained",
    )

    store.record_sandbox_receipt(spec.run_id, receipt)

    assert RunStore(store.database_path).sandbox_receipts(spec.run_id) == [receipt.to_dict()]
    connection = sqlite3.connect(store.database_path)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        connection.execute("UPDATE sandbox_receipts SET receipt_json='{}'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        connection.execute("DELETE FROM sandbox_receipts")
    connection.close()


def test_store_migrates_populated_v3_memory_and_advice_to_v5(tmp_path):
    database = tmp_path / "v3.db"
    store = RunStore(database)
    spec = run_spec()
    store.create_run(spec)
    store.save_memory(spec.run_id, continuation(spec), expected_revision=0)
    advice = SupervisorAdvice(
        advice_id="advice-v3",
        run_spec_hash=spec.identity,
        stagnation_evidence_hash="b" * 64,
        directions=("Try one bounded direction",),
        prohibited_repeats=(),
    )
    store.record_supervisor_advice(spec.run_id, advice)
    connection = sqlite3.connect(database)
    connection.execute("DROP TABLE mutation_receipts")
    connection.execute("UPDATE schema_metadata SET value='3' WHERE key='schema_version'")
    connection.commit()
    connection.close()

    migrated = RunStore(database)

    assert migrated.schema_version() == 5
    assert migrated.load_memory(spec.run_id) == continuation(spec)
    assert migrated.supervisor_advice(spec.run_id) == [advice.to_dict()]
    check = sqlite3.connect(database)
    exists = {
        row[0]
        for row in check.execute(
            "SELECT name FROM sqlite_master WHERE type='table' "
            "AND name IN ('mutation_receipts','sandbox_receipts')"
        )
    }
    check.close()
    assert exists == {"mutation_receipts", "sandbox_receipts"}


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
