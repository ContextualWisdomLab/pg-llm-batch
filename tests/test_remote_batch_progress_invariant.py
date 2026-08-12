# SPDX-License-Identifier: Apache-2.0
"""Regression tests for durable lifecycle progress invariants."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch import db


class _Cursor:
    """Capture lifecycle SQL without contacting PostgreSQL."""

    def __init__(self, driver: "_Psycopg") -> None:
        self.driver = driver

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        """Record one SQL statement and its bound parameters."""
        self.driver.executions.append((sql, params))


class _Connection:
    """Expose the minimal connection surface used by lifecycle persistence."""

    def __init__(self, driver: "_Psycopg") -> None:
        self.driver = driver

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def cursor(self) -> _Cursor:
        """Return one SQL-capturing cursor."""
        return _Cursor(self.driver)

    def commit(self) -> None:
        """Record an explicit transaction commit."""
        self.driver.commits += 1


class _Psycopg:
    """Minimal deterministic psycopg replacement for boundary tests."""

    def __init__(self) -> None:
        self.executions: list[tuple[str, Any]] = []
        self.connections: list[str] = []
        self.commits = 0

    def connect(self, dsn: str) -> _Connection:
        """Record the selected target before returning a fake connection."""
        self.connections.append(dsn)
        return _Connection(self)


def _compact_sql(sql: str) -> str:
    """Normalize SQL whitespace for semantic contract assertions."""
    return " ".join(sql.split())


def test_persistence_rejects_impossible_same_observation_before_database(
    monkeypatch: Any,
) -> None:
    """Completed plus failed requests cannot exceed the observed total."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)

    with pytest.raises(ValueError, match="request_counts progress is inconsistent"):
        db.persist_remote_batch_state(
            "postgresql://example",
            "primary",
            {
                "id": "batch-1",
                "status": "in_progress",
                "request_counts": {"total": 1, "completed": 1, "failed": 1},
            },
            observation_order=1,
        )

    assert driver.connections == []
    assert driver.executions == []
    assert driver.commits == 0


def test_upsert_guards_combined_monotonic_progress_invariant(monkeypatch: Any) -> None:
    """Independent monotonic counter updates cannot create impossible progress."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)

    db.persist_remote_batch_state(
        "postgresql://example",
        "primary",
        {
            "id": "batch-1",
            "status": "in_progress",
            "request_counts": {"total": 10, "completed": 9, "failed": 0},
        },
        observation_order=1,
    )

    sql = _compact_sql(driver.executions[1][0])
    expected_guard = (
        "GREATEST( llm_remote_batch_jobs.completed_requests, "
        "EXCLUDED.completed_requests ) + GREATEST( "
        "llm_remote_batch_jobs.failed_requests, EXCLUDED.failed_requests ) "
        "<= GREATEST( llm_remote_batch_jobs.total_requests, "
        "EXCLUDED.total_requests )"
    )
    assert expected_guard in sql
