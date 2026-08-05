# SPDX-License-Identifier: Apache-2.0
"""Tests for tenant-bound lifecycle persistence and reads."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from pg_llm_batch import db
from pg_llm_batch.exceptions import ValidationError


class _Cursor:
    """Record parameterized SQL and return deterministic rows."""

    def __init__(self, driver: "_Psycopg") -> None:
        self.driver = driver

    def __enter__(self) -> "_Cursor":
        """Return the cursor context."""
        return self

    def __exit__(self, *_exc: Any) -> None:
        """Leave the cursor context without suppressing errors."""
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        """Record one SQL execution and its bound parameters."""
        self.driver.executions.append((sql, params))

    def fetchone(self) -> Any:
        """Return the next configured row, or no row when exhausted."""
        if not self.driver.fetchone_rows:
            return None
        return self.driver.fetchone_rows.pop(0)


class _Connection:
    """Expose a cursor and commit counter for the fake driver."""

    def __init__(self, driver: "_Psycopg") -> None:
        self.driver = driver

    def __enter__(self) -> "_Connection":
        """Return the connection context."""
        return self

    def __exit__(self, *_exc: Any) -> None:
        """Leave the connection context without suppressing errors."""
        return None

    def cursor(self) -> _Cursor:
        """Return one cursor bound to the fake driver."""
        return _Cursor(self.driver)

    def commit(self) -> None:
        """Record a committed database transaction."""
        self.driver.commits += 1


class _Psycopg:
    """Minimal psycopg replacement for deterministic database contracts."""

    def __init__(self, fetchone_rows: list[Any] | None = None) -> None:
        self.executions: list[tuple[str, Any]] = []
        self.connections: list[str] = []
        self.commits = 0
        self.fetchone_rows = list(fetchone_rows or [])

    def connect(self, dsn: str) -> _Connection:
        """Record the DSN and return a fake connection."""
        self.connections.append(dsn)
        return _Connection(self)


def _provider_batch(status: str = "in_progress") -> dict[str, Any]:
    """Return one deterministic provider lifecycle object."""
    return {
        "id": "batch-shared",
        "input_file_id": "file-input",
        "endpoint": "/v1/responses",
        "status": status,
        "request_counts": {"total": 3, "completed": 1, "failed": 0},
        "metadata": {"job_name": "nightly"},
    }


def test_standalone_persistence_sets_transaction_scope_before_upsert(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Legacy persistence uses explicit standalone scope under the RLS policy."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)
    observed = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)

    snapshot = db.persist_remote_batch_state(
        "postgresql://tenant-test",
        "primary",
        _provider_batch(),
        11,
        observed_at=observed,
    )

    assert snapshot["tenant_scope"] == "standalone"
    assert driver.executions[0] == (
        "SELECT set_config('pg_llm_batch.tenant_scope', %s, true)",
        ("standalone",),
    )
    upsert_sql, upsert_params = driver.executions[1]
    assert "INSERT INTO llm_remote_batch_jobs (" in upsert_sql
    assert "tenant_scope," in upsert_sql
    assert (
        "ON CONFLICT (tenant_scope, endpoint_alias, remote_batch_id) DO UPDATE"
        in upsert_sql
    )
    assert upsert_params[:4] == ("standalone", "primary", "batch-shared", 11)
    assert driver.commits == 1


def test_explicit_tenants_do_not_share_the_business_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Identical provider identifiers are independently bound to trusted tenants."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)

    first = db.persist_tenant_remote_batch_state(
        "postgresql://tenant-test",
        "tenant-a",
        "primary",
        _provider_batch("in_progress"),
        21,
    )
    second = db.persist_tenant_remote_batch_state(
        "postgresql://tenant-test",
        "tenant-b",
        "primary",
        _provider_batch("completed"),
        22,
    )

    assert first["tenant_scope"] == "tenant-a"
    assert second["tenant_scope"] == "tenant-b"
    assert driver.executions[0][1] == ("tenant-a",)
    assert driver.executions[1][1][:4] == (
        "tenant-a",
        "primary",
        "batch-shared",
        21,
    )
    assert driver.executions[2][1] == ("tenant-b",)
    assert driver.executions[3][1][:4] == (
        "tenant-b",
        "primary",
        "batch-shared",
        22,
    )
    assert driver.commits == 2


def test_invalid_tenant_scope_fails_before_database_access(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A malformed tenant scope cannot reach a database connection or SQL sink."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)

    with pytest.raises(ValidationError) as exc_info:
        db.persist_tenant_remote_batch_state(
            "postgresql://tenant-test",
            " tenant-a",
            "primary",
            _provider_batch(),
            31,
        )

    assert exc_info.value.details["field"] == "tenant_scope"
    assert driver.connections == []
    assert driver.executions == []


def test_tenant_scoped_read_sets_context_and_binds_complete_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Lifecycle reads establish tenant context before selecting one exact row."""
    first_seen = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)
    last_seen = datetime(2026, 8, 5, 9, 5, tzinfo=timezone.utc)
    driver = _Psycopg(
        fetchone_rows=[
            (
                "tenant-a",
                "primary",
                "batch-shared",
                42,
                "file-input",
                "/v1/responses",
                "completed",
                "file-output",
                None,
                3,
                3,
                0,
                {"job_name": "nightly"},
                first_seen,
                last_seen,
                last_seen,
                last_seen,
            )
        ]
    )
    monkeypatch.setattr(db, "psycopg", driver)

    state = db.get_tenant_remote_batch_state(
        "postgresql://tenant-test",
        "tenant-a",
        "primary",
        "batch-shared",
    )

    assert driver.executions[0][1] == ("tenant-a",)
    select_sql, select_params = driver.executions[1]
    assert "FROM llm_remote_batch_jobs" in select_sql
    assert "tenant_scope = %s" in select_sql
    assert "endpoint_alias = %s" in select_sql
    assert "remote_batch_id = %s" in select_sql
    assert select_params == ("tenant-a", "primary", "batch-shared")
    assert state == {
        "tenant_scope": "tenant-a",
        "endpoint_alias": "primary",
        "remote_batch_id": "batch-shared",
        "observation_order": 42,
        "input_file_id": "file-input",
        "batch_endpoint": "/v1/responses",
        "batch_status": "completed",
        "output_file_id": "file-output",
        "error_file_id": None,
        "total_requests": 3,
        "completed_requests": 3,
        "failed_requests": 0,
        "provider_metadata": {"job_name": "nightly"},
        "first_seen_at": first_seen,
        "last_observed_at": last_seen,
        "terminal_at": last_seen,
        "updated_at": last_seen,
    }
    assert driver.commits == 0


def test_tenant_scoped_read_returns_none_only_for_a_missing_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid scoped query may report absence without weakening validation."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)

    assert (
        db.get_tenant_remote_batch_state(
            "postgresql://tenant-test",
            "tenant-a",
            "primary",
            "batch-missing",
        )
        is None
    )
    assert len(driver.executions) == 2


def test_standalone_read_delegates_to_explicit_default_scope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Single-tenant callers use the same RLS-safe read path as tenant clients."""
    captured: list[tuple[Any, ...]] = []

    def fake_get(*args: Any) -> None:
        captured.append(args)
        return None

    monkeypatch.setattr(db, "get_tenant_remote_batch_state", fake_get)

    assert (
        db.get_remote_batch_state(
            "postgresql://tenant-test",
            "primary",
            "batch-shared",
        )
        is None
    )
    assert captured == [
        (
            "postgresql://tenant-test",
            "standalone",
            "primary",
            "batch-shared",
        )
    ]
