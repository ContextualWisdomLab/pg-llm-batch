"""Candidate-only pg8000 DB-API adapters for commercial migration evidence.

This module intentionally stops short of a production ``PostgresDriverPort``.
pg8000 1.31.5 documents the DB-API cursor, transaction, autocommit, parameter
binding, module-only connection thread sharing, and ``-1`` unknown-row-count
behavior needed by part of the current port, but pg-llm-batch has not yet proved
its full conninfo/service-selector, JSONB adaptation, PostgreSQL
error-classification, Python 3.14, RLS, transport failure recovery, package,
SBOM, and provenance contract on one exact artifact. Keeping this adapter
candidate-only lets those portable semantics be exercised without making an
unreleased or unverified runtime dependency canonical.
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
    """Fail closed unless imported pg8000 DB-API metadata matches package use.

    pg8000 exposes ``paramstyle`` as mutable module state. pg-llm-batch's current
    SQL uses DB-API ``format`` placeholders, so a future production candidate
    factory must run this guard immediately after importing the exact admitted
    pg8000 artifact and before creating adapters or executing SQL. The documented
    ``threadsafety == 1`` value is also part of this boundary: code may share the
    module across threads but must not infer that one connection is shareable.
    Metadata is read from an exact ``ModuleType`` dictionary rather than through
    arbitrary shaped objects whose attribute access could execute caller-controlled
    code.

    Raises:
        Pg8000CandidateAdapterError: If DB-API level, parameter style, or thread
            sharing semantics differ from the exact reviewed candidate contract.
    """
    if type(dbapi_module) is not ModuleType:
        raise Pg8000CandidateAdapterError("PostgreSQL driver module identity is invalid")

    module = cast(ModuleType, dbapi_module)
    metadata = vars(module)
    api_level = metadata.get("apilevel")
    parameter_style = metadata.get("paramstyle")
    thread_safety = metadata.get("threadsafety")

    if type(api_level) is not str or api_level != "2.0":
        raise Pg8000CandidateAdapterError("PostgreSQL driver API level is incompatible")
    if type(parameter_style) is not str or parameter_style != "format":
        raise Pg8000CandidateAdapterError(
            "PostgreSQL driver parameter style is incompatible"
        )
    if type(thread_safety) is not int or thread_safety != 1:
        raise Pg8000CandidateAdapterError(
            "PostgreSQL driver thread safety is incompatible"
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
        """Return a bounded result page and reject invalid caller or driver budgets.

        ``bool`` is rejected even though it subclasses ``int`` because an
        accidental truth value must not become a one-row resource budget. The
        adapter also verifies that the concrete DB-API candidate honors that
        budget; over-delivery is a candidate-contract failure rather than extra
        data the application may silently materialize.
        """
        if type(size) is not int or size <= 0:
            raise Pg8000CandidateAdapterError("PostgreSQL driver fetch size is invalid")
        rows = self._cursor.fetchmany(size)
        try:
            returned_count = len(rows)
        except (TypeError, ValueError, OverflowError):
            raise Pg8000CandidateAdapterError(
                "PostgreSQL driver fetch result is invalid"
            ) from None
        if returned_count > size:
            raise Pg8000CandidateAdapterError(
                "PostgreSQL driver fetch result exceeds requested size"
            )
        return [self._normalize_result_row(row) for row in rows]

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
        """Enter the package cursor context without requiring a driver extension.

        Python DB-API 2.0 standardizes ``Cursor.close()`` but not a cursor context
        manager. The anti-corruption adapter therefore owns context entry instead
        of making an undocumented pg8000 ``__enter__`` method part of the product
        contract.
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool | None:
        """Close the DB-API cursor without replacing an active application error.

        Cursor exit owns resource cleanup only; transaction commit or rollback
        remains a connection-level responsibility. If cleanup fails while an
        application exception is already in flight, the application exception
        remains primary. A close-only failure still propagates. Returning
        ``False`` preserves ordinary context-manager exception propagation while
        avoiding a driver-specific cursor context-manager dependency.
        """
        try:
            self._cursor.close()
        except BaseException:
            if exc is not None:
                raise exc from None
            raise
        return False


class Pg8000CandidateConnectionAdapter(PostgresConnectionPort):
    """Exercise portable pg8000 DB-API connection semantics on one raw connection.

    This adapter proves only the connection/cursor portion of the migration port.
    It never opens a connection itself and therefore cannot bypass the still-open
    DSN/conninfo/service-selector admission problem. All operations stay on the
    injected raw connection so transaction-local RLS state cannot migrate to an
    implicit second session. The candidate's DB-API thread level does not permit
    callers to infer that this retained connection is safe to share across threads;
    that package-level concurrency boundary remains a separate admission gate.
    """

    def __init__(self, connection: Any) -> None:
        self._connection = connection
        self._closed = False

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
        """Execute on this connection and release the owned cursor on failure.

        DB-API does not require ``Connection.execute``. The adapter therefore
        creates the cursor itself and owns it until a successful execution hands
        the cursor back to the caller. If execution fails before that handoff,
        cleanup is attempted immediately so a database error cannot strand an
        unreachable cursor. A secondary close failure never replaces the primary
        execution failure.
        """
        cursor = self.cursor()
        try:
            cursor.execute(query, params)
        except BaseException as execution_error:
            try:
                cursor.__exit__(
                    type(execution_error),
                    execution_error,
                    execution_error.__traceback__,
                )
            except BaseException:
                raise execution_error from None
            raise
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
        """Report whether this adapter has successfully closed its raw connection.

        DB-API 2.0 requires ``close()`` but not a portable public liveness flag.
        The anti-corruption layer therefore tracks only the state it owns instead
        of reading a pg8000 implementation detail. This is intentionally not a
        network health probe; unexpected transport failure remains an operation
        error that recovery tests must prove is discarded and reconnected.
        """
        return self._closed

    def close(self) -> None:
        """Close the retained raw connection and record successful local cleanup.

        The state flips only after the raw close returns successfully. A close
        failure therefore remains visible and cannot be misrepresented as a
        released session authority; transport-failure recovery is still a later
        candidate acceptance gate.
        """
        self._connection.close()
        self._closed = True

    def __enter__(self) -> Pg8000CandidateConnectionAdapter:
        """Enter the package transaction context without a driver-only extension.

        The anti-corruption layer owns the existing pg-llm-batch connection
        context contract: successful exit commits, exceptional exit rolls back,
        and both paths close the physical connection. Entry itself must not open a
        second session or mutate transaction policy.
        """
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool | None:
        """Commit or roll back, close, and preserve the highest-priority failure.

        pg8000's public DB-API contract documents ``commit``, ``rollback``, and
        ``close`` but does not require a connection context-manager extension.
        Owning the package policy here removes that undocumented dependency while
        retaining the transaction semantics required by candidate admission. A
        commit or rollback failure remains primary over both an application error
        and later cleanup failure. If rollback succeeds, the application error
        remains primary over a later close failure. A close-only failure still
        propagates on an otherwise successful exit.
        """
        transaction_error: BaseException | None = None
        try:
            if exc_type is None:
                self.commit()
            else:
                self.rollback()
        except BaseException as error:
            transaction_error = error

        try:
            self.close()
        except BaseException:
            if transaction_error is not None:
                raise transaction_error from None
            if exc is not None:
                raise exc from None
            raise

        if transaction_error is not None:
            raise transaction_error
        return False
