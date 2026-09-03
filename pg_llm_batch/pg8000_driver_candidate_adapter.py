"""Candidate-only pg8000 DB-API adapters for commercial migration evidence.

This module intentionally stops short of a production ``PostgresDriverPort``.
pg8000 1.31.5 documents the DB-API cursor, transaction, autocommit, parameter
binding, and ``-1`` unknown-row-count behavior needed by part of the current
port, but pg-llm-batch has not yet proved its full conninfo/service-selector,
JSONB adaptation, closed-state, PostgreSQL error-classification, Python 3.14,
RLS, recovery, concurrency, package, SBOM, and provenance contract on one exact
artifact. Keeping this adapter candidate-only lets those portable semantics be
exercised without making an unreleased or unverified runtime dependency
canonical.
"""

from __future__ import annotations

from types import ModuleType
from typing import Any, cast

from .postgres_driver_port import PostgresConnectionPort, PostgresCursorPort


class Pg8000CandidateAdapterError(RuntimeError):
    """Report a candidate-boundary mismatch without exposing database content.

    A mismatch means the candidate cannot yet be promoted through the shared
    PostgreSQL port. The error is deliberately separate from pg8000's database
    exceptions so callers cannot mistake missing adapter evidence for a server
    or application failure.
    """


def validate_pg8000_dbapi_module(dbapi_module: object) -> None:
    """Fail closed unless the imported pg8000 DB-API mode matches package SQL.

    pg8000 exposes ``paramstyle`` as mutable module state. pg-llm-batch's current
    SQL uses DB-API ``format`` placeholders, so a future production candidate
    factory must run this guard immediately after importing the exact admitted
    pg8000 artifact and before creating adapters or executing SQL. Metadata is
    read from an exact ``ModuleType`` dictionary rather than through arbitrary
    shaped objects whose attribute access could execute caller-controlled code.

    Raises:
        Pg8000CandidateAdapterError: If DB-API 2.0 or ``format`` parameter style
            is not the exact active module contract.
    """
    if type(dbapi_module) is not ModuleType:
        raise Pg8000CandidateAdapterError("PostgreSQL driver module identity is invalid")

    module = cast(ModuleType, dbapi_module)
    metadata = vars(module)
    api_level = metadata.get("apilevel")
    parameter_style = metadata.get("paramstyle")

    if type(api_level) is not str or api_level != "2.0":
        raise Pg8000CandidateAdapterError("PostgreSQL driver API level is incompatible")
    if type(parameter_style) is not str or parameter_style != "format":
        raise Pg8000CandidateAdapterError(
            "PostgreSQL driver parameter style is incompatible"
        )


class Pg8000CandidateCursorAdapter(PostgresCursorPort):
    """Exercise pg8000 DB-API cursor semantics behind the canonical cursor port.

    The raw cursor remains dependency-injected because this candidate slice must
    not add pg8000 to the production dependency graph before the exact artifact
    passes license, security, Python, PostgreSQL, and recovery admission. Query
    text and bound parameters are forwarded unchanged; materialized list rows are
    normalized to the tuple representation already used by pg-llm-batch.
    """

    def __init__(self, cursor: Any) -> None:
        self._cursor = cursor

    @staticmethod
    def _normalize_result_row(row: object) -> tuple[object, ...]:
        """Normalize one DB-API positional row while rejecting ambiguous shapes.

        pg8000 documents list-like result rows. The package canonicalizes exact
        ``list`` and ``tuple`` containers only; mapping or custom containers are
        rejected so a driver-specific row factory cannot silently change domain
        indexing or equality semantics.
        """
        if type(row) is tuple:
            return row
        if type(row) is list:
            return tuple(row)
        raise Pg8000CandidateAdapterError("PostgreSQL driver result row is invalid")

    def execute(
        self,
        query: str,
        params: object | None = None,
    ) -> Pg8000CandidateCursorAdapter:
        """Forward package-authored SQL and bound parameters without interpolation.

        pg8000's DB-API interface defaults to ``format`` parameter style, which
        matches the existing ``%s`` package SQL. This candidate method forwards
        both objects unchanged so later real-driver tests can detect any semantic
        mismatch rather than hiding it in an adapter rewrite.
        """
        self._cursor.execute(query, params)
        return self

    def executemany(
        self,
        query: str,
        params_seq: object,
    ) -> Pg8000CandidateCursorAdapter:
        """Forward one statement and parameter sequence without implicit commits.

        Transaction ownership remains with the retained connection. The adapter
        therefore does not commit between items or transform the supplied
        sequence into independently executed application operations.
        """
        self._cursor.executemany(query, params_seq)
        return self

    def fetchone(self) -> tuple[object, ...] | None:
        """Return one canonical tuple row or ``None`` at end of results.

        Only row-container normalization belongs here. Field-count, type, tenant,
        and domain validation remain responsibilities of the consuming bounded
        context after the database adapter returns.
        """
        row = self._cursor.fetchone()
        if row is None:
            return None
        return self._normalize_result_row(row)

    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        """Return a bounded result page and reject invalid caller size values.

        ``bool`` is rejected even though it subclasses ``int`` because an
        accidental truth value must not become a one-row resource budget.
        """
        if type(size) is not int or size <= 0:
            raise Pg8000CandidateAdapterError("PostgreSQL driver fetch size is invalid")
        return [self._normalize_result_row(row) for row in self._cursor.fetchmany(size)]

    def fetchall(self) -> list[tuple[object, ...]]:
        """Normalize all rows from an already bounded package-authored query.

        This preserves current package compatibility but does not authorize new
        unbounded queries; untrusted-result paths must continue to enforce their
        own finite SQL and fetch budgets.
        """
        return [self._normalize_result_row(row) for row in self._cursor.fetchall()]

    def row_count(self) -> int | None:
        """Normalize pg8000's documented ``-1`` unknown row count to ``None``.

        Exact non-negative counts remain usable as mutation evidence. Any other
        negative sentinel or non-integer value fails closed because the package
        must not interpret an undocumented driver state as exact write success.
        """
        value = self._cursor.rowcount
        if type(value) is not int:
            raise Pg8000CandidateAdapterError("PostgreSQL driver row count is invalid")
        if value == -1:
            return None
        if value < 0:
            raise Pg8000CandidateAdapterError("PostgreSQL driver row count is invalid")
        return value

    def __enter__(self) -> Pg8000CandidateCursorAdapter:
        """Enter the raw cursor context while keeping this adapter's identity.

        Candidate acceptance must later prove the real pg8000 cursor implements
        compatible context-manager cleanup; this wrapper does not synthesize that
        behavior when it is absent.
        """
        self._cursor.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool | None:
        """Delegate raw cursor cleanup and preserve exception propagation policy.

        The return value is forwarded exactly because changing it could suppress
        a database or application exception and create false transaction success.
        """
        return self._cursor.__exit__(exc_type, exc, traceback)


