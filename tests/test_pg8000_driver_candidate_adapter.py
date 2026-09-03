"""Contract tests for the pg8000 DB-API candidate adapter boundary.

These tests deliberately use small DB-API-shaped fakes instead of importing
pg8000. They pin the pg-llm-batch side of the candidate contract first, while
real pg8000 1.31.5 and PostgreSQL acceptance remains a separate mandatory gate
before any runtime dependency or default-driver change.
"""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.pg8000_driver_candidate_adapter import (
    Pg8000CandidateAdapterError,
    Pg8000CandidateConnectionAdapter,
    Pg8000CandidateCursorAdapter,
)
from pg_llm_batch.postgres_driver_port import PostgresConnectionPort, PostgresCursorPort


class _FakeCursor:
    """Record DB-API cursor calls while exposing configurable materialized rows."""

    def __init__(self) -> None:
        self.execute_calls: list[tuple[str, object | None]] = []
        self.executemany_calls: list[tuple[str, object]] = []
        self.fetchone_value: object | None = None
        self.fetchmany_value: list[object] = []
        self.fetchall_value: list[object] = []
        self.rowcount: object = 0
        self.enter_count = 0
        self.exit_args: tuple[object, object, object] | None = None

    def execute(self, query: str, params: object | None = None) -> _FakeCursor:
        self.execute_calls.append((query, params))
        return self

    def executemany(self, query: str, params_seq: object) -> _FakeCursor:
        self.executemany_calls.append((query, params_seq))
        return self

    def fetchone(self) -> object | None:
        return self.fetchone_value

    def fetchmany(self, size: int) -> list[object]:
        assert size > 0
        return self.fetchmany_value

    def fetchall(self) -> list[object]:
        return self.fetchall_value

    def __enter__(self) -> _FakeCursor:
        self.enter_count += 1
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self.exit_args = (exc_type, exc, traceback)
        return False


class _FakeConnection:
    """Record one connection's transaction and cursor activity."""

    def __init__(self) -> None:
        self.cursor_value = _FakeCursor()
        self.autocommit: object = False
        self.closed: object = False
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0
        self.enter_count = 0
        self.exit_args: tuple[object, object, object] | None = None

    def cursor(self) -> _FakeCursor:
        return self.cursor_value

    def commit(self) -> None:
        self.commit_count += 1

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.close_count += 1
        self.closed = True

    def __enter__(self) -> _FakeConnection:
        self.enter_count += 1
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        self.exit_args = (exc_type, exc, traceback)
        return False


def test_candidate_cursor_preserves_parameter_binding_and_wrapper_identity() -> None:
    raw = _FakeCursor()
    adapter = Pg8000CandidateCursorAdapter(raw)
    params = ("tenant-a", 7)

    result = adapter.execute("SELECT %s, %s", params)
    many_result = adapter.executemany("INSERT INTO t VALUES (%s)", [(1,), (2,)])

    assert isinstance(adapter, PostgresCursorPort)
    assert result is adapter
    assert many_result is adapter
    assert raw.execute_calls == [("SELECT %s, %s", params)]
    assert raw.executemany_calls == [("INSERT INTO t VALUES (%s)", [(1,), (2,)])]


def test_candidate_cursor_normalizes_pg8000_list_rows_to_tuples() -> None:
    raw = _FakeCursor()
    adapter = Pg8000CandidateCursorAdapter(raw)

    assert adapter.fetchone() is None

    raw.fetchone_value = ["one", 1]
    raw.fetchmany_value = [["two", 2], ("three", 3)]
    raw.fetchall_value = [("four", 4), ["five", 5]]

    assert adapter.fetchone() == ("one", 1)
    assert adapter.fetchmany(2) == [("two", 2), ("three", 3)]
    assert adapter.fetchall() == [("four", 4), ("five", 5)]


def test_candidate_cursor_rejects_non_positional_rows_and_invalid_fetch_size() -> None:
    raw = _FakeCursor()
    adapter = Pg8000CandidateCursorAdapter(raw)
    raw.fetchone_value = {"id": 1}

    with pytest.raises(Pg8000CandidateAdapterError, match="result row is invalid"):
        adapter.fetchone()
    with pytest.raises(Pg8000CandidateAdapterError, match="fetch size is invalid"):
        adapter.fetchmany(0)
    with pytest.raises(Pg8000CandidateAdapterError, match="fetch size is invalid"):
        adapter.fetchmany(True)


def test_candidate_cursor_normalizes_unknown_row_count_and_rejects_bad_sentinels() -> None:
    raw = _FakeCursor()
    adapter = Pg8000CandidateCursorAdapter(raw)

    raw.rowcount = -1
    assert adapter.row_count() is None
    raw.rowcount = 4
    assert adapter.row_count() == 4
    raw.rowcount = -2
    with pytest.raises(Pg8000CandidateAdapterError, match="row count is invalid"):
        adapter.row_count()
    raw.rowcount = "4"
    with pytest.raises(Pg8000CandidateAdapterError, match="row count is invalid"):
        adapter.row_count()


def test_candidate_cursor_context_delegates_cleanup_without_suppressing_errors() -> None:
    raw = _FakeCursor()
    adapter = Pg8000CandidateCursorAdapter(raw)
    error = RuntimeError("boom")

    assert adapter.__enter__() is adapter
    assert raw.enter_count == 1
    assert adapter.__exit__(RuntimeError, error, None) is False
    assert raw.exit_args == (RuntimeError, error, None)


def test_candidate_connection_uses_one_raw_connection_for_execution_and_transactions() -> None:
    raw = _FakeConnection()
    adapter = Pg8000CandidateConnectionAdapter(raw)

    cursor = adapter.cursor()
    direct_cursor = adapter.execute("SELECT %s", (9,))
    adapter.commit()
    adapter.rollback()

    assert isinstance(adapter, PostgresConnectionPort)
    assert isinstance(cursor, Pg8000CandidateCursorAdapter)
    assert isinstance(direct_cursor, Pg8000CandidateCursorAdapter)
    assert raw.cursor_value.execute_calls == [("SELECT %s", (9,))]
    assert raw.commit_count == 1
    assert raw.rollback_count == 1


def test_candidate_connection_validates_autocommit_and_closed_state() -> None:
    raw = _FakeConnection()
    adapter = Pg8000CandidateConnectionAdapter(raw)

    adapter.set_autocommit(True)
    assert raw.autocommit is True
    assert adapter.is_closed() is False

    with pytest.raises(Pg8000CandidateAdapterError, match="autocommit is invalid"):
        adapter.set_autocommit(1)  # type: ignore[arg-type]

    raw.closed = 0
    with pytest.raises(Pg8000CandidateAdapterError, match="closed state is unavailable"):
        adapter.is_closed()

    del raw.closed
    with pytest.raises(Pg8000CandidateAdapterError, match="closed state is unavailable"):
        adapter.is_closed()


def test_candidate_connection_close_and_context_delegate_to_raw_connection() -> None:
    raw = _FakeConnection()
    adapter = Pg8000CandidateConnectionAdapter(raw)
    error = ValueError("bad")

    assert adapter.__enter__() is adapter
    assert raw.enter_count == 1
    assert adapter.__exit__(ValueError, error, None) is False
    assert raw.exit_args == (ValueError, error, None)

    adapter.close()
    assert raw.close_count == 1
    assert adapter.is_closed() is True
