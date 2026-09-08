"""Psycopg adapter for the provider-neutral PostgreSQL driver port.

This module is a migration baseline, not the commercial replacement itself. It
encapsulates the PostgreSQL-client behavior that existing pg-llm-batch code
currently receives from Psycopg so a future permissively licensed adapter can be
verified against the same transaction, parameter-binding, conninfo, JSONB, and
error-classification contract before the LGPL-family runtime dependency is
removed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import psycopg
from psycopg import ProgrammingError
from psycopg.conninfo import conninfo_to_dict, make_conninfo
from psycopg.errors import UndefinedFunction
from psycopg.types.json import Jsonb

from .postgres_driver_port import (
    PostgresConnectionPort,
    PostgresCursorPort,
    PostgresDriverPort,
)


class PsycopgDriverAdapterError(RuntimeError):
    """Report a fixed adapter-contract failure without reflecting database data.

    The adapter uses this error only when a driver-facing primitive violates the
    migration port itself, such as a non-boolean autocommit state, unsupported row
    container, or a row-count value with the wrong Python type. PostgreSQL
    execution errors continue to propagate through Psycopg so existing bounded
    contexts can classify them.
    """


class PsycopgInvalidConninfoError(PsycopgDriverAdapterError):
    """Identify conninfo grammar failures created at the adapter parsing boundary.

    Psycopg's public ``ProgrammingError`` class also represents server-side SQL
    errors such as undefined tables and malformed statements. Wrapping only
    failures raised by conninfo parsing/rendering prevents those unrelated
    database errors from being misclassified as an invalid DSN.
    """


class PsycopgCursorAdapter(PostgresCursorPort):
    """Wrap one PostgreSQL cursor while preserving canonical tuple row semantics.

    Package-authored query text and bound parameters are handed to the retained
    cursor unchanged. Result rows are normalized from exact tuple/list containers
    to tuples because current pg-llm-batch bounded contexts use positional tuple
    identity and equality. This keeps a future DB-API driver that returns list rows
    from silently changing application behavior.
    """

    def __init__(self, cursor: Any) -> None:
        """Retain one Psycopg cursor behind the driver-neutral cursor contract."""
        self._cursor = cursor

    @staticmethod
    def _normalize_result_row(row: object) -> tuple[object, ...]:
        """Normalize one materialized DB-API row to the positional tuple contract."""
        if type(row) is tuple:
            return row
        if type(row) is list:
            return tuple(row)
        raise PsycopgDriverAdapterError("PostgreSQL driver result row is invalid")

    def execute(
        self,
        query: str,
        params: object | None = None,
    ) -> PsycopgCursorAdapter:
        """Execute one query with Psycopg parameter binding and retain this wrapper."""
        self._cursor.execute(query, params)
        return self

    def executemany(
        self,
        query: str,
        params_seq: object,
    ) -> PsycopgCursorAdapter:
        """Execute one query for a parameter sequence without implicit commits."""
        self._cursor.executemany(query, params_seq)
        return self

    def fetchone(self) -> tuple[object, ...] | None:
        """Return one canonical tuple row, or ``None`` only for end-of-results."""
        row = self._cursor.fetchone()
        if row is None:
            return None
        return self._normalize_result_row(row)

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        """Return at most the requested finite page and reject malformed results."""
        if type(size) is not int or size <= 0:
            raise PsycopgDriverAdapterError("PostgreSQL driver fetch size is invalid")
        rows = self._cursor.fetchmany(size)
        try:
            returned_count = len(rows)
        except (TypeError, ValueError, OverflowError):
            raise PsycopgDriverAdapterError(
                "PostgreSQL driver fetch result is invalid"
            ) from None
        if returned_count > size:
            raise PsycopgDriverAdapterError(
                "PostgreSQL driver fetch result exceeds requested size"
            )
        return [self._normalize_result_row(row) for row in rows]

    def fetchall(self) -> list[tuple[object, ...]]:
        """Return bounded query results while rejecting malformed rows."""
        return [self._normalize_result_row(row) for row in self._cursor.fetchall()]

    def row_count(self) -> int | None:
        """Return an exact non-negative count or normalize Psycopg's unknown sentinel."""
        value = self._cursor.rowcount
        if type(value) is not int:
            raise PsycopgDriverAdapterError("PostgreSQL driver row count is invalid")
        if value == -1:
            return None
        if value < 0:
            raise PsycopgDriverAdapterError("PostgreSQL driver row count is invalid")
        return value

    def __enter__(self) -> PsycopgCursorAdapter:
        """Enter the retained cursor context while preserving wrapper identity."""
        self._cursor.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool | None:
        """Delegate cursor cleanup and exception propagation to Psycopg."""
        return self._cursor.__exit__(exc_type, exc, traceback)


