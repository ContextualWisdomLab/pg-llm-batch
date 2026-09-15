# SPDX-License-Identifier: Apache-2.0
"""Driver-port adapter for legacy in-memory PostgreSQL unit-test fakes.

Production bounded contexts no longer import Psycopg directly while the
commercial driver migration is in progress. These wrappers let the existing
in-memory SQL fake exercise the same ``PostgresDriverPort`` contract without
reintroducing concrete-client authority into product code.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pg_llm_batch.postgres_driver_port import PostgresConnectionPort


class _FakeCursorPort:
    """Adapt one legacy fake cursor to the driver-neutral cursor contract."""

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    def execute(self, query: str, params: object | None = None) -> _FakeCursorPort:
        self._cursor.execute(query, params)
        return self

    def executemany(self, query: str, params_seq: object) -> _FakeCursorPort:
        self._cursor.executemany(query, params_seq)
        return self

    def fetchone(self) -> tuple[object, ...] | None:
        row = self._cursor.fetchone()
        return None if row is None else tuple(row)

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        fetchmany = getattr(self._cursor, "fetchmany", None)
        if not callable(fetchmany):
            return self.fetchall()[:size]
        return [tuple(row) for row in fetchmany(size)]

    def fetchall(self) -> list[tuple[object, ...]]:
        return [tuple(row) for row in self._cursor.fetchall()]

    def row_count(self) -> int | None:
        value = getattr(self._cursor, "rowcount", None)
        if value is None or value == -1:
            return None
        return int(value)

    def __enter__(self) -> _FakeCursorPort:
        self._cursor.__enter__()
        return self

    def __exit__(self, *exc: object) -> object:
        return self._cursor.__exit__(*exc)


class _FakeConnectionPort:
    """Adapt one legacy fake connection while preserving exact session identity."""

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def cursor(self) -> _FakeCursorPort:
        return _FakeCursorPort(self._connection.cursor())

    def execute(self, query: str, params: object | None = None) -> _FakeCursorPort:
        cursor = self.cursor()
        return cursor.execute(query, params)

    def commit(self) -> None:
        self._connection.commit()

    def rollback(self) -> None:
        rollback = getattr(self._connection, "rollback", None)
        if callable(rollback):
            rollback()

    def set_autocommit(self, enabled: bool) -> None:
        self._connection.autocommit = enabled

    def is_closed(self) -> bool:
        return bool(self._connection.closed)

    def close(self) -> None:
        self._connection.close()

    def __enter__(self) -> _FakeConnectionPort:
        self._connection.__enter__()
        return self

    def __exit__(self, *exc: object) -> object:
        return self._connection.__exit__(*exc)


class FakePsycopgDriverPort:
    """Expose ``tests.conftest.FakePsycopg`` through ``PostgresDriverPort``.

    The fake intentionally implements only deterministic unit-test semantics.
    Real PostgreSQL compatibility, RLS, recovery, and candidate admission remain
    covered by their dedicated integration lanes rather than being inferred from
    this in-memory adapter.
    """

    def __init__(self, psycopg_fake: Any) -> None:
        self._psycopg_fake = psycopg_fake

    def connect(
        self,
        dsn: str,
        *,
        connect_timeout_seconds: int | None = None,
    ) -> PostgresConnectionPort:
        kwargs: dict[str, object] = {}
        if connect_timeout_seconds is not None:
            kwargs["connect_timeout"] = connect_timeout_seconds
        return _FakeConnectionPort(self._psycopg_fake.connect(dsn, **kwargs))

    def parse_conninfo(self, dsn: str) -> Mapping[str, str]:
        return {"dsn": dsn}

    def make_conninfo(self, params: Mapping[str, str]) -> str:
        return str(params.get("dsn", ""))

    def jsonb(self, value: object) -> object:
        return value

    def is_invalid_conninfo(self, error: BaseException) -> bool:
        return False

    def is_undefined_function(self, error: BaseException) -> bool:
        return isinstance(error, self._psycopg_fake.errors.UndefinedFunction)
