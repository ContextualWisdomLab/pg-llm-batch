from __future__ import annotations

from typing import Any

import pytest
from psycopg import ProgrammingError
from psycopg.errors import UndefinedFunction
from psycopg.types.json import Jsonb

from pg_llm_batch.postgres_driver_port import PostgresDriverPort
from pg_llm_batch.psycopg_driver_adapter import (
    PsycopgConnectionAdapter,
    PsycopgCursorAdapter,
    PsycopgDriverAdapter,
    PsycopgDriverAdapterError,
)


class _RawCursor:
    def __init__(self) -> None:
        self.executions: list[tuple[str, object | None]] = []
        self.many_executions: list[tuple[str, object]] = []
        self.rows: list[object] = [["one"], ["two"]]
        self.rowcount: object = 2
        self.entered = False
        self.exited = False

    def execute(self, query: str, params: object | None = None) -> _RawCursor:
        self.executions.append((query, params))
        return self

    def executemany(self, query: str, params_seq: object) -> None:
        self.many_executions.append((query, params_seq))

    def fetchone(self) -> object | None:
        return self.rows[0] if self.rows else None

    def fetchmany(self, size: int) -> list[object]:
        return list(self.rows[:size])

    def fetchall(self) -> list[object]:
        return list(self.rows)

    def __enter__(self) -> _RawCursor:
        self.entered = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool | None:
        self.exited = True
        return None


class _RawConnection:
    def __init__(self) -> None:
        self.autocommit = False
        self.closed = False
        self.cursor_value = _RawCursor()
        self.commits = 0
        self.rollbacks = 0
        self.close_calls = 0
        self.entered = False
        self.exited = False

    def cursor(self) -> _RawCursor:
        return self.cursor_value

    def execute(self, query: str, params: object | None = None) -> _RawCursor:
        return self.cursor_value.execute(query, params)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True

    def __enter__(self) -> _RawConnection:
        self.entered = True
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool | None:
        self.exited = True
        return None


def test_psycopg_driver_is_provider_neutral_port_implementation() -> None:
    assert isinstance(PsycopgDriverAdapter(), PostgresDriverPort)


def test_cursor_adapter_preserves_parameter_and_result_authority() -> None:
    raw = _RawCursor()
    cursor = PsycopgCursorAdapter(raw)

    assert cursor.execute("SELECT %s", ("tenant-a",)) is cursor
    assert raw.executions == [("SELECT %s", ("tenant-a",))]

    batch = [(1,), (2,)]
    assert cursor.executemany("INSERT INTO example VALUES (%s)", batch) is cursor
    assert raw.many_executions == [("INSERT INTO example VALUES (%s)", batch)]

    assert cursor.fetchone() == ("one",)
    assert cursor.fetchmany(1) == [("one",)]
    assert cursor.fetchall() == [("one",), ("two",)]
    assert cursor.row_count() == 2


def test_cursor_adapter_rejects_none_inside_materialized_result_page() -> None:
    raw = _RawCursor()
    raw.rows = [["one"], None]
    cursor = PsycopgCursorAdapter(raw)

    with pytest.raises(PsycopgDriverAdapterError, match="result row"):
        cursor.fetchmany(2)
    with pytest.raises(PsycopgDriverAdapterError, match="result row"):
        cursor.fetchall()


@pytest.mark.parametrize("invalid_size", [True, 0, -1, 1.5])
def test_cursor_adapter_rejects_non_positive_or_non_integer_fetch_budget(
    invalid_size: object,
) -> None:
    raw = _RawCursor()

    with pytest.raises(PsycopgDriverAdapterError, match="fetch size"):
        PsycopgCursorAdapter(raw).fetchmany(invalid_size)  # type: ignore[arg-type]


def test_cursor_adapter_rejects_non_integer_row_count() -> None:
    raw = _RawCursor()
    raw.rowcount = True

    with pytest.raises(PsycopgDriverAdapterError, match="row count"):
        PsycopgCursorAdapter(raw).row_count()


def test_cursor_adapter_preserves_context_manager_boundary() -> None:
    raw = _RawCursor()
    cursor = PsycopgCursorAdapter(raw)

    with cursor as entered:
        assert entered is cursor

    assert raw.entered is True
    assert raw.exited is True


