# SPDX-License-Identifier: Apache-2.0
"""Driver-port regressions for PostgreSQL token-counting migration."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock
import time
from typing import Any

import pytest

import pg_llm_batch.token_counter as token_counter_module
from pg_llm_batch.token_counter import TokenCounter


class _UndefinedFunctionError(RuntimeError):
    """Represent one driver-classified undefined PostgreSQL function."""


class _OtherDriverError(RuntimeError):
    """Represent a database failure that must not disable pg_tiktoken availability."""


class _Cursor:
    """Return deterministic pg_tiktoken probe and count rows."""

    def __init__(self, driver: _Driver) -> None:
        self.driver = driver

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def execute(self, query: str, params: object | None = None) -> _Cursor:
        self.driver.executions.append((query, params))
        if "tiktoken_count" in query and "to_regprocedure" not in query:
            self.driver.enter_count_execution()
            try:
                if self.driver.execution_delay_seconds:
                    time.sleep(self.driver.execution_delay_seconds)
                if self.driver.primary_error is not None:
                    error = self.driver.primary_error
                    self.driver.primary_error = None
                    raise error
                self.driver.rows.append((7,))
            finally:
                self.driver.leave_count_execution()
        elif "tiktoken_encode" in query and "to_regprocedure" not in query:
            self.driver.rows.append((9,))
        return self

    def fetchone(self) -> tuple[object, ...] | None:
        if not self.driver.rows:
            return None
        return self.driver.rows.pop(0)


class _Connection:
    """Expose the connection lifecycle required by TokenCounter."""

    def __init__(self, driver: _Driver) -> None:
        self.driver = driver
        self.closed = False
        self.autocommit_values: list[bool] = []

    def cursor(self) -> _Cursor:
        return _Cursor(self.driver)

    def set_autocommit(self, enabled: bool) -> None:
        self.autocommit_values.append(enabled)

    def is_closed(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True


class _Driver:
    """Minimal concrete-driver-free port fake for token counting."""

    def __init__(
        self,
        *,
        primary_error: BaseException | None = None,
        execution_delay_seconds: float = 0.0,
    ) -> None:
        self.primary_error = primary_error
        self.execution_delay_seconds = execution_delay_seconds
        self.executions: list[tuple[str, object | None]] = []
        self.rows: list[tuple[object, ...]] = [(True, True, True)]
        self.connections: list[_Connection] = []
        self.dsn_values: list[str] = []
        self._execution_lock = Lock()
        self.active_count_executions = 0
        self.max_active_count_executions = 0

    def connect(
        self,
        dsn: str,
        *,
        connect_timeout_seconds: int | None = None,
    ) -> _Connection:
        assert connect_timeout_seconds is None
        self.dsn_values.append(dsn)
        connection = _Connection(self)
        self.connections.append(connection)
        return connection

    def is_undefined_function(self, error: BaseException) -> bool:
        return isinstance(error, _UndefinedFunctionError)

    def enter_count_execution(self) -> None:
        """Record concurrent use of the shared token-counting connection."""
        with self._execution_lock:
            self.active_count_executions += 1
            self.max_active_count_executions = max(
                self.max_active_count_executions,
                self.active_count_executions,
            )

    def leave_count_execution(self) -> None:
        """Release one deterministic concurrent-execution observation."""
        with self._execution_lock:
            self.active_count_executions -= 1


def _deny_default_driver(monkeypatch: pytest.MonkeyPatch) -> None:
    """Fail if explicit token-counter injection silently reacquires the runtime default."""

    def fail_default_driver():
        raise AssertionError("default PostgreSQL runtime driver was reached")

    monkeypatch.setattr(
        token_counter_module,
        "retained_postgres_driver",
        fail_default_driver,
    )


def test_token_counter_uses_injected_driver_without_default_driver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A replacement candidate must exercise pg_tiktoken through its own port."""
    driver = _Driver()
    _deny_default_driver(monkeypatch)
    metadata_calls: list[tuple[str, str, object]] = []

    def _metadata(dsn: str, model: str, *, postgres_driver: object = None) -> dict[str, str]:
        metadata_calls.append((dsn, model, postgres_driver))
        return {"tokenizer_model": "o200k_base"}

    monkeypatch.setattr(token_counter_module, "get_model_metadata", _metadata)

    counter = TokenCounter("postgresql://x", postgres_driver=driver)

    assert counter.count_tokens("hello", "model-a") == 7
    assert driver.dsn_values == ["postgresql://x"]
    assert driver.connections[0].autocommit_values == [True]
    assert metadata_calls == [("postgresql://x", "model-a", driver)]


def test_token_counter_serializes_shared_driver_connection_use(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A DB-API level-1 candidate must never receive concurrent connection calls."""
    driver = _Driver(execution_delay_seconds=0.03)
    _deny_default_driver(monkeypatch)
    monkeypatch.setattr(
        token_counter_module,
        "get_model_metadata",
        lambda _dsn, _model, *, postgres_driver=None: {"tokenizer_model": "o200k_base"},
    )
    counter = TokenCounter("postgresql://x", postgres_driver=driver)
    counter.get_encoder("model-a")
    start = Barrier(4)

    def _count_one(index: int) -> int:
        start.wait()
        return counter.count_tokens(f"hello-{index}", "model-a")

    with ThreadPoolExecutor(max_workers=4) as executor:
        results = list(executor.map(_count_one, range(4)))

    assert results == [7, 7, 7, 7]
    assert driver.max_active_count_executions == 1


def test_token_counter_uses_driver_error_classification_for_encode_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Undefined-function fallback must depend only on the driver-port classifier."""
    driver = _Driver(primary_error=_UndefinedFunctionError("undefined function"))
    _deny_default_driver(monkeypatch)
    monkeypatch.setattr(
        token_counter_module,
        "get_model_metadata",
        lambda _dsn, _model, *, postgres_driver=None: {"tokenizer_model": "o200k_base"},
    )

    counter = TokenCounter("postgresql://x", postgres_driver=driver)

    assert counter.count_tokens("hello", "model-a") == 9
    assert any("tiktoken_encode" in query for query, _params in driver.executions)


def test_non_undefined_driver_error_discards_cached_connection_before_retry(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A transient DB failure must retry on a fresh connection without disabling pg_tiktoken."""
    driver = _Driver(primary_error=_OtherDriverError("temporary database failure"))
    _deny_default_driver(monkeypatch)
    monkeypatch.setattr(
        token_counter_module,
        "get_model_metadata",
        lambda _dsn, _model, *, postgres_driver=None: {"tokenizer_model": "o200k_base"},
    )

    counter = TokenCounter("postgresql://x", postgres_driver=driver)

    with pytest.raises(RuntimeError, match="Token counting requires pg_tiktoken"):
        counter.count_tokens("first", "model-a")

    assert len(driver.connections) == 1
    assert driver.connections[0].closed is True
    assert counter.count_tokens("second", "model-a") == 7
    assert len(driver.connections) == 2
    assert driver.connections[1].autocommit_values == [True]
    assert not any("tiktoken_encode" in query for query, _params in driver.executions)
