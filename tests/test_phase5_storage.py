from __future__ import annotations

import sqlite3
from types import SimpleNamespace
import pytest

from contracts import Candidate, EvaluationResult
from storage import RunStore
from test_storage import run_spec


def objects(spec):
    candidate = Candidate(
        "phase5-candidate",
        spec.identity,
        None,
        "b" * 64,
        "c" * 64,
        ("calculator.py", "filters.py"),
        "bounded",
    )
    evaluation = EvaluationResult(
        "phase5-evaluation",
        candidate.identity,
        spec.identity,
        "phase5.immutable-evaluator.v1",
        True,
        {"passed": 1},
        {"passed": 0},
        True,
        "passed",
        ("d" * 64,),
    )
    receipt = SimpleNamespace(identity="e" * 64, to_dict=lambda: {"receipt_id": "phase5-receipt"})
    return candidate, evaluation, receipt


def test_schema_v6_atomic_patch_set_receipt_is_append_only(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    spec = run_spec()
    store.create_run(spec)
    candidate, evaluation, receipt = objects(spec)
    store.record_patch_set_attempt(spec.run_id, candidate, evaluation, receipt)
    assert store.schema_version() == 6
    assert store.patch_set_receipts(spec.run_id) == [{"receipt_id": "phase5-receipt"}]
    connection = sqlite3.connect(store.database_path)
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        connection.execute("UPDATE patch_set_receipts SET receipt_json='{}'")
    with pytest.raises(sqlite3.DatabaseError, match="append-only"):
        connection.execute("DELETE FROM patch_set_receipts")
    connection.close()


def test_schema_v6_attempt_rolls_back_candidate_and_evaluation_on_receipt_error(tmp_path):
    store = RunStore(tmp_path / "runs.db")
    spec = run_spec()
    store.create_run(spec)
    candidate, evaluation, receipt = objects(spec)
    store.record_patch_set_attempt(spec.run_id, candidate, evaluation, receipt)
    candidate2 = Candidate(
        "phase5-candidate-2",
        spec.identity,
        None,
        "f" * 64,
        "a" * 64,
        ("calculator.py", "filters.py"),
        "bounded",
    )
    evaluation2 = EvaluationResult(
        "phase5-evaluation-2",
        candidate2.identity,
        spec.identity,
        "phase5.immutable-evaluator.v1",
        True,
        {"passed": 1},
        {"passed": 0},
        True,
        "passed",
        ("d" * 64,),
    )
    with pytest.raises(sqlite3.IntegrityError):
        store.record_patch_set_attempt(spec.run_id, candidate2, evaluation2, receipt)
    assert all(
        row["candidate_id"] != "phase5-candidate-2"
        for row in store.lineage(spec.run_id)["candidates"]
    )


def test_schema_v5_to_v6_migration_error_rolls_back_every_statement(tmp_path):
    database = tmp_path / "populated-v5.db"
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE schema_metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO schema_metadata VALUES ('schema_version', '5');
        CREATE TABLE v5_payload (id INTEGER PRIMARY KEY, value TEXT NOT NULL);
        INSERT INTO v5_payload(value) VALUES ('preserve-me');
        CREATE VIEW patch_set_receipts AS SELECT id FROM v5_payload;
        """
    )
    connection.close()

    with pytest.raises(sqlite3.OperationalError, match="patch_set_receipts"):
        RunStore(database)

    connection = sqlite3.connect(database)
    assert connection.execute(
        "SELECT value FROM schema_metadata WHERE key='schema_version'"
    ).fetchone()[0] == "5"
    assert connection.execute("SELECT value FROM v5_payload").fetchone()[0] == "preserve-me"
    assert connection.execute(
        "SELECT COUNT(*) FROM sqlite_master WHERE type='table' AND name='candidates'"
    ).fetchone()[0] == 0
    connection.close()