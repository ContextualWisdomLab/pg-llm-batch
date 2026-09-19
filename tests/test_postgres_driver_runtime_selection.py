"""Regressions for the canonical PostgreSQL driver selection boundary.

Bounded contexts acquire PostgreSQL capability through one lazy runtime selector
rather than importing a concrete client. The commercial migration keeps explicit
driver injection available while requiring the default selector to construct the
exact admitted production adapter.
"""

from __future__ import annotations

import sys
from types import ModuleType
from typing import Any

import pg_llm_batch.checkpoint_store as checkpoint_store
import pg_llm_batch.config as config
import pg_llm_batch.db as db
import pg_llm_batch.health as health
import pg_llm_batch.orchestrator as orchestrator
import pg_llm_batch.postgres_driver_runtime as postgres_driver_runtime
import pg_llm_batch.token_counter as token_counter
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


def test_token_counter_default_driver_uses_runtime_selector(monkeypatch) -> None:
    """Token counting must acquire its retained database capability centrally."""
    driver = _Driver()
    monkeypatch.setattr(token_counter, "retained_postgres_driver", lambda: driver)
    monkeypatch.setattr(
        token_counter.TokenCounter,
        "_ensure_pg_tiktoken",
        lambda self: False,
    )

    counter = token_counter.TokenCounter("postgresql://unit")

    assert counter._postgres_driver is driver


def test_orchestrator_default_driver_uses_runtime_selector(monkeypatch) -> None:
    """Batch assembly must not retain a direct concrete-driver authority path."""
    driver = _Driver()
    monkeypatch.setattr(orchestrator, "retained_postgres_driver", lambda: driver)

    service = orchestrator.PostgresBatchOrchestrator("postgresql://unit")

    assert service._postgres_driver is driver


def test_runtime_selector_constructs_admitted_pg8000_loader(monkeypatch) -> None:
    """The default selector must delegate to the admitted pg8000 loader only."""
    driver = _Driver()
    module = ModuleType("pg_llm_batch.pg8000_driver_adapter")
    module.load_pg8000_driver = lambda: driver  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, module.__name__, module)

    selected = postgres_driver_runtime.retained_postgres_driver()

    assert selected is driver


def test_runtime_selector_returns_postgres_driver_port() -> None:
    """The retained selector must expose only the provider-neutral driver port."""
    driver = retained_postgres_driver()

    assert callable(driver.connect)
    assert callable(driver.parse_conninfo)
    assert callable(driver.make_conninfo)
    assert callable(driver.jsonb)