def test_connection_adapter_preserves_transaction_and_session_semantics() -> None:
    raw = _RawConnection()
    connection = PsycopgConnectionAdapter(raw)

    cursor = connection.cursor()
    assert isinstance(cursor, PsycopgCursorAdapter)
    assert cursor.execute("SELECT %s", (1,)) is cursor

    direct = connection.execute("SELECT %s", (2,))
    assert isinstance(direct, PsycopgCursorAdapter)
    assert raw.cursor_value.executions[-1] == ("SELECT %s", (2,))

    connection.commit()
    connection.rollback()
    assert raw.commits == 1
    assert raw.rollbacks == 1

    connection.set_autocommit(True)
    assert raw.autocommit is True
    assert connection.is_closed() is False

    connection.close()
    assert raw.close_calls == 1
    assert connection.is_closed() is True


def test_connection_adapter_rejects_non_boolean_autocommit() -> None:
    raw = _RawConnection()

    with pytest.raises(PsycopgDriverAdapterError, match="autocommit"):
        PsycopgConnectionAdapter(raw).set_autocommit(1)  # type: ignore[arg-type]

    assert raw.autocommit is False


def test_connection_adapter_preserves_context_manager_boundary() -> None:
    raw = _RawConnection()
    connection = PsycopgConnectionAdapter(raw)

    with connection as entered:
        assert entered is connection

    assert raw.entered is True
    assert raw.exited is True


def test_driver_uses_psycopg_conninfo_and_jsonb_contracts() -> None:
    driver = PsycopgDriverAdapter()

    parsed = driver.parse_conninfo("host=localhost dbname='batch db' application_name=pg-llm-batch")
    assert parsed == {
        "host": "localhost",
        "dbname": "batch db",
        "application_name": "pg-llm-batch",
    }

    rendered = driver.make_conninfo(parsed)
    assert driver.parse_conninfo(rendered) == parsed

    adapted = driver.jsonb({"count": 1})
    assert isinstance(adapted, Jsonb)
    assert adapted.obj == {"count": 1}


def test_driver_classifies_only_adapter_owned_conninfo_grammar_failures() -> None:
    driver = PsycopgDriverAdapter()

    with pytest.raises(PsycopgDriverAdapterError) as invalid_conninfo:
        driver.parse_conninfo("host='unterminated")

    assert driver.is_invalid_conninfo(invalid_conninfo.value) is True
    assert driver.is_invalid_conninfo(ProgrammingError("syntax error")) is False
    assert driver.is_invalid_conninfo(RuntimeError("invalid conninfo")) is False


def test_driver_classifies_only_psycopg_undefined_function() -> None:
    driver = PsycopgDriverAdapter()

    assert driver.is_undefined_function(UndefinedFunction("missing")) is True
    assert driver.is_undefined_function(RuntimeError("missing")) is False


def test_driver_connect_preserves_exact_timeout_and_wraps_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _RawConnection()
    calls: list[tuple[str, dict[str, Any]]] = []

    def fake_connect(dsn: str, **kwargs: Any) -> _RawConnection:
        calls.append((dsn, kwargs))
        return raw

    monkeypatch.setattr("pg_llm_batch.psycopg_driver_adapter.psycopg.connect", fake_connect)

    connection = PsycopgDriverAdapter().connect(
        "host=localhost dbname=batch",
        connect_timeout_seconds=7,
    )

    assert isinstance(connection, PsycopgConnectionAdapter)
    assert calls == [("host=localhost dbname=batch", {"connect_timeout": 7})]


def test_driver_connect_fails_closed_on_invalid_timeout_before_driver_call(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    called = False

    def fake_connect(*args: object, **kwargs: object) -> None:
        nonlocal called
        called = True

    monkeypatch.setattr("pg_llm_batch.psycopg_driver_adapter.psycopg.connect", fake_connect)

    for invalid in (True, 0, -1, 1.5):
        with pytest.raises(PsycopgDriverAdapterError, match="timeout"):
            PsycopgDriverAdapter().connect(
                "host=localhost dbname=batch",
                connect_timeout_seconds=invalid,  # type: ignore[arg-type]
            )

    assert called is False