class Pg8000CandidateConnectionAdapter(PostgresConnectionPort):
    """Exercise portable pg8000 DB-API connection semantics on one raw connection.

    This adapter proves only the connection/cursor portion of the migration port.
    It never opens a connection itself and therefore cannot bypass the still-open
    DSN/conninfo/service-selector admission problem. All operations stay on the
    injected raw connection so transaction-local RLS state cannot migrate to an
    implicit second session.
    """

    def __init__(self, connection: Any) -> None:
        self._connection = connection

    def cursor(self) -> Pg8000CandidateCursorAdapter:
        """Create a candidate cursor on this exact retained database connection.

        No second connection or hidden pool is introduced. Later PostgreSQL
        acceptance must prove the real driver preserves the same session for
        tenant-local ``set_config`` and lifecycle SQL.
        """
        return Pg8000CandidateCursorAdapter(self._connection.cursor())

    def execute(
        self,
        query: str,
        params: object | None = None,
    ) -> Pg8000CandidateCursorAdapter:
        """Execute through a cursor created from this retained connection only.

        DB-API does not require ``Connection.execute``. Creating a cursor here
        keeps the canonical convenience method while preserving parameter binding
        and session identity instead of depending on a non-portable extension.
        """
        cursor = self.cursor()
        cursor.execute(query, params)
        return cursor

    def commit(self) -> None:
        """Commit the current local transaction through the raw DB-API connection.

        The adapter adds no retry or distributed-delivery semantics; higher
        bounded contexts retain responsibility for replay and idempotency.
        """
        self._connection.commit()

    def rollback(self) -> None:
        """Roll back the current local transaction and propagate driver failures.

        Rollback errors remain visible because hiding them would make recovery
        evidence claim a clean transaction boundary that PostgreSQL did not prove.
        """
        self._connection.rollback()

    def set_autocommit(self, enabled: bool) -> None:
        """Set pg8000's documented autocommit property from an exact boolean only.

        Rejecting integer truthiness prevents configuration mistakes from being
        normalized into transaction-policy changes at the infrastructure edge.
        """
        if type(enabled) is not bool:
            raise Pg8000CandidateAdapterError("PostgreSQL driver autocommit is invalid")
        self._connection.autocommit = enabled

    def is_closed(self) -> bool:
        """Return an exact public closed-state signal or fail candidate admission.

        The current PostgreSQL port requires deterministic cached-connection
        recovery, while pg8000's public DB-API documentation reviewed for this
        slice does not establish a portable closed-state attribute. Candidate
        runtime tests must therefore supply and prove an exact boolean signal;
        absence or an ambiguous value is a compatibility failure, not ``False``.
        """
        try:
            value = self._connection.closed
        except AttributeError:
            raise Pg8000CandidateAdapterError(
                "PostgreSQL driver closed state is unavailable"
            ) from None
        if type(value) is not bool:
            raise Pg8000CandidateAdapterError(
                "PostgreSQL driver closed state is unavailable"
            )
        return value

    def close(self) -> None:
        """Close the retained raw connection and release its session authority.

        The candidate does not retain or recreate a hidden connection after this
        call; later real-driver recovery tests must prove cleanup and reconnect
        behavior under process and database failures.
        """
        self._connection.close()

    def __enter__(self) -> Pg8000CandidateConnectionAdapter:
        """Enter the raw connection context without changing transaction policy.

        Real pg8000 acceptance must verify its DB-API context manager has the
        commit/rollback semantics required by the port before this candidate can
        become a production driver.
        """
        self._connection.__enter__()
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool | None:
        """Delegate connection-context exit without suppressing raw-driver errors.

        Returning the raw value preserves its transaction and exception behavior
        for later parity tests instead of making the candidate look compatible by
        changing failure semantics in the wrapper.
        """
        return self._connection.__exit__(exc_type, exc, traceback)
