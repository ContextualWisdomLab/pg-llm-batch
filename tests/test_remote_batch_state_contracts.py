# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for durable remote batch state semantics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pg_llm_batch import db


class _Cursor:
    """Capture SQL submitted by the lifecycle helper."""

    def __init__(self, driver: "_Psycopg") -> None:
        self.driver = driver

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        """Record one SQL execution and its bound parameters."""
        self.driver.executions.append((sql, params))


class _Connection:
    """Expose the small connection surface used by the lifecycle helper."""

    def __init__(self, driver: "_Psycopg") -> None:
        self.driver = driver

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def cursor(self) -> _Cursor:
        """Return a cursor that records SQL instead of contacting PostgreSQL."""
        return _Cursor(self.driver)

    def commit(self) -> None:
        """Record the explicit lifecycle transaction commit."""
        self.driver.commits += 1


class _Psycopg:
    """Minimal psycopg replacement for deterministic SQL contract tests."""

    def __init__(self) -> None:
        self.executions: list[tuple[str, Any]] = []
        self.commits = 0

    def connect(self, _dsn: str) -> _Connection:
        """Return a fake connection for the supplied DSN."""
        return _Connection(self)


def _compact_sql(sql: str) -> str:
    """Normalize SQL whitespace so assertions focus on update semantics."""
    return " ".join(sql.split())


def test_sparse_observations_cannot_reduce_persisted_request_counts(
    monkeypatch: Any,
) -> None:
    """Newer sparse polls or cancellations must not erase known progress counts."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)

    db.persist_remote_batch_state(
        "postgresql://example",
        "primary",
        {"id": "batch-1", "status": "cancelling"},
        observation_order=2,
    )

    sql = _compact_sql(driver.executions[0][0])
    assert (
        "total_requests = GREATEST( llm_remote_batch_jobs.total_requests, "
        "EXCLUDED.total_requests )"
    ) in sql
    assert (
        "completed_requests = GREATEST( "
        "llm_remote_batch_jobs.completed_requests, EXCLUDED.completed_requests )"
    ) in sql
    assert (
        "failed_requests = GREATEST( llm_remote_batch_jobs.failed_requests, "
        "EXCLUDED.failed_requests )"
    ) in sql
    assert driver.commits == 1


def test_operator_docs_define_current_state_and_tenant_trust_boundaries() -> None:
    """Lifecycle documentation must not overstate audit or tenant isolation."""
    documentation = (
        Path(__file__).parents[1] / "docs" / "remote-batch-lifecycle.md"
    ).read_text(encoding="utf-8")

    assert "current-state projection" in documentation
    assert "not an authorization or tenant-isolation boundary" in documentation
    assert "append-only audit history" in documentation
