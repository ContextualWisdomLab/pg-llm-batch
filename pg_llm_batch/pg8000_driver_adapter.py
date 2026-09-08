"""Production construction boundary for the admitted pg8000 PostgreSQL driver.

The underlying pg8000 semantics were proved incrementally behind candidate-only
adapters before production selection. This module adds the missing construction
boundary: it accepts only the exact admitted distribution, imports its DB-API
module lazily, and optionally composes the existing explicit service-file
resolver. It does not change the repository's default runtime selector or
manifest; those remain a separate atomic promotion with lock/SBOM evidence.
"""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import PackageNotFoundError, version as distribution_version
from pathlib import Path

from .pg8000_candidate_driver_port import Pg8000CandidateDriverAdapter
from .pg8000_candidate_service_file import Pg8000CandidateServiceFileResolver
from .postgres_driver_port import PostgresDriverPort


PG8000_ADMITTED_VERSION = "1.31.5"


class Pg8000DriverUnavailableError(RuntimeError):
    """Report that the exact admitted PostgreSQL driver cannot be constructed.

    Diagnostics intentionally omit import paths, package metadata, selectors,
    and credentials. Missing unrelated transitive imports are re-raised so a
    broken product environment is not misclassified as ordinary driver absence.
    """


class Pg8000DriverAdapter(Pg8000CandidateDriverAdapter):
    """Expose the fully proved pg8000 port semantics under the production name.

    The implementation deliberately inherits the already exercised cursor,
    connection, selector, JSONB, SQLSTATE, and thread-affinity behavior instead
    of copying that logic into a second concrete-driver authority.
    """


def load_pg8000_driver(*, service_file: Path | None = None) -> PostgresDriverPort:
    """Construct only the exact admitted pg8000 artifact behind the canonical port.

    Distribution identity is checked before import so an unreviewed installed
    version never executes as database-client authority. Service-file support is
    opt-in through one caller-selected path; ambient ``PGSERVICEFILE`` discovery
    remains outside the admitted contract.

    Args:
        service_file: Optional explicit ``pg_service.conf`` path. When omitted,
            ``service=`` selectors remain fail closed.

    Returns:
        A canonical PostgreSQL driver port backed by exact pg8000 1.31.5.

    Raises:
        Pg8000DriverUnavailableError: If pg8000 is absent, its DB-API module is
            absent, or the installed distribution is not the admitted version.
        ModuleNotFoundError: If importing pg8000 exposes an unrelated missing
            dependency, preserving the packaging defect for root-cause repair.
    """
    try:
        installed_version = distribution_version("pg8000")
    except PackageNotFoundError:
        raise Pg8000DriverUnavailableError("PostgreSQL driver is unavailable") from None

    if installed_version != PG8000_ADMITTED_VERSION:
        raise Pg8000DriverUnavailableError(
            "PostgreSQL driver version is not admitted"
        )

    try:
        dbapi_module = import_module("pg8000.dbapi")
    except ModuleNotFoundError as exc:
        if exc.name not in {"pg8000", "pg8000.dbapi"}:
            raise
        raise Pg8000DriverUnavailableError("PostgreSQL driver is unavailable") from None

    service_resolver = (
        None
        if service_file is None
        else Pg8000CandidateServiceFileResolver(service_file)
    )
    return Pg8000DriverAdapter(
        dbapi_module,
        service_resolver=service_resolver,
    )
