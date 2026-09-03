# SPDX-License-Identifier: Apache-2.0
"""Driver-port regressions for durable remote batch lifecycle persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

from pg_llm_batch import db


class _Cursor:
    """Expose the cursor behavior required by the lifecycle migration seam."""

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

    def row_count(self) -> int:
        return self.driver.affected_rows


class _Connection:
    """Retain one fake transaction and expose commit evidence."""

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
    """Minimal driver-shaped test double that contains no Psycopg type."""

    def __init__(
        self,
        *,
        rows: list[tuple[object, ...]] | None = None,
        affected_rows: int = 1,
    ) -> None:
        self.rows = list(rows or [])
        self.affected_rows = affected_rows
        self.executions: list[tuple[str, object | None]] = []
        self.connections: list[str] = []
        self.commits = 0

    def connect(self, dsn: str) -> _Connection:
        self.connections.append(dsn)
        return _Connection(self)


def _persisted_remote_batch_row(
    observed: datetime,
) -> tuple[object, ...]:
    """Return one exact persisted lifecycle row used by stale-write regressions."""
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


def test_observation_order_reservation_uses_injected_driver_without_psycopg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Driver migration must retain the default standalone tenant boundary."""
    driver = _Driver(rows=[(41,)])
    monkeypatch.setattr(db, "psycopg", None)

    order = db.reserve_remote_batch_observation_order(
        "postgresql://x",
        postgres_driver=driver,
    )

    assert order == 41
    assert driver.connections == ["postgresql://x"]
    assert driver.executions == [
        (
            "SELECT set_config('pg_llm_batch.tenant_scope', %s, true)",
            ("standalone",),
        ),
        ("SELECT nextval('llm_remote_batch_observation_sequence')", None),
    ]


def test_stale_lifecycle_write_reads_persisted_state_through_injected_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Port row-count semantics must preserve the stale-write recovery contract."""
    observed = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
    driver = _Driver(
        rows=[_persisted_remote_batch_row(observed)],
        affected_rows=0,
    )
    monkeypatch.setattr(db, "psycopg", None)

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
    assert any(
        "SELECT tenant_scope" in query
        for query, _params in driver.executions
    )
    assert driver.commits == 1


def test_remote_lifecycle_read_uses_injected_driver_without_psycopg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant-scoped reads must not reacquire the legacy driver implicitly."""
    observed = datetime(2026, 9, 2, 12, 0, tzinfo=timezone.utc)
    driver = _Driver(rows=[_persisted_remote_batch_row(observed)])
    monkeypatch.setattr(db, "psycopg", None)

    snapshot = db.get_remote_batch_state(
        "postgresql://x",
        "primary",
        "batch-1",
        postgres_driver=driver,
    )

    assert snapshot is not None
    assert snapshot["tenant_scope"] == "standalone"
    assert snapshot["observation_order"] == 1
    assert driver.executions[0] == (
        "SELECT set_config('pg_llm_batch.tenant_scope', %s, true)",
        ("standalone",),
    )
