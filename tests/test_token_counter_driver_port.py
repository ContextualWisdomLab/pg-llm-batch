# SPDX-License-Identifier: Apache-2.0
"""Driver-port regressions for PostgreSQL token-counting migration."""

from __future__ import annotations

from typing import Any

import pytest

import pg_llm_batch.token_counter as token_counter_module
from pg_llm_batch.token_counter import TokenCounter


class _UndefinedFunctionError(RuntimeError):
    """Represent one driver-classified undefined PostgreSQL function."""


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
            if self.driver.fail_primary_count:
                self.driver.fail_primary_count = False
                raise _UndefinedFunctionError("undefined function")
            self.driver.rows.append((7,))
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
    """Minimal Psycopg-free driver implementing the token-counting port surface."""

    def __init__(self, *, fail_primary_count: bool = False) -> None:
        self.fail_primary_count = fail_primary_count
        self.executions: list[tuple[str, object | None]] = []
        self.rows: list[tuple[object, ...]] = [(True, True, True)]
        self.connections: list[_Connection] = []
        self.dsn_values: list[str] = []

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


def test_token_counter_uses_injected_driver_without_psycopg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A replacement candidate must exercise pg_tiktoken without Psycopg authority."""
    driver = _Driver()
    monkeypatch.setattr(token_counter_module, "psycopg", None)
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


def test_token_counter_uses_driver_error_classification_for_encode_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Undefined-function fallback must not depend on a Psycopg exception class."""
    driver = _Driver(fail_primary_count=True)
    monkeypatch.setattr(token_counter_module, "psycopg", None)
    monkeypatch.setattr(
        token_counter_module,
        "get_model_metadata",
        lambda _dsn, _model, *, postgres_driver=None: {"tokenizer_model": "o200k_base"},
    )

    counter = TokenCounter("postgresql://x", postgres_driver=driver)

    assert counter.count_tokens("hello", "model-a") == 9
    assert any("tiktoken_encode" in query for query, _params in driver.executions)
