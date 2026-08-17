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
        self.rowcount = 1

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        """Record one SQL statement and expose configured upsert application."""
        self.driver.executions.append((sql, params))
        if "INSERT INTO llm_remote_batch_jobs" in sql:
            self.rowcount = self.driver.upsert_rowcount

    def fetchone(self) -> Any:
        """Return the configured persisted lifecycle row for a reread."""
        return self.driver.stored_row


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

    def __init__(self, *, upsert_rowcount: int = 1, stored_row: Any = None) -> None:
        self.executions: list[tuple[str, Any]] = []
        self.connections: list[str] = []
        self.commits = 0
        self.upsert_rowcount = upsert_rowcount
        self.stored_row = stored_row

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


def test_skipped_progress_upsert_returns_the_persisted_snapshot(monkeypatch: Any) -> None:
    """A rejected monotonic merge must not be reported as successfully persisted."""
    stored_row = (
        "standalone",
        "primary",
        "batch-stored",
        1,
        None,
        "/v1/chat/completions",
        "in_progress",
        None,
        None,
        10,
        9,
        0,
        {},
        None,
        None,
        None,
        None,
    )
    driver = _Psycopg(upsert_rowcount=0, stored_row=stored_row)
    monkeypatch.setattr(db, "psycopg", driver)

    result = db.persist_remote_batch_state(
        "postgresql://example",
        "primary",
        {
            "id": "batch-stored",
            "status": "in_progress",
            "request_counts": {"total": 10, "completed": 0, "failed": 2},
        },
        observation_order=2,
    )

    assert result["observation_order"] == 1
    assert result["total_requests"] == 10
    assert result["completed_requests"] == 9
    assert result["failed_requests"] == 0
    assert any(
        "SELECT tenant_scope" in sql and "FROM llm_remote_batch_jobs" in sql
        for sql, _params in driver.executions
    )


def test_skipped_progress_upsert_without_stored_row_fails_closed(
    monkeypatch: Any,
) -> None:
    """A rejected update without a rereadable durable row is an integrity error."""
    driver = _Psycopg(upsert_rowcount=0, stored_row=None)
    monkeypatch.setattr(db, "psycopg", driver)

    with pytest.raises(
        RuntimeError,
        match="remote batch progress update was rejected without persisted state",
    ):
        db.persist_remote_batch_state(
            "postgresql://example",
            "primary",
            {
                "id": "batch-missing",
                "status": "in_progress",
                "request_counts": {"total": 1, "completed": 1, "failed": 0},
            },
            observation_order=2,
        )

    assert driver.commits == 0


def test_schema_migration_fails_closed_on_known_historical_corruption() -> None:
    """Schema reapplication must report inconsistent known progress before validation."""
    packaged_schema = db.SCHEMA_PATH.read_text(encoding="utf-8")
    docker_schema = (
        db.SCHEMA_PATH.parents[1] / "docker/postgres/init/02_schema.sql"
    ).read_text(encoding="utf-8")

    assert packaged_schema == docker_schema
    assert "inconsistent known remote batch progress requires operator remediation" in packaged_schema
    assert "RAISE EXCEPTION USING" in packaged_schema
    assert "total_requests_known IS TRUE OR total_requests > 0" in packaged_schema
    assert "AND NOT convalidated" in packaged_schema
