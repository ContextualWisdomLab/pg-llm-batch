"""Recovery regressions for terminal pg_tiktoken capability loss.

A replacement PostgreSQL driver may classify both supported pg_tiktoken entry
points as undefined at runtime, for example after an extension rollback or a
misrouted connection.  Once the counter marks the capability unavailable it
must also release the cached session; retaining an unusable connection would
leak a database resource that the counter intentionally never retries.
"""

from __future__ import annotations

from typing import Any

import pytest

import pg_llm_batch.token_counter as token_counter_module
from pg_llm_batch.token_counter import TokenCounter


class _UndefinedFunctionError(RuntimeError):
    """Represent one driver-classified PostgreSQL undefined-function error."""


class _Cursor:
    """Expose a healthy capability probe followed by two missing functions."""

    def __init__(self, driver: _Driver) -> None:
        self._driver = driver

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def execute(self, query: str, params: object | None = None) -> _Cursor:
        if "to_regprocedure" in query:
            self._driver.rows.append((True, True, True))
            return self
        if "tiktoken_count" in query or "tiktoken_encode" in query:
            raise _UndefinedFunctionError("pg_tiktoken function unavailable")
        raise AssertionError(f"unexpected SQL in cleanup regression: {query!r}")

    def fetchone(self) -> tuple[object, ...] | None:
        if not self._driver.rows:
            return None
        return self._driver.rows.pop(0)


class _Connection:
    """Track whether terminal capability loss releases the retained session."""

    def __init__(self, driver: _Driver) -> None:
        self._driver = driver
        self.closed = False

    def cursor(self) -> _Cursor:
        return _Cursor(self._driver)

    def set_autocommit(self, enabled: bool) -> None:
        assert enabled is True

    def is_closed(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True


class _Driver:
    """Minimal driver port for terminal undefined-function recovery evidence."""

    def __init__(self) -> None:
        self.rows: list[tuple[object, ...]] = []
        self.connections: list[_Connection] = []

    def connect(
        self,
        dsn: str,
        *,
        connect_timeout_seconds: int | None = None,
    ) -> _Connection:
        assert dsn == "postgresql://candidate"
        assert connect_timeout_seconds is None
        connection = _Connection(self)
        self.connections.append(connection)
        return connection

    def is_undefined_function(self, error: BaseException) -> bool:
        return isinstance(error, _UndefinedFunctionError)


def test_terminal_undefined_function_failure_closes_cached_driver_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Both missing pg_tiktoken entry points must disable and release the session."""
    driver = _Driver()
    monkeypatch.setattr(token_counter_module, "psycopg", None)
    monkeypatch.setattr(
        token_counter_module,
        "get_model_metadata",
        lambda _dsn, _model, *, postgres_driver=None: {
            "tokenizer_model": "o200k_base"
        },
    )

    counter = TokenCounter("postgresql://candidate", postgres_driver=driver)

    with pytest.raises(RuntimeError, match="Token counting requires pg_tiktoken"):
        counter.count_tokens("hello", "model-a")

    assert len(driver.connections) == 1
    assert driver.connections[0].closed is True
    assert counter._pg_conn is None
    assert counter._pg_available is False
