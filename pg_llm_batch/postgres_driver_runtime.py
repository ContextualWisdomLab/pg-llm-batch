"""Runtime selection for the admitted PostgreSQL driver implementation.

Concrete database-client authority belongs at one infrastructure boundary.
Bounded contexts consume only :class:`PostgresDriverPort`; this module lazily
constructs the exact admitted pg8000 adapter while preserving explicit driver
injection for tests and alternate infrastructure wiring.
"""

from __future__ import annotations

from importlib import import_module

from .postgres_driver_port import PostgresDriverPort


class PostgresDriverUnavailableError(RuntimeError):
    """Report that the admitted PostgreSQL client cannot be constructed.

    The fixed diagnostic deliberately omits import paths, environment details,
    DSNs, credentials, distribution metadata, and package-selection details.
    Unexpected package defects remain distinguishable from ordinary admitted
    driver absence.
    """


def retained_postgres_driver() -> PostgresDriverPort:
    """Return the single admitted concrete driver behind the neutral port.

    The production construction boundary verifies the exact pg8000 distribution
    version and import origin before package code executes. Importing that
    boundary through :mod:`importlib` preserves genuinely lazy construction and
    lets tests replace the construction module without a package-level cached
    attribute becoming a second authority.
    """
    pg8000_driver_adapter = import_module("pg_llm_batch.pg8000_driver_adapter")

    try:
        return pg8000_driver_adapter.load_pg8000_driver()
    except pg8000_driver_adapter.Pg8000DriverUnavailableError:
        raise PostgresDriverUnavailableError(
            "PostgreSQL driver is unavailable"
        ) from None
