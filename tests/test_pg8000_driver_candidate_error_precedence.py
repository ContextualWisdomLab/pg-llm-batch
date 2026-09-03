"""Regression tests for candidate PostgreSQL transaction cleanup precedence.

The pg8000 anti-corruption adapter must attempt connection cleanup after a
transaction failure without letting a later close failure replace the earlier
commit or rollback failure. These tests keep that recovery contract independent
from the real-driver PostgreSQL smoke gate.
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
