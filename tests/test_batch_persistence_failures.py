# SPDX-License-Identifier: Apache-2.0
"""Failure-path coverage for transactional batch persistence."""

from __future__ import annotations

import pytest

from pg_llm_batch import orchestrator as orch_mod
from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.orchestrator import PostgresBatchOrchestrator


BATCH_UUID = "11111111-1111-1111-1111-111111111111"
REQUEST_UUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
FILE_UUID = "bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"
QUEUE_UUID = "cccccccc-cccc-cccc-cccc-cccccccccccc"


class Counter:
    """Minimal persistence limit provider."""

    azure_max_files_per_job = 1


class Cursor:
    """Drive one selected transactional failure mode."""

    def __init__(self, mode: str) -> None:
        self.mode = mode
        self.next_one = None
        self.next_all = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def execute(self, sql, params):
        self.rowcount = 0
        if "SELECT queue_uuid" in sql:
            self.next_one = None if self.mode == "missing_batch" else (QUEUE_UUID,)
        elif "SELECT file_path" in sql:
            self.next_all = []
        elif "RETURNING file_uuid" in sql:
            self.next_one = None if self.mode == "missing_file_uuid" else (FILE_UUID,)
        elif "UPDATE llm_requests" in sql:
            self.rowcount = 0 if self.mode == "assignment_mismatch" else len(params[2])

    def executemany(self, _sql, _params):
        return None

    def fetchone(self):
        return self.next_one

    def fetchall(self):
        return self.next_all


class Connection:
    """Record whether the persistence transaction committed."""

    def __init__(self, mode: str) -> None:
        self.cursor_value = Cursor(mode)
        self.autocommit = True
        self.commits = 0

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return None

    def cursor(self):
        return self.cursor_value

    def commit(self):
        self.commits += 1


class _CursorPort:
    """Expose failure-mode row-count evidence through the driver cursor contract."""

    def __init__(self, cursor: Cursor) -> None:
        self._cursor = cursor

    def __enter__(self):
        self._cursor.__enter__()
        return self

    def __exit__(self, *exc):
        return self._cursor.__exit__(*exc)

    def execute(self, sql, params=None):
        self._cursor.execute(sql, params)
        return self

    def executemany(self, sql, params):
        self._cursor.executemany(sql, params)
        return self

    def fetchone(self):
        return self._cursor.fetchone()

    def fetchall(self):
        return self._cursor.fetchall()

    def row_count(self):
        return self._cursor.rowcount


class _ConnectionPort:
    """Preserve one failure-mode transaction while satisfying the driver port."""

    def __init__(self, connection: Connection) -> None:
        self._connection = connection

    def __enter__(self):
        self._connection.__enter__()
        return self

    def __exit__(self, *exc):
        return self._connection.__exit__(*exc)

    def cursor(self):
        return _CursorPort(self._connection.cursor())

    def set_autocommit(self, enabled):
        self._connection.autocommit = enabled

    def commit(self):
        self._connection.commit()


class _Driver:
    """Return one deterministic failure connection through the driver boundary."""

    def __init__(self, connection: Connection) -> None:
        self.connection = connection

    def connect(self, _dsn, **_kwargs):
        return _ConnectionPort(self.connection)

    def jsonb(self, value):
        return value


def _orchestrator(monkeypatch, mode: str):
    connection = Connection(mode)
    driver = _Driver(connection)
    monkeypatch.setattr(orch_mod, "retained_postgres_driver", lambda: driver)
    return PostgresBatchOrchestrator("postgresql://x"), connection


def _payload():
    return {
        "part_index": 0,
        "record_count": 1,
        "total_tokens": 2,
        "request_ids": [REQUEST_UUID],
        "lines": ['{"custom_id":"r1"}'],
    }


def test_missing_batch_row_aborts_persistence(monkeypatch):
    """A concurrently deleted batch never leaves orphan payload rows."""
    orchestrator, connection = _orchestrator(monkeypatch, "missing_batch")

    with pytest.raises(ValidationError, match="batch disappeared"):
        orchestrator._persist_payloads([_payload()], BATCH_UUID, Counter())

    assert connection.commits == 0


def test_missing_returned_file_uuid_aborts_persistence(monkeypatch):
    """An unexpected INSERT result fails before request assignment."""
    orchestrator, connection = _orchestrator(monkeypatch, "missing_file_uuid")

    with pytest.raises(RuntimeError, match="did not return file_uuid"):
        orchestrator._persist_payloads([_payload()], BATCH_UUID, Counter())

    assert connection.commits == 0


def test_request_assignment_mismatch_aborts_persistence(monkeypatch):
    """Concurrent request mutation rolls back every prepared artifact."""
    orchestrator, connection = _orchestrator(monkeypatch, "assignment_mismatch")

    with pytest.raises(ValidationError, match="assignment changed") as exc_info:
        orchestrator._persist_payloads([_payload()], BATCH_UUID, Counter())

    assert exc_info.value.details["field"] == "request_ids"
    assert connection.commits == 0
