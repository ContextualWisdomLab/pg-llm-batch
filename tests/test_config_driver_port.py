# SPDX-License-Identifier: Apache-2.0
"""Regression tests for configuration persistence through the PostgreSQL port."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch import config
from pg_llm_batch.config import PostgresConfigStore, SecretStore
from tests.conftest import FakeCursor, FakeKVStore


class _ConfigConnection:
    """Expose KV persistence through the driver-neutral connection surface."""

    def __init__(self, store: FakeKVStore) -> None:
        self.store = store
        self.autocommit_values: list[bool] = []
        self.closed = False

    def cursor(self) -> FakeCursor:
        """Return a cursor backed by the shared deterministic KV store."""
        return FakeCursor(self.store)

    def set_autocommit(self, enabled: bool) -> None:
        """Record the store's explicit autocommit policy decision."""
        self.autocommit_values.append(enabled)

    def close(self) -> None:
        """Record deterministic release of this connection capability."""
        self.closed = True


class _ConfigDriver:
    """Return distinct connections backed by one deterministic database state."""

    def __init__(self) -> None:
        self.store = FakeKVStore()
        self.dsns: list[str] = []
        self.connections: list[_ConfigConnection] = []

    def connect(self, dsn: str, **_kwargs: Any) -> _ConfigConnection:
        """Capture one validated DSN and create a connection on shared state."""
        self.dsns.append(dsn)
        connection = _ConfigConnection(self.store)
        self.connections.append(connection)
        return connection


def test_config_store_uses_injected_driver_without_psycopg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Configuration CRUD must not require Psycopg when a replacement port is supplied."""
    monkeypatch.setattr(config, "psycopg", None)
    driver = _ConfigDriver()

    store = PostgresConfigStore(
        "postgresql://example",
        postgres_driver=driver,  # type: ignore[arg-type]
    )
    try:
        store.set("batch_size", "default", 321)
        assert store.get("batch_size", "default") == 321
        assert driver.dsns == ["postgresql://example"]
        assert driver.connections[0].autocommit_values == [True]
    finally:
        store.close()

    assert driver.connections[0].closed is True


def test_secret_store_uses_injected_driver_without_psycopg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Secret persistence must retain the same DB seam without a concrete driver import."""
    monkeypatch.setattr(config, "psycopg", None)
    driver = _ConfigDriver()

    store = SecretStore(
        "postgresql://example",
        postgres_driver=driver,  # type: ignore[arg-type]
    )
    try:
        store.set_secret("provider.key", "secret-value")
        assert store.get_secret("provider.key") == "secret-value"
        assert driver.dsns == ["postgresql://example"]
        assert driver.connections[0].autocommit_values == [True]
    finally:
        store.close()

    assert driver.connections[0].closed is True
