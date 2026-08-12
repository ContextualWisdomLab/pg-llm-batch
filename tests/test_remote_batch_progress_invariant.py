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


def test_persistence_rejects_impossible_same_observation_before_database(
    monkeypatch: Any,
) -> None:
    """Completed plus failed requests cannot exceed one explicitly known total."""
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


@pytest.mark.parametrize(
    ("request_counts", "expected_total_known"),
    [
        ({"completed": 2, "failed": 1}, False),
        ({"total": "invalid", "completed": 2, "failed": 1}, False),
        ({"total": 0, "completed": 0, "failed": 0}, True),
    ],
)
def test_persistence_distinguishes_unknown_total_from_explicit_zero(
    monkeypatch: Any,
    request_counts: dict[str, object],
    expected_total_known: bool,
) -> None:
    """Persist knownness internally without widening the public snapshot shape."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)

    snapshot = db.persist_remote_batch_state(
        "postgresql://example",
        "primary",
        {
            "id": "batch-knownness",
            "status": "in_progress",
            "request_counts": request_counts,
        },
        observation_order=1,
    )

    assert snapshot["total_requests"] == 0
    assert "total_requests_known" not in snapshot
    assert snapshot["completed_requests"] == request_counts.get("completed", 0)
    assert snapshot["failed_requests"] == request_counts.get("failed", 0)

    persistence_params = driver.executions[-1][1]
    assert persistence_params is not None
    assert persistence_params[13] is expected_total_known
