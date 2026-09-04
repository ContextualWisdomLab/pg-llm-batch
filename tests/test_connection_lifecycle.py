# SPDX-License-Identifier: Apache-2.0
"""Regression tests for owned PostgreSQL connection lifecycle boundaries."""

from __future__ import annotations

from threading import RLock
from types import SimpleNamespace
from typing import Any

import pytest

from pg_llm_batch import config as config_module
from pg_llm_batch import orchestrator as orchestrator_module
from pg_llm_batch import token_counter as token_counter_module
from pg_llm_batch.config import PostgresConfigStore, SecretStore
from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.orchestrator import PostgresBatchOrchestrator
from pg_llm_batch.token_counter import BatchAccumulator, TokenCounter


class _QueryCursor:
    """Return an empty queued-request snapshot for orchestration tests."""

    def __enter__(self) -> "_QueryCursor":
        """Return this cursor from the context manager."""
        return self

    def __exit__(self, *_exc: Any) -> None:
        """Leave the cursor context without suppressing errors."""

    def execute(self, _sql: str, _params: tuple[str]) -> None:
        """Accept the orchestrator's bounded queued-request query."""

    def fetchall(self) -> list[tuple[Any, ...]]:
        """Return no queued requests."""
        return []


class _QueryConnection:
    """Expose one context-managed cursor without opening a real database."""

    def __enter__(self) -> "_QueryConnection":
        """Return this connection from the context manager."""
        return self

    def __exit__(self, *_exc: Any) -> None:
        """Leave the connection context without suppressing errors."""

    def cursor(self) -> _QueryCursor:
        """Return a new query cursor."""
        return _QueryCursor()


class _InitializationConnection:
    """Expose whether a partially initialized store releases its connection."""

    def __init__(self) -> None:
        """Start open with autocommit disabled like a new database connection."""
        self.autocommit = False
        self.closed = False

    def close(self) -> None:
        """Record deterministic release after constructor failure."""
        self.closed = True


class _InitializationConnectionPort:
    """Expose initialization cleanup through the driver-neutral connection API."""

    def __init__(self, connection: _InitializationConnection) -> None:
        self._connection = connection

    def set_autocommit(self, enabled: bool) -> None:
        self._connection.autocommit = enabled

    def close(self) -> None:
        self._connection.close()


class _InitializationDriver:
    """Return one observable initialization connection through the runtime port."""

    def __init__(self, connection: _InitializationConnection) -> None:
        self._connection = connection

    def connect(self, _dsn: str, **_kwargs: Any) -> _InitializationConnectionPort:
        return _InitializationConnectionPort(self._connection)


class _OwnedConfig:
    """Record whether the orchestrator closes its owned config store."""

    instances: list["_OwnedConfig"] = []

    def __init__(
        self,
        dsn: str,
        *,
        postgres_driver: object | None = None,
    ) -> None:
        """Record the explicit DSN, shared driver, and owned store lifecycle."""
        self.dsn = dsn
        self.postgres_driver = postgres_driver
        self.closed = False
        self.instances.append(self)

    def close(self) -> None:
        """Record deterministic release of the config connection."""
        self.closed = True


class _OwnedCounter:
    """Record whether the orchestrator closes its owned token counter."""

    instances: list["_OwnedCounter"] = []

    def __init__(
        self,
        dsn: str,
        *,
        config: _OwnedConfig,
        postgres_driver: object | None = None,
    ) -> None:
        """Record constructor ownership and expose the runtime token limit."""
        self.dsn = dsn
        self.config = config
        self.postgres_driver = postgres_driver
        self.effective_limit = 100
        self.closed = False
        self.instances.append(self)

    def close(self) -> None:
        """Record deterministic release of the cached token connection."""
        self.closed = True


def _prepare_owned_orchestrator(monkeypatch: Any) -> PostgresBatchOrchestrator:
    """Build an orchestrator whose database-owned collaborators are observable."""
    _OwnedConfig.instances = []
    _OwnedCounter.instances = []
    driver = SimpleNamespace(connect=lambda _dsn: _QueryConnection())
    monkeypatch.setattr(orchestrator_module, "retained_postgres_driver", lambda: driver)
    monkeypatch.setattr(orchestrator_module, "PostgresConfigStore", _OwnedConfig)
    monkeypatch.setattr(orchestrator_module, "TokenCounter", _OwnedCounter)
    orchestrator = PostgresBatchOrchestrator("postgresql://example")
    monkeypatch.setattr(orchestrator, "_resolve_batch_uuid", lambda _key: "resolved")
    return orchestrator


def test_prepare_batches_closes_owned_connections_after_success(
    monkeypatch: Any,
) -> None:
    """A completed preparation must release both package-owned connections."""
    orchestrator = _prepare_owned_orchestrator(monkeypatch)
    monkeypatch.setattr(orchestrator, "_assemble_payloads", lambda _counter, _rows: [])
    monkeypatch.setattr(
        orchestrator,
        "_persist_payloads",
        lambda _payloads, _batch_uuid, _counter: {"ready": [], "overflow": []},
    )

    assert orchestrator.prepare_batches(batch_uuid="source-key") == {
        "ready": [],
        "overflow": [],
    }
    assert _OwnedCounter.instances[0].closed is True
    assert _OwnedConfig.instances[0].closed is True


