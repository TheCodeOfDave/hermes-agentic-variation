from __future__ import annotations

import hashlib
import json
import sqlite3
from dataclasses import asdict
from pathlib import Path
from typing import Any

try:
    from .contracts import RunSpec
    from .state_machine import RunState, apply_transition
except ImportError:  # Direct module execution in local tests.
    from contracts import RunSpec
    from state_machine import RunState, apply_transition

_SCHEMA_VERSION = 2


class StorageConflictError(RuntimeError):
    """Raised for duplicate identities or optimistic-concurrency conflicts."""


def _canonical_json(value: dict[str, Any]) -> str:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=True,
        allow_nan=False,
    )


def _state_json(state: RunState) -> str:
    return _canonical_json(asdict(state))


def _state_hash(state: RunState) -> str:
    return hashlib.sha256(_state_json(state).encode("utf-8")).hexdigest()


def _state_from_json(raw: str) -> RunState:
    return RunState(**json.loads(raw))


def _spec_from_json(raw: str) -> RunSpec:
    data = json.loads(raw)
    version = data.pop("contract_version", None)
    if version != RunSpec.contract_version:
        raise StorageConflictError(f"unsupported RunSpec contract version: {version}")
    for name in ("exclusions", "correctness_predicates", "score_keys", "allowed_toolsets"):
        data[name] = tuple(data[name])
    return RunSpec(**data)


