# SPDX-License-Identifier: Apache-2.0
"""Regression tests for checkpoint persistence through the PostgreSQL driver port."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

import pg_llm_batch.checkpoint_store as checkpoint_store
from pg_llm_batch.checkpoint_store import (
    PostgresBatchResultCheckpointStore,
    apply_result_checkpoint_schema,
)


class _PortCursor:
    """Provide the minimal cursor behavior needed by the checkpoint boundary."""

    def __init__(self, calls: list[tuple[str, object | None]]) -> None:
        self.calls = calls
        self.result: object | None = None

    def execute(self, query: str, params: object | None = None) -> "_PortCursor":
        """Record parameterized SQL without interpolating caller values."""
        self.calls.append((query, params))
        self.result = (params[0],) if query.startswith("SELECT set_config") and params else None
        return self

    def fetchone(self) -> object | None:
        """Return the bounded result from the previous fake operation."""
        return self.result

    def __enter__(self) -> "_PortCursor":
        """Retain cursor identity across the context-manager boundary."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """Release no external resources in the deterministic fake."""
        return None


class _PortConnection:
    """Expose one retained fake connection for driver-port regression tests."""

    def __init__(self, calls: list[tuple[str, object | None]]) -> None:
        self.calls = calls
        self.commit_count = 0

    def cursor(self) -> _PortCursor:
        """Create a cursor bound to this exact fake connection."""
        return _PortCursor(self.calls)

    def commit(self) -> None:
        """Record explicit package-owned transaction commit authority."""
        self.commit_count += 1

    def __enter__(self) -> "_PortConnection":
        """Retain connection identity across the context-manager boundary."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """Release no external resources in the deterministic fake."""
        return None


class _DriverPortFake:
    """Connect checkpoint operations without exposing a concrete database client."""

    def __init__(self) -> None:
        self.dsns: list[str] = []
        self.calls: list[tuple[str, object | None]] = []
        self.connections: list[_PortConnection] = []

    def connect(self, dsn: str, **_kwargs: Any) -> _PortConnection:
        """Return one connection and preserve the exact validated DSN."""
        self.dsns.append(dsn)
        connection = _PortConnection(self.calls)
        self.connections.append(connection)
        return connection


def _deny_legacy_psycopg_path(monkeypatch: pytest.MonkeyPatch) -> None:
    """Make accidental fallback to the retained Psycopg path fail immediately."""

    def fail_require_psycopg() -> None:
        raise AssertionError("legacy Psycopg availability check was reached")

    class _ForbiddenPsycopg:
        def connect(self, *_args: object, **_kwargs: object) -> None:
            raise AssertionError("legacy Psycopg connection path was reached")

    monkeypatch.setattr(checkpoint_store, "_require_psycopg", fail_require_psycopg)
    monkeypatch.setattr(checkpoint_store, "psycopg", _ForbiddenPsycopg())


def test_checkpoint_store_load_uses_injected_driver_port_without_psycopg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A migrated store must reach tenant SQL through the injected database port."""
    _deny_legacy_psycopg_path(monkeypatch)
    driver = _DriverPortFake()
    store = PostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
        postgres_driver=driver,  # type: ignore[arg-type]
    )

    assert store.load("worker-a", "batch-1", "default") is None
    assert driver.dsns == ["postgresql://unit"]
    assert driver.calls[0][1] == ("tenant-a",)
    assert driver.calls[1][1] == ("tenant-a", "worker-a", "default", "batch-1")


def test_checkpoint_schema_application_uses_injected_driver_port_without_psycopg(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Schema migration must be able to run through the same replacement seam."""
    _deny_legacy_psycopg_path(monkeypatch)
    migration = tmp_path / "checkpoint.sql"
    migration.write_text("CREATE TABLE checkpoint_probe (probe_id BIGINT);", encoding="utf-8")
    driver = _DriverPortFake()

    apply_result_checkpoint_schema(
        "postgresql://unit",
        str(migration),
        postgres_driver=driver,  # type: ignore[arg-type]
    )

    assert driver.dsns == ["postgresql://unit"]
    assert driver.calls == [("CREATE TABLE checkpoint_probe (probe_id BIGINT);", None)]
    assert driver.connections[0].commit_count == 1
