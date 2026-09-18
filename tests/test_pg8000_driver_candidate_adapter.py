"""Contract tests for the pg8000 DB-API candidate adapter boundary.

These tests deliberately use small DB-API-shaped fakes instead of importing
pg8000. They pin the pg-llm-batch side of the candidate contract first, while
real pg8000 1.31.5 and PostgreSQL acceptance remains a separate mandatory gate
before any runtime dependency or default-driver change.
"""

from __future__ import annotations

from types import ModuleType

import pytest

from pg_llm_batch.pg8000_driver_candidate_adapter import (
    Pg8000CandidateAdapterError,
    Pg8000CandidateConnectionAdapter,
    Pg8000CandidateCursorAdapter,
    validate_pg8000_dbapi_module,
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
        self.close_count = 0
        self.close_error: BaseException | None = None
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

    def close(self) -> None:
        self.close_count += 1
        if self.close_error is not None:
            raise self.close_error

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


def _dbapi_module(
    *,
    apilevel: object = "2.0",
    paramstyle: object = "format",
    threadsafety: object = 1,
) -> ModuleType:
    """Build one exact module-shaped DB-API authority for candidate contract tests."""
    module = ModuleType("pg8000.dbapi")
    module.apilevel = apilevel
    module.paramstyle = paramstyle
    module.threadsafety = threadsafety
    return module


def test_candidate_dbapi_module_requires_dbapi_2_and_format_parameter_style() -> None:
    module = _dbapi_module()

    validate_pg8000_dbapi_module(module)

    module.paramstyle = "named"
    with pytest.raises(Pg8000CandidateAdapterError, match="parameter style is incompatible"):
        validate_pg8000_dbapi_module(module)

    module.paramstyle = "format"
    module.apilevel = "1.0"
    with pytest.raises(Pg8000CandidateAdapterError, match="API level is incompatible"):
        validate_pg8000_dbapi_module(module)


def test_candidate_dbapi_module_requires_module_only_connection_thread_safety() -> None:
    """Reject metadata that would misstate pg8000 connection-sharing semantics."""
    validate_pg8000_dbapi_module(_dbapi_module(threadsafety=1))

    for invalid in (0, 2, 3, True, "1"):
        with pytest.raises(
            Pg8000CandidateAdapterError,
            match="thread safety is incompatible",
        ):
            validate_pg8000_dbapi_module(_dbapi_module(threadsafety=invalid))


def test_candidate_dbapi_module_rejects_shaped_or_behavior_bearing_metadata() -> None:
    class _StringSubclass(str):
        pass

    with pytest.raises(Pg8000CandidateAdapterError, match="module identity is invalid"):
        validate_pg8000_dbapi_module(object())
    with pytest.raises(Pg8000CandidateAdapterError, match="API level is incompatible"):
        validate_pg8000_dbapi_module(_dbapi_module(apilevel=_StringSubclass("2.0")))
    with pytest.raises(Pg8000CandidateAdapterError, match="parameter style is incompatible"):
        validate_pg8000_dbapi_module(_dbapi_module(paramstyle=_StringSubclass("format")))


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


def test_candidate_cursor_context_owns_dbapi_cleanup_without_raw_context_dependency() -> None:
    raw = _FakeCursor()
    adapter = Pg8000CandidateCursorAdapter(raw)
    error = RuntimeError("boom")

    assert adapter.__enter__() is adapter
    assert raw.enter_count == 0
    assert adapter.__exit__(RuntimeError, error, None) is False
    assert raw.close_count == 1
    assert raw.exit_args is None


def test_candidate_cursor_context_preserves_application_error_over_cleanup_failure() -> None:
    """Cleanup failure must not replace the application error already in flight."""
    raw = _FakeCursor()
    adapter = Pg8000CandidateCursorAdapter(raw)
    application_error = ValueError("application")
    raw.close_error = RuntimeError("cleanup")

    with pytest.raises(ValueError) as caught:
        adapter.__exit__(ValueError, application_error, None)

    assert caught.value is application_error
    assert raw.close_count == 1


def test_candidate_cursor_context_propagates_cleanup_failure_without_application_error() -> None:
    """A close-only failure remains visible when no earlier error has priority."""
    raw = _FakeCursor()
    adapter = Pg8000CandidateCursorAdapter(raw)
    cleanup_error = RuntimeError("cleanup")
    raw.close_error = cleanup_error

    with pytest.raises(RuntimeError) as caught:
        adapter.__exit__(None, None, None)

    assert caught.value is cleanup_error
    assert raw.close_count == 1


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


def test_candidate_connection_validates_autocommit_and_owns_closed_state() -> None:
    raw = _FakeConnection()
    adapter = Pg8000CandidateConnectionAdapter(raw)

    adapter.set_autocommit(True)
    assert raw.autocommit is True
    assert adapter.is_closed() is False

    with pytest.raises(Pg8000CandidateAdapterError, match="autocommit is invalid"):
        adapter.set_autocommit(1)  # type: ignore[arg-type]

    raw.closed = 0
    assert adapter.is_closed() is False
    del raw.closed
    assert adapter.is_closed() is False

    adapter.close()
    assert raw.close_count == 1
    assert adapter.is_closed() is True


def test_candidate_connection_context_commits_and_closes_without_raw_context_dependency() -> None:
    raw = _FakeConnection()
    adapter = Pg8000CandidateConnectionAdapter(raw)

    assert adapter.__enter__() is adapter
    assert raw.enter_count == 0
    assert adapter.__exit__(None, None, None) is False
    assert raw.commit_count == 1
    assert raw.rollback_count == 0
    assert raw.close_count == 1
    assert raw.exit_args is None
    assert adapter.is_closed() is True


def test_candidate_connection_context_rolls_back_and_closes_on_exception() -> None:
    raw = _FakeConnection()
    adapter = Pg8000CandidateConnectionAdapter(raw)
    error = ValueError("bad")

    assert adapter.__enter__() is adapter
    assert raw.enter_count == 0
    assert adapter.__exit__(ValueError, error, None) is False
    assert raw.commit_count == 0
    assert raw.rollback_count == 1
    assert raw.close_count == 1
    assert raw.exit_args is None
    assert adapter.is_closed() is True
