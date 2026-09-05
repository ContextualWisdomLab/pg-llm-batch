from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, get_type_hints

import pytest

from pg_llm_batch import db
from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.postgres_driver_port import PostgresCursorPort
from pg_llm_batch.psycopg_driver_adapter import PsycopgCursorAdapter


class _RawCursor:
    def __init__(self, rowcount: object) -> None:
        self.rowcount = rowcount


class _Cursor:
    def __init__(self, driver: _Driver) -> None:
        self.driver = driver

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def execute(self, query: str, params: object | None = None) -> _Cursor:
        self.driver.executions.append((query, params))
        return self

    def fetchone(self) -> tuple[object, ...] | None:
        if not self.driver.rows:
            return None
        return self.driver.rows.pop(0)

    def row_count(self) -> int | None:
        return self.driver.affected_rows


class _Connection:
    def __init__(self, driver: _Driver) -> None:
        self.driver = driver

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def cursor(self) -> _Cursor:
        return _Cursor(self.driver)

    def commit(self) -> None:
        self.driver.commits += 1


class _Driver:
    def __init__(
        self,
        *,
        rows: list[tuple[object, ...]] | None = None,
        affected_rows: int | None = 1,
    ) -> None:
        self.rows = list(rows or [])
        self.affected_rows = affected_rows
        self.executions: list[tuple[str, object | None]] = []
        self.connections: list[str] = []
        self.commits = 0

    def connect(self, dsn: str) -> _Connection:
        self.connections.append(dsn)
        return _Connection(self)


def _persisted_remote_batch_row(observed: datetime) -> tuple[object, ...]:
    return (
        "standalone",
        "primary",
        "batch-1",
        1,
        None,
        "/v1/responses",
        "in_progress",
        None,
        None,
        2,
        1,
        0,
        {},
        observed,
        observed,
        None,
        observed,
    )


def test_cursor_port_exposes_unknown_row_count_without_driver_sentinel() -> None:
    """The provider-neutral cursor contract must represent unknown counts explicitly."""
    assert get_type_hints(PostgresCursorPort.row_count)["return"] == int | None


def test_psycopg_cursor_normalizes_unknown_row_count() -> None:
    """Psycopg's -1 sentinel must not leak through the provider-neutral port."""
    assert PsycopgCursorAdapter(_RawCursor(-1)).row_count() is None


def test_observation_order_binds_validated_tenant_scope_before_sequence_io() -> None:
    """A tenant reservation must establish transaction-local RLS identity first."""
    driver = _Driver(rows=[(41,)])

    order = db.reserve_remote_batch_observation_order(
        "postgresql://x",
        tenant_scope="tenant-a",
        postgres_driver=driver,
    )

    assert order == 41
    assert driver.executions == [
        (
            "SELECT set_config('pg_llm_batch.tenant_scope', %s, true)",
            ("tenant-a",),
        ),
        ("SELECT nextval('llm_remote_batch_observation_sequence')", None),
    ]


def test_observation_order_rejects_invalid_tenant_before_database_io() -> None:
    """Untrusted tenant text must fail before a connection or sequence reservation."""
    driver = _Driver(rows=[(41,)])

    with pytest.raises(ValidationError, match="tenant_scope"):
        db.reserve_remote_batch_observation_order(
            "postgresql://x",
            tenant_scope="tenant scope",
            postgres_driver=driver,
        )

    assert driver.connections == []
    assert driver.executions == []


def test_unknown_remote_lifecycle_row_count_reads_persisted_state() -> None:
    """Unknown affected-row evidence must not be guessed as a successful UPSERT."""
    observed = datetime(2026, 9, 3, 1, 0, tzinfo=timezone.utc)
    driver = _Driver(
        rows=[_persisted_remote_batch_row(observed)],
        affected_rows=None,
    )

    snapshot = db.persist_remote_batch_state(
        "postgresql://x",
        "primary",
        {
            "id": "batch-1",
            "endpoint": "/v1/responses",
            "status": "in_progress",
            "request_counts": {"total": 2, "completed": 2, "failed": 0},
        },
        observation_order=2,
        observed_at=observed,
        postgres_driver=driver,
    )

    assert snapshot["observation_order"] == 1
    assert snapshot["completed_requests"] == 1
