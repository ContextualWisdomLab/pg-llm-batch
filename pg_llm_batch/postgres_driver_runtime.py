"""Runtime selection for the retained PostgreSQL driver implementation.

Concrete database-client authority belongs at one infrastructure boundary while
pg-llm-batch migrates away from Psycopg. Bounded contexts consume only
:class:`PostgresDriverPort`; this module lazily constructs the retained adapter
until a commercially admitted replacement is ready. Keeping the import lazy
also preserves explicit driver injection for candidate and degraded-mode tests.
"""

from __future__ import annotations

from .postgres_driver_port import PostgresDriverPort


class PostgresDriverUnavailableError(RuntimeError):
    """Report that the retained PostgreSQL client cannot be constructed.

    The fixed diagnostic deliberately omits import paths, environment details,
    DSNs, and credentials. Import failures unrelated to Psycopg are re-raised so
    packaging defects are not misclassified as an optional-client absence.
    """


def retained_postgres_driver() -> PostgresDriverPort:
    """Return the currently retained concrete driver behind the neutral port.

    Psycopg remains a temporary migration baseline only. The import lives here
    so callers do not acquire a second concrete-driver dependency and the future
    production replacement can be switched at one reviewed runtime boundary.
    """
    try:
        from .psycopg_driver_adapter import PsycopgDriverAdapter
    except ModuleNotFoundError as exc:
        missing_name = exc.name or ""
        if missing_name != "psycopg" and not missing_name.startswith("psycopg."):
            raise
        raise PostgresDriverUnavailableError(
            "Retained PostgreSQL driver is unavailable"
        ) from None
    return PsycopgDriverAdapter()