class RunStore:
    """SQLite-backed Phase 0 run ledger with append-only transition evidence."""

    def __init__(self, database_path: str | Path):
        self.database_path = Path(database_path)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS schema_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
                INSERT OR IGNORE INTO schema_metadata(key, value)
                    VALUES ('schema_version', '2');
                UPDATE schema_metadata SET value = '2'
                    WHERE key = 'schema_version' AND CAST(value AS INTEGER) < 2;

                CREATE TABLE IF NOT EXISTS runs (
                    run_id TEXT PRIMARY KEY,
                    run_spec_hash TEXT NOT NULL,
                    spec_json TEXT NOT NULL,
                    state_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS run_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    event TEXT NOT NULL,
                    revision INTEGER NOT NULL,
                    state_hash TEXT NOT NULL,
                    payload_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS candidates (
                    candidate_hash TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    candidate_json TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS evaluations (
                    evaluation_hash TEXT PRIMARY KEY,
                    run_id TEXT NOT NULL REFERENCES runs(run_id),
                    candidate_hash TEXT NOT NULL REFERENCES candidates(candidate_hash),
                    evaluation_json TEXT NOT NULL
                );

                CREATE TRIGGER IF NOT EXISTS run_events_no_update
                BEFORE UPDATE ON run_events
                BEGIN
                    SELECT RAISE(ABORT, 'run_events is append-only');
                END;

                CREATE TRIGGER IF NOT EXISTS run_events_no_delete
                BEFORE DELETE ON run_events
                BEGIN
                    SELECT RAISE(ABORT, 'run_events is append-only');
                END;
                """
            )

    def schema_version(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM schema_metadata WHERE key = 'schema_version'"
            ).fetchone()
        if row is None:
            raise StorageConflictError("schema version is missing")
        return int(row["value"])

    def create_run(self, spec: RunSpec) -> RunState:
        state = RunState.new(spec.identity)
        spec_json = _canonical_json(spec.to_dict())
        state_json = _state_json(state)
        try:
            with self._connect() as connection:
                connection.execute("BEGIN IMMEDIATE")
                connection.execute(
                    "INSERT INTO runs(run_id, run_spec_hash, spec_json, state_json) "
                    "VALUES (?, ?, ?, ?)",
                    (spec.run_id, spec.identity, spec_json, state_json),
                )
                self._append_event(
                    connection,
                    run_id=spec.run_id,
                    event="run_created",
                    state=state,
                    payload={"run_spec_hash": spec.identity},
                )
        except sqlite3.IntegrityError as exc:
            raise StorageConflictError(f"run_id already exists: {spec.run_id}") from exc
        return state

    def load_run(self, run_id: str) -> tuple[RunSpec, RunState]:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT spec_json, state_json FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        if row is None:
            raise KeyError(run_id)
        return _spec_from_json(row["spec_json"]), _state_from_json(row["state_json"])

    def transition(
        self,
        run_id: str,
        event: str,
        *,
        expected_revision: int,
        candidate_hash: str | None = None,
        cost_delta: float = 0.0,
    ) -> RunState:
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT spec_json, state_json FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            spec = _spec_from_json(row["spec_json"])
            state = _state_from_json(row["state_json"])
            if state.revision != expected_revision:
                raise StorageConflictError(
                    f"revision mismatch: expected {expected_revision}, current {state.revision}"
                )

            updated = apply_transition(
                state,
                event,
                spec,
                candidate_hash=candidate_hash,
                cost_delta=cost_delta,
            )
            cursor = connection.execute(
                "UPDATE runs SET state_json = ? WHERE run_id = ? AND state_json = ?",
                (_state_json(updated), run_id, row["state_json"]),
            )
            if cursor.rowcount != 1:
                raise StorageConflictError("run changed during transition")
            self._append_event(
                connection,
                run_id=run_id,
                event=event,
                state=updated,
                payload={"candidate_hash": candidate_hash, "cost_delta": cost_delta},
            )
        return updated

    def events(self, run_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT id, event, revision, state_hash, payload_json "
                "FROM run_events WHERE run_id = ? ORDER BY id",
                (run_id,),
            ).fetchall()
        return [
            {
                "id": row["id"],
                "event": row["event"],
                "revision": row["revision"],
                "state_hash": row["state_hash"],
                "payload": json.loads(row["payload_json"]),
            }
            for row in rows
        ]

    def record_observation(self, run_id: str, event: str, payload: dict[str, Any]) -> None:
        """Append non-transition evidence without claiming a state change."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT state_json FROM runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if row is None:
                raise KeyError(run_id)
            self._append_event(
                connection,
                run_id=run_id,
                event=event,
                state=_state_from_json(row["state_json"]),
                payload=payload,
            )

    def record_candidate(self, run_id: str, candidate: Any) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO candidates(candidate_hash, run_id, candidate_json) VALUES (?, ?, ?)",
                (candidate.identity, run_id, _canonical_json(candidate.to_dict())),
            )

    def record_evaluation(self, run_id: str, evaluation: Any) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO evaluations(evaluation_hash, run_id, candidate_hash, evaluation_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    evaluation.identity,
                    run_id,
                    evaluation.candidate_hash,
                    _canonical_json(evaluation.to_dict()),
                ),
            )

    def record_attempt(self, run_id: str, candidate: Any, evaluation: Any) -> None:
        """Persist candidate and its evaluation in one SQLite transaction."""
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                "INSERT INTO candidates(candidate_hash, run_id, candidate_json) VALUES (?, ?, ?)",
                (candidate.identity, run_id, _canonical_json(candidate.to_dict())),
            )
            connection.execute(
                "INSERT INTO evaluations(evaluation_hash, run_id, candidate_hash, evaluation_json) "
                "VALUES (?, ?, ?, ?)",
                (
                    evaluation.identity,
                    run_id,
                    candidate.identity,
                    _canonical_json(evaluation.to_dict()),
                ),
            )

    def lineage(self, run_id: str) -> dict[str, list[dict[str, Any]]]:
        with self._connect() as connection:
            candidates = connection.execute(
                "SELECT candidate_json FROM candidates WHERE run_id = ? ORDER BY rowid",
                (run_id,),
            ).fetchall()
            evaluations = connection.execute(
                "SELECT evaluation_json FROM evaluations WHERE run_id = ? ORDER BY rowid",
                (run_id,),
            ).fetchall()
        return {
            "candidates": [json.loads(row["candidate_json"]) for row in candidates],
            "evaluations": [json.loads(row["evaluation_json"]) for row in evaluations],
        }

    @staticmethod
    def _append_event(
        connection: sqlite3.Connection,
        *,
        run_id: str,
        event: str,
        state: RunState,
        payload: dict[str, Any],
    ) -> None:
        connection.execute(
            "INSERT INTO run_events(run_id, event, revision, state_hash, payload_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (run_id, event, state.revision, _state_hash(state), _canonical_json(payload)),
        )