class PsycopgConnectionAdapter(PostgresConnectionPort):
    """Wrap one Psycopg connection while preserving its session and transaction.

    The same retained raw connection backs cursor creation, direct execution,
    commit, rollback, autocommit selection, and closed-state inspection. The
    adapter therefore cannot silently move tenant-local ``set_config`` state to
    another connection.
    """

    def __init__(self, connection: Any) -> None:
        """Retain one Psycopg connection as the exact session capability."""
        self._connection = connection

    def cursor(self) -> PsycopgCursorAdapter:
        """Create a wrapped cursor on this exact retained PostgreSQL connection."""
        return PsycopgCursorAdapter(self._connection.cursor())

    def execute(
        self,
        query: str,
        params: object | None = None,
    ) -> PsycopgCursorAdapter:
        """Execute through this connection without opening an implicit second one."""
        return PsycopgCursorAdapter(self._connection.execute(query, params))

    def commit(self) -> None:
        """Commit the current local PostgreSQL transaction through Psycopg."""
        self._connection.commit()

    def rollback(self) -> None:
        """Roll back the current local PostgreSQL transaction through Psycopg."""
        self._connection.rollback()

    def set_autocommit(self, enabled: bool) -> None:
        """Set Psycopg autocommit only from an exact boolean policy decision."""
        if type(enabled) is not bool:
            raise PsycopgDriverAdapterError("PostgreSQL driver autocommit is invalid")
        self._connection.autocommit = enabled

    def is_closed(self) -> bool:
        """Return Psycopg's public closed-state signal without truthiness coercion."""
        value = self._connection.closed
        if type(value) is not bool:
            raise PsycopgDriverAdapterError("PostgreSQL driver closed state is invalid")
        return value

    def close(self) -> None:
        """Close the retained PostgreSQL connection and release its session state."""
        self._connection.close()

    def __enter__(self) -> PsycopgConnectionAdapter:
        """Enter Psycopg's connection context while preserving wrapper identity."""
        self._connection.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool | None:
        """Delegate transaction-context exit and error propagation to Psycopg."""
        return self._connection.__exit__(exc_type, exc, traceback)


class PsycopgDriverAdapter(PostgresDriverPort):
    """Expose existing Psycopg behavior through the migration anti-corruption port.

    This class establishes a parity baseline only. It does not make Psycopg an
    approved commercial dependency and it does not acquire model/provider routing
    authority from contextual-orchestrator.
    """

    def connect(
        self,
        dsn: str,
        *,
        connect_timeout_seconds: int | None = None,
    ) -> PsycopgConnectionAdapter:
        """Connect with an optional exact positive libpq timeout in whole seconds."""
        kwargs: dict[str, int] = {}
        if connect_timeout_seconds is not None:
            if type(connect_timeout_seconds) is not int or connect_timeout_seconds <= 0:
                raise PsycopgDriverAdapterError("PostgreSQL driver timeout is invalid")
            kwargs["connect_timeout"] = connect_timeout_seconds
        return PsycopgConnectionAdapter(psycopg.connect(dsn, **kwargs))

    def parse_conninfo(self, dsn: str) -> Mapping[str, str]:
        """Parse conninfo and narrow Psycopg's broad ProgrammingError category."""
        try:
            return conninfo_to_dict(dsn)
        except ProgrammingError:
            raise PsycopgInvalidConninfoError(
                "PostgreSQL connection selector is invalid"
            ) from None

    def make_conninfo(self, params: Mapping[str, str]) -> str:
        """Render conninfo and narrow Psycopg's broad ProgrammingError category."""
        try:
            return make_conninfo(**dict(params))
        except ProgrammingError:
            raise PsycopgInvalidConninfoError(
                "PostgreSQL connection selector is invalid"
            ) from None

    def jsonb(self, value: object) -> Jsonb:
        """Wrap a validated Python value in Psycopg's JSONB parameter adapter."""
        return Jsonb(value)

    def is_invalid_conninfo(self, error: BaseException) -> bool:
        """Recognize only errors wrapped at the conninfo grammar boundary."""
        return isinstance(error, PsycopgInvalidConninfoError)

    def is_undefined_function(self, error: BaseException) -> bool:
        """Recognize only Psycopg's PostgreSQL undefined-function error category."""
        return isinstance(error, UndefinedFunction)
