"""Provider-neutral PostgreSQL driver contracts for runtime decoupling.

The package currently has direct Psycopg coupling at several infrastructure
boundaries. These abstract ports describe the database capabilities those
callers actually need without choosing a concrete PostgreSQL driver. Concrete
adapters remain infrastructure concerns and must preserve parameterized SQL,
transaction semantics, connection-string handling, JSONB adaptation, and
PostgreSQL error classification.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Mapping


class PostgresCursorPort(ABC):
    """Describe the synchronous cursor surface used by pg-llm-batch.

    Implementations must preserve parameter binding rather than interpolating
    SQL text themselves. Materialized result rows use positional tuples as the
    canonical package representation because existing bounded contexts use tuple
    indexing and equality. A concrete driver returning another row container must
    normalize it inside its adapter before exposing it through this port.
    """

    @abstractmethod
    def execute(
        self,
        query: str,
        params: object | None = None,
    ) -> PostgresCursorPort:
        """Execute one parameterized PostgreSQL operation and retain the cursor.

        ``query`` is package-authored SQL and ``params`` carries bound values.
        Implementations must not downgrade this call into string formatting or
        another transport that changes PostgreSQL parameter semantics.
        """

    @abstractmethod
    def executemany(self, query: str, params_seq: object) -> PostgresCursorPort:
        """Execute one package-authored operation for a parameter sequence.

        Concrete adapters are responsible for preserving the driver's normal
        transactional behavior and must not silently commit between entries.
        """

    @abstractmethod
    def fetchone(self) -> tuple[object, ...] | None:
        """Return one canonical tuple row, or ``None`` when no row remains.

        The adapter owns only the row-container normalization. The consuming
        bounded context remains responsible for validating field count, primitive
        types, and semantic meaning before database evidence becomes trusted.
        """

    @abstractmethod
    def fetchmany(self, size: int) -> list[tuple[object, ...]]:
        """Return at most ``size`` canonical tuple rows.

        Bounded contexts use this operation when an explicit row budget is part
        of the product contract; adapters must preserve that finite request and
        fail closed rather than silently dropping malformed materialized rows.
        """

    @abstractmethod
    def fetchall(self) -> list[tuple[object, ...]]:
        """Return canonical tuple rows for an already bounded result set.

        This method exists for compatibility with current package code. New
        untrusted-result paths should prefer a bounded query and ``fetchmany``.
        """

    @abstractmethod
    def row_count(self) -> int | None:
        """Return an exact affected-row count or ``None`` when it is unknown.

        Existing persistence paths use the count to detect missing updates and
        partial batch membership writes. Concrete adapters must normalize native
        unknown sentinels at this boundary so consumers never mistake a
        driver-specific integer such as ``-1`` for exact success evidence.
        """

    @abstractmethod
    def __enter__(self) -> PostgresCursorPort:
        """Enter the cursor context without changing transaction ownership.

        Connection-level transaction semantics remain owned by the surrounding
        connection port rather than being hidden in cursor entry.
        """

    @abstractmethod
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool | None:
        """Leave the cursor context and release adapter-owned cursor resources.

        Returning a truthy value may suppress an exception, so concrete
        adapters should preserve their underlying driver's normal behavior.
        """


class PostgresConnectionPort(ABC):
    """Describe the synchronous PostgreSQL connection capability the package uses.

    The port deliberately keeps transaction mode and closed-state inspection
    explicit because current token-counting, configuration, and batch assembly
    paths depend on those semantics. A replacement driver must not weaken RLS,
    replay, or recovery behavior by hiding them behind an opaque wrapper.
    """

    @abstractmethod
    def cursor(self) -> PostgresCursorPort:
        """Create a cursor bound to this connection's current transaction.

        The returned cursor must implement ``PostgresCursorPort`` semantics and
        must not open a second implicit connection.
        """

    @abstractmethod
    def execute(
        self,
        query: str,
        params: object | None = None,
    ) -> PostgresCursorPort:
        """Execute one parameterized statement using this exact connection.

        This convenience operation must retain the same transaction and session
        state, including transaction-local tenant ``set_config`` values.
        """

    @abstractmethod
    def commit(self) -> None:
        """Commit the current local PostgreSQL transaction.

        A successful return means only that the concrete driver reported local
        transaction commit; it does not imply distributed exactly-once delivery.
        """

    @abstractmethod
    def rollback(self) -> None:
        """Roll back the current local PostgreSQL transaction.

        Adapters must preserve PostgreSQL rollback behavior and must not convert
        rollback failures into a successful application outcome.
        """

    @abstractmethod
    def set_autocommit(self, enabled: bool) -> None:
        """Select explicit connection autocommit behavior without attribute leakage.

        Existing runtime paths intentionally use both autocommit and explicit
        transactions. Concrete adapters translate this operation into their
        native API while preserving PostgreSQL transaction and session scope.
        """

    @abstractmethod
    def is_closed(self) -> bool:
        """Report whether this concrete connection can still execute work.

        Cached connection owners use this signal to reconnect deterministically
        instead of issuing work through a connection the driver has closed.
        """

    @abstractmethod
    def close(self) -> None:
        """Release the concrete database connection and its session authority.

        Implementations must not keep an implicit reusable connection alive
        after callers intentionally close this capability.
        """

    @abstractmethod
    def __enter__(self) -> PostgresConnectionPort:
        """Enter the connection context using the concrete driver's semantics.

        The adapter must preserve whether normal context exit commits or rolls
        back rather than inventing a different transaction policy.
        """

    @abstractmethod
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        traceback: object | None,
    ) -> bool | None:
        """Leave the connection context and preserve driver error propagation.

        Concrete adapters remain responsible for matching their documented
        commit, rollback, and cleanup behavior on normal and exceptional exit.
        """


class PostgresDriverPort(ABC):
    """Define the PostgreSQL-driver anti-corruption layer required by the package.

    This port owns no model discovery, provider routing, LLM credentials, or
    batch-provider selection. It exists solely to let pg-llm-batch replace a
    concrete PostgreSQL client while keeping its database and tenant contracts
    stable and testable.
    """

    @abstractmethod
    def connect(
        self,
        dsn: str,
        *,
        connect_timeout_seconds: int | None = None,
    ) -> PostgresConnectionPort:
        """Open one synchronous PostgreSQL connection for a validated DSN.

        The concrete adapter must honor the requested finite positive timeout in
        whole seconds when supplied and return a connection whose transaction and
        session behavior conforms to ``PostgresConnectionPort``.
        """

    @abstractmethod
    def parse_conninfo(self, dsn: str) -> Mapping[str, str]:
        """Parse a PostgreSQL connection selector without exposing credentials.

        The returned mapping is used only for deterministic policy decisions;
        callers remain responsible for rejecting credential-bearing selectors
        where their boundary requires a credential-free DSN.
        """

    @abstractmethod
    def make_conninfo(self, params: Mapping[str, str]) -> str:
        """Render validated PostgreSQL connection parameters safely.

        Concrete adapters must use their reviewed conninfo quoting rules rather
        than ad-hoc concatenation when values may contain PostgreSQL syntax.
        """

    @abstractmethod
    def jsonb(self, value: object) -> object:
        """Adapt one validated Python value for a PostgreSQL JSONB parameter.

        The adapter may return a driver-specific wrapper, but that wrapper must
        remain confined behind this infrastructure boundary and out of domain
        models and public package contracts.
        """

    @abstractmethod
    def is_invalid_conninfo(self, error: BaseException) -> bool:
        """Classify only a PostgreSQL connection-selector grammar failure.

        CLI and bootstrap boundaries need to normalize malformed DSN syntax
        without importing one concrete driver's exception type. Implementations
        must not broaden this category to connection, authentication, or runtime
        database failures.
        """

    @abstractmethod
    def is_undefined_function(self, error: BaseException) -> bool:
        """Classify the PostgreSQL undefined-function error without leaking it.

        Token-counting fallback logic needs this narrow database-error category;
        adapters must not broaden it to unrelated provider or application errors.
        """
