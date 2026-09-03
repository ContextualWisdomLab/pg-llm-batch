"""Regression tests for candidate PostgreSQL transaction cleanup precedence.

The pg8000 anti-corruption adapter must attempt connection cleanup after a
transaction failure without letting a later close failure replace the earlier
commit or rollback failure. An application exception also remains primary when
rollback succeeds but later connection cleanup fails. Direct connection
execution must likewise close the internally created cursor when execution
fails, because the caller never receives that cursor and therefore cannot
release it. These tests keep that recovery contract independent from the
real-driver PostgreSQL smoke gate.
"""

from __future__ import annotations

import pytest

from pg_llm_batch.pg8000_driver_candidate_adapter import (
    Pg8000CandidateConnectionAdapter,
)


class _TransactionAndCloseFailureConnection:
    """Expose deterministic transaction and close failures for precedence tests."""

    def __init__(self, *, fail_commit: bool) -> None:
        self.fail_commit = fail_commit
        self.commit_count = 0
        self.rollback_count = 0
        self.close_count = 0

    def commit(self) -> None:
        self.commit_count += 1
        if self.fail_commit:
            raise RuntimeError("commit failed")

    def rollback(self) -> None:
        self.rollback_count += 1
        if not self.fail_commit:
            raise RuntimeError("rollback failed")

    def close(self) -> None:
        self.close_count += 1
        raise OSError("close failed")


class _RollbackSuccessCloseFailureConnection:
    """Succeed rollback but fail cleanup after an application exception."""

    def __init__(self) -> None:
        self.rollback_count = 0
        self.close_count = 0

    def rollback(self) -> None:
        self.rollback_count += 1

    def close(self) -> None:
        self.close_count += 1
        raise OSError("close failed")


class _ExecuteAndCloseFailureCursor:
    """Fail direct execution and optionally fail the required cursor cleanup."""

    def __init__(self, *, fail_close: bool) -> None:
        self.fail_close = fail_close
        self.execute_count = 0
        self.close_count = 0

    def execute(self, query: str, params: object | None = None) -> None:
        """Raise the primary execution failure after recording one attempt."""
        del query, params
        self.execute_count += 1
        raise RuntimeError("execute failed")

    def close(self) -> None:
        """Record cleanup and optionally expose a secondary cleanup failure."""
        self.close_count += 1
        if self.fail_close:
            raise OSError("cursor close failed")


class _ExecuteFailureConnection:
    """Return one retained failing cursor to the connection adapter."""

    def __init__(self, cursor: _ExecuteAndCloseFailureCursor) -> None:
        self.cursor_value = cursor

    def cursor(self) -> _ExecuteAndCloseFailureCursor:
        """Return the exact cursor whose ownership transfers to direct execute."""
        return self.cursor_value


def test_candidate_context_preserves_commit_failure_when_close_also_fails() -> None:
    raw = _TransactionAndCloseFailureConnection(fail_commit=True)
    adapter = Pg8000CandidateConnectionAdapter(raw)

    with pytest.raises(RuntimeError, match="commit failed"):
        adapter.__exit__(None, None, None)

    assert raw.commit_count == 1
    assert raw.rollback_count == 0
    assert raw.close_count == 1
    assert adapter.is_closed() is False


def test_candidate_context_preserves_rollback_failure_when_close_also_fails() -> None:
    raw = _TransactionAndCloseFailureConnection(fail_commit=False)
    adapter = Pg8000CandidateConnectionAdapter(raw)
    application_error = ValueError("application failed")

    with pytest.raises(RuntimeError, match="rollback failed"):
        adapter.__exit__(ValueError, application_error, None)

    assert raw.commit_count == 0
    assert raw.rollback_count == 1
    assert raw.close_count == 1
    assert adapter.is_closed() is False


def test_candidate_context_preserves_application_error_when_only_close_fails() -> None:
    """Cleanup failure must not replace an application error after rollback."""
    raw = _RollbackSuccessCloseFailureConnection()
    adapter = Pg8000CandidateConnectionAdapter(raw)
    application_error = ValueError("application failed")

    with pytest.raises(ValueError) as caught:
        adapter.__exit__(ValueError, application_error, None)

    assert caught.value is application_error
    assert raw.rollback_count == 1
    assert raw.close_count == 1
    assert adapter.is_closed() is False


@pytest.mark.parametrize("fail_close", [False, True])
def test_candidate_direct_execute_closes_cursor_and_preserves_primary_failure(
    fail_close: bool,
) -> None:
    raw_cursor = _ExecuteAndCloseFailureCursor(fail_close=fail_close)
    adapter = Pg8000CandidateConnectionAdapter(_ExecuteFailureConnection(raw_cursor))

    with pytest.raises(RuntimeError, match="execute failed"):
        adapter.execute("SELECT %s", (1,))

    assert raw_cursor.execute_count == 1
    assert raw_cursor.close_count == 1
