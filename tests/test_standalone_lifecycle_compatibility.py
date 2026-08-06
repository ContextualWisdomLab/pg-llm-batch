# SPDX-License-Identifier: Apache-2.0
"""Backward-compatibility tests for standalone durable lifecycle helpers."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch import db


class _Cursor:
    """Record parameterized lifecycle statements for the compatibility test."""

    def __init__(self, driver: "_Psycopg") -> None:
        self.driver = driver

    def __enter__(self) -> "_Cursor":
        """Return this cursor context."""
        return self

    def __exit__(self, *_exc: Any) -> None:
        """Leave the cursor context without suppressing failures."""
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        """Record one statement and its bound values."""
        self.driver.executions.append((sql, params))


class _Connection:
    """Expose one recording cursor and a no-op transaction commit."""

    def __init__(self, driver: "_Psycopg") -> None:
        self.driver = driver

    def __enter__(self) -> "_Connection":
        """Return this connection context."""
        return self

    def __exit__(self, *_exc: Any) -> None:
        """Leave the connection context without suppressing failures."""
        return None

    def cursor(self) -> _Cursor:
        """Return a recording cursor."""
        return _Cursor(self.driver)

    def commit(self) -> None:
        """Complete the fake transaction without additional behavior."""
        return None


class _Psycopg:
    """Minimal psycopg replacement for standalone return-shape verification."""

    def __init__(self) -> None:
        self.executions: list[tuple[str, Any]] = []

    def connect(self, _dsn: str) -> _Connection:
        """Return a deterministic fake connection."""
        return _Connection(self)


def test_standalone_persistence_keeps_the_pre_tenant_return_shape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Adding tenant isolation must not add a new key to the legacy helper result."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)

    snapshot = db.persist_remote_batch_state(
        "postgresql://compatibility",
        "primary",
        {
            "id": "batch-compatibility",
            "status": "in_progress",
            "request_counts": {"total": 1, "completed": 0, "failed": 0},
        },
        1,
    )

    assert "tenant_scope" not in snapshot
    assert snapshot["endpoint_alias"] == "primary"
    assert snapshot["remote_batch_id"] == "batch-compatibility"
    assert driver.executions[0] == (
        "SELECT set_config('pg_llm_batch.tenant_scope', %s, true)",
        ("standalone",),
    )


def test_explicit_tenant_persistence_exposes_the_tenant_identity(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The new tenant-aware helper returns its explicit trusted scope."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)

    snapshot = db.persist_tenant_remote_batch_state(
        "postgresql://compatibility",
        "tenant-a",
        "primary",
        {
            "id": "batch-compatibility",
            "status": "in_progress",
            "request_counts": {"total": 1, "completed": 0, "failed": 0},
        },
        2,
    )

    assert snapshot["tenant_scope"] == "tenant-a"
