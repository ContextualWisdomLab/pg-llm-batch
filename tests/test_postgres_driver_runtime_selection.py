"""Regressions for the retained PostgreSQL driver selection boundary.

The commercial driver migration must leave concrete Psycopg authority in one
infrastructure adapter rather than importing the package from each bounded
context. These tests exercise the default connection path through a lazy runtime
selector while preserving explicit driver injection.
"""

from __future__ import annotations

from typing import Any

import pg_llm_batch.checkpoint_store as checkpoint_store
import pg_llm_batch.config as config
import pg_llm_batch.db as db
import pg_llm_batch.health as health
from pg_llm_batch.postgres_driver_runtime import retained_postgres_driver


class _Connection:
    """Represent one exact connection returned by the selected fake driver."""


class _Driver:
    """Capture default-driver connection attempts without a concrete client."""

    def __init__(self) -> None:
        self.dsns: list[str] = []
        self.connection_kwargs: list[dict[str, Any]] = []
        self.connection = _Connection()

    def connect(self, dsn: str, **kwargs: Any) -> _Connection:
        """Record the exact DSN and connection options before returning the fake."""
        self.dsns.append(dsn)
        self.connection_kwargs.append(dict(kwargs))
        return self.connection


def test_db_default_connection_uses_runtime_driver_selector(monkeypatch) -> None:
    """Low-level DB helpers must not own a second concrete-driver import path."""
    driver = _Driver()
    monkeypatch.setattr(db, "retained_postgres_driver", lambda: driver)

    connection = db._connect_database("postgresql://unit", None)

    assert connection is driver.connection
    assert driver.dsns == ["postgresql://unit"]
    assert driver.connection_kwargs == [{}]


def test_checkpoint_default_connection_uses_runtime_driver_selector(monkeypatch) -> None:
    """Checkpoint persistence must share the same retained-driver authority."""
    driver = _Driver()
    monkeypatch.setattr(checkpoint_store, "retained_postgres_driver", lambda: driver)

    connection = checkpoint_store._connect_postgres("postgresql://unit", None)

    assert connection is driver.connection
    assert driver.dsns == ["postgresql://unit"]
    assert driver.connection_kwargs == [{}]


def test_health_default_connection_uses_runtime_driver_selector(monkeypatch) -> None:
    """Readiness must share the retained driver and preserve its finite timeout."""
    driver = _Driver()
    monkeypatch.setattr(health, "retained_postgres_driver", lambda: driver)

    connection = health._connect_health_database("postgresql://unit", None)

    assert connection is driver.connection
    assert driver.dsns == ["postgresql://unit"]
    assert driver.connection_kwargs == [{"connect_timeout_seconds": 5}]


def test_config_default_connection_uses_runtime_driver_selector(monkeypatch) -> None:
    """Configuration persistence must not retain a second concrete-client authority."""
    driver = _Driver()
    monkeypatch.setattr(config, "retained_postgres_driver", lambda: driver)

    connection = config._connect_store_database(
        "postgresql://unit",
        None,
        missing_dependency_message="driver unavailable",
    )

    assert connection is driver.connection
    assert driver.dsns == ["postgresql://unit"]
    assert driver.connection_kwargs == [{}]


def test_runtime_selector_returns_postgres_driver_port() -> None:
    """The retained selector must expose only the provider-neutral driver port."""
    driver = retained_postgres_driver()

    assert callable(driver.connect)
    assert callable(driver.parse_conninfo)
    assert callable(driver.make_conninfo)
    assert callable(driver.jsonb)