def test_prepare_batches_closes_owned_connections_after_failure(
    monkeypatch: Any,
) -> None:
    """A preparation error must release both package-owned connections."""
    orchestrator = _prepare_owned_orchestrator(monkeypatch)

    def fail_assembly(_counter: _OwnedCounter, _rows: list[tuple[Any, ...]]) -> list[Any]:
        raise RuntimeError("assembly failed")

    monkeypatch.setattr(orchestrator, "_assemble_payloads", fail_assembly)

    with pytest.raises(RuntimeError, match="assembly failed"):
        orchestrator.prepare_batches(batch_uuid="source-key")

    assert _OwnedCounter.instances[0].closed is True
    assert _OwnedConfig.instances[0].closed is True


def test_prepare_batches_closes_config_when_counter_construction_fails(
    monkeypatch: Any,
) -> None:
    """Config ownership must be released even when token setup cannot finish."""
    orchestrator = _prepare_owned_orchestrator(monkeypatch)

    def fail_counter(
        _dsn: str,
        *,
        config: _OwnedConfig,
        postgres_driver: object | None = None,
    ) -> _OwnedCounter:
        assert config is _OwnedConfig.instances[0]
        assert postgres_driver is orchestrator._postgres_driver
        raise RuntimeError("counter construction failed")

    monkeypatch.setattr(orchestrator_module, "TokenCounter", fail_counter)

    with pytest.raises(RuntimeError, match="counter construction failed"):
        orchestrator.prepare_batches(batch_uuid="source-key")

    assert _OwnedConfig.instances[0].closed is True
    assert _OwnedCounter.instances == []


def test_config_store_constructor_closes_connection_after_setup_failure(
    monkeypatch: Any,
) -> None:
    """A failed config-store setup must release the connection it already acquired."""
    connection = _InitializationConnection()
    driver = _InitializationDriver(connection)
    monkeypatch.setattr(config_module, "retained_postgres_driver", lambda: driver)

    def fail_table_setup(_store: PostgresConfigStore) -> None:
        raise RuntimeError("config setup failed")

    monkeypatch.setattr(PostgresConfigStore, "_ensure_table", fail_table_setup)

    with pytest.raises(RuntimeError, match="config setup failed"):
        PostgresConfigStore("postgresql://example")

    assert connection.closed is True


def test_secret_store_constructor_closes_connection_after_setup_failure(
    monkeypatch: Any,
) -> None:
    """A failed secret-store setup must release the connection it already acquired."""
    connection = _InitializationConnection()
    driver = _InitializationDriver(connection)
    monkeypatch.setattr(config_module, "retained_postgres_driver", lambda: driver)

    def fail_table_setup(_store: SecretStore) -> None:
        raise RuntimeError("secret setup failed")

    monkeypatch.setattr(SecretStore, "_ensure_table", fail_table_setup)

    with pytest.raises(RuntimeError, match="secret setup failed"):
        SecretStore("postgresql://example")

    assert connection.closed is True


def test_token_counter_close_releases_cached_connection() -> None:
    """Closing a counter must release and clear its cached PostgreSQL connection."""
    closed: list[str] = []
    counter = object.__new__(TokenCounter)
    counter._pg_connection_lock = RLock()
    counter._pg_conn = SimpleNamespace(close=lambda: closed.append("closed"))

    counter.close()
    counter.close()

    assert closed == ["closed"]
    assert counter._pg_conn is None


def test_token_counter_close_clears_connection_after_driver_failure() -> None:
    """Driver cleanup failure must not retain the unusable cached connection."""
    counter = object.__new__(TokenCounter)
    counter._pg_connection_lock = RLock()

    def fail_close() -> None:
        raise RuntimeError("driver close failed")

    counter._pg_conn = SimpleNamespace(close=fail_close)

    counter.close()

    assert counter._pg_conn is None


def test_invalid_configuration_is_rejected_before_token_connection(
    monkeypatch: Any,
) -> None:
    """Constructor validation must complete before acquiring a token connection."""
    extension_checks: list[str] = []

    class _InvalidConfig:
        def get(self, category: str, key: str, default: Any) -> Any:
            if (category, key) == ("token_limits", "buffer_percentage"):
                return 99
            return default

    monkeypatch.setattr(
        token_counter_module.TokenCounter,
        "_ensure_pg_tiktoken",
        lambda _self: extension_checks.append("checked") or True,
    )

    with pytest.raises(ValidationError, match="between 0 and 50"):
        TokenCounter("postgresql://example", config=_InvalidConfig())

    assert extension_checks == []


def test_invalid_configured_batch_limit_is_rejected_before_token_connection(
    monkeypatch: Any,
) -> None:
    """A non-positive configured batch ceiling must fail before DB acquisition."""
    extension_checks: list[str] = []

    class _InvalidConfig:
        def get(self, category: str, key: str, default: Any) -> Any:
            if (category, key) == ("token_limits", "per_batch"):
                return 0
            return default

    monkeypatch.setattr(
        token_counter_module.TokenCounter,
        "_ensure_pg_tiktoken",
        lambda _self: extension_checks.append("checked") or True,
    )

    with pytest.raises(ValidationError, match="must be a positive integer"):
        TokenCounter("postgresql://example", config=_InvalidConfig())

    assert extension_checks == []


def test_invalid_explicit_accumulator_limit_is_rejected() -> None:
    """A caller-provided non-positive accumulator ceiling must fail closed."""
    counter = SimpleNamespace(
        effective_limit=100,
        azure_max_records_per_file=10,
        azure_max_bytes_per_file=1024,
    )

    with pytest.raises(ValidationError, match="must be a positive integer"):
        BatchAccumulator(counter, "gpt-4o", max_records=0)
