from __future__ import annotations

from collections.abc import Mapping

import pytest

from pg_llm_batch.postgres_driver_port import (
    PostgresConnectionPort,
    PostgresCursorPort,
    PostgresDriverPort,
)


def test_cursor_port_covers_existing_database_interaction_surface() -> None:
    assert PostgresCursorPort.__abstractmethods__ == {
        "__enter__",
        "__exit__",
        "execute",
        "executemany",
        "fetchall",
        "fetchmany",
        "fetchone",
    }


def test_connection_port_covers_transaction_and_cursor_lifecycle() -> None:
    assert PostgresConnectionPort.__abstractmethods__ == {
        "__enter__",
        "__exit__",
        "close",
        "commit",
        "cursor",
        "execute",
        "is_closed",
        "rollback",
        "set_autocommit",
    }


def test_driver_port_covers_psycopg_replacement_capabilities_only() -> None:
    assert PostgresDriverPort.__abstractmethods__ == {
        "connect",
        "is_undefined_function",
        "jsonb",
        "make_conninfo",
        "parse_conninfo",
    }
    assert not hasattr(PostgresDriverPort, "discover_model")
    assert not hasattr(PostgresDriverPort, "route_model")
    assert not hasattr(PostgresDriverPort, "select_provider")


class _Cursor(PostgresCursorPort):
    def __init__(self) -> None:
        self.executions: list[tuple[str, object | None]] = []

    def execute(self, query: str, params: object | None = None) -> _Cursor:
        self.executions.append((query, params))
        return self

    def executemany(self, query: str, params_seq: object) -> _Cursor:
        self.executions.append((query, params_seq))
        return self

    def fetchone(self) -> object | None:
        return ("row",)

    def fetchmany(self, size: int) -> list[object]:
        return [("row",)] * size

    def fetchall(self) -> list[object]:
        return [("row",)]

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        return None


class _Connection(PostgresConnectionPort):
    def __init__(self) -> None:
        self.cursor_instance = _Cursor()
        self.committed = False
        self.rolled_back = False
        self.closed = False
        self.autocommit = False

    def cursor(self) -> _Cursor:
        return self.cursor_instance

    def execute(self, query: str, params: object | None = None) -> _Cursor:
        return self.cursor_instance.execute(query, params)

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def set_autocommit(self, enabled: bool) -> None:
        self.autocommit = enabled

    def is_closed(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True

    def __enter__(self) -> _Connection:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> None:
        self.close()


class _UndefinedFunctionError(Exception):
    pass


class _Driver(PostgresDriverPort):
    def connect(
        self,
        dsn: str,
        *,
        connect_timeout_seconds: float | None = None,
    ) -> _Connection:
        assert dsn == "service=pg_llm_batch"
        assert connect_timeout_seconds == 5.0
        return _Connection()

    def parse_conninfo(self, dsn: str) -> Mapping[str, str]:
        key, value = dsn.split("=", 1)
        return {key: value}

    def make_conninfo(self, params: Mapping[str, str]) -> str:
        return " ".join(f"{key}={value}" for key, value in sorted(params.items()))

    def jsonb(self, value: object) -> object:
        return ("jsonb", value)

    def is_undefined_function(self, error: BaseException) -> bool:
        return isinstance(error, _UndefinedFunctionError)


def test_complete_port_can_run_without_psycopg_types() -> None:
    driver = _Driver()

    connection = driver.connect(
        "service=pg_llm_batch",
        connect_timeout_seconds=5.0,
    )
    assert connection.is_closed() is False
    connection.set_autocommit(True)
    assert connection.autocommit is True

    with connection as active_connection:
        with active_connection.cursor() as cursor:
            cursor.execute("SELECT %s", ("tenant-a",))
            cursor.executemany("SELECT %s", [("tenant-a",), ("tenant-b",)])
            assert cursor.fetchone() == ("row",)
            assert cursor.fetchmany(1) == [("row",)]
            assert cursor.fetchall() == [("row",)]
        active_connection.commit()

    assert connection.committed is True
    assert connection.is_closed() is True
    assert driver.parse_conninfo("service=pg_llm_batch") == {
        "service": "pg_llm_batch"
    }
    assert driver.make_conninfo({"service": "pg_llm_batch"}) == (
        "service=pg_llm_batch"
    )
    assert driver.jsonb({"request_id": "opaque"}) == (
        "jsonb",
        {"request_id": "opaque"},
    )
    assert driver.is_undefined_function(_UndefinedFunctionError()) is True
    assert driver.is_undefined_function(RuntimeError()) is False


def test_incomplete_driver_cannot_be_instantiated() -> None:
    class _IncompleteDriver(PostgresDriverPort):
        def connect(
            self,
            dsn: str,
            *,
            connect_timeout_seconds: float | None = None,
        ) -> PostgresConnectionPort:
            raise AssertionError("not called")

    with pytest.raises(TypeError):
        _IncompleteDriver()
