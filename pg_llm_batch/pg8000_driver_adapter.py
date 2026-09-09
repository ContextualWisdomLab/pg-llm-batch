"""Production construction boundary for the admitted pg8000 PostgreSQL driver.

The underlying pg8000 semantics were proved incrementally behind candidate-only
adapters before production selection. This module accepts only the exact admitted
distribution, verifies that the importable package resolves to that distribution,
imports its DB-API module lazily, verifies that the returned module is rooted in
the same admitted distribution, and optionally composes the explicit service-file
resolver. The centralized runtime selector constructs this adapter; release
authority still requires the matching manifest, lock, package, SBOM, provenance,
and protected-head acceptance evidence.
"""

from __future__ import annotations

from importlib import import_module
from importlib.metadata import Distribution, PackageNotFoundError, distribution
from importlib.util import find_spec
from pathlib import Path
from types import ModuleType

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


def _resolve_origin_path(value: str | Path) -> Path:
    """Resolve one origin path without exposing filesystem lookup diagnostics."""
    try:
        return Path(value).resolve()
    except (OSError, RuntimeError, ValueError):
        raise Pg8000DriverUnavailableError(
            "PostgreSQL driver origin is not admitted"
        ) from None


def _require_admitted_pg8000_origin(installed_distribution: Distribution) -> Path:
    """Reject package-path shadowing and return the admitted package root."""
    expected_root = _resolve_origin_path(
        Path(installed_distribution.locate_file("pg8000"))
    )
    package_spec = find_spec("pg8000")
    if (
        package_spec is None
        or package_spec.origin is None
        or package_spec.submodule_search_locations is None
    ):
        raise Pg8000DriverUnavailableError(
            "PostgreSQL driver origin is not admitted"
        )

    observed_origin = _resolve_origin_path(package_spec.origin)
    observed_roots = tuple(
        _resolve_origin_path(location)
        for location in package_spec.submodule_search_locations
    )
    if (
        observed_origin != expected_root / "__init__.py"
        or observed_roots != (expected_root,)
    ):
        raise Pg8000DriverUnavailableError(
            "PostgreSQL driver origin is not admitted"
        )
    return expected_root


def _require_admitted_pg8000_dbapi_origin(
    dbapi_module: ModuleType,
    expected_root: Path,
) -> None:
    """Reject a returned DB-API module outside the admitted distribution root."""
    module_file = vars(dbapi_module).get("__file__")
    if type(module_file) is not str:
        raise Pg8000DriverUnavailableError(
            "PostgreSQL driver origin is not admitted"
        )
    if _resolve_origin_path(module_file) != expected_root / "dbapi.py":
        raise Pg8000DriverUnavailableError(
            "PostgreSQL driver origin is not admitted"
        )


def load_pg8000_driver(*, service_file: Path | None = None) -> PostgresDriverPort:
    """Construct only the exact admitted pg8000 artifact behind the canonical port.

    One installed-distribution metadata snapshot supplies both version admission
    and the package root used for import-origin admission. The package root is
    checked before import, and the DB-API module returned by Python's import
    machinery must then report a source path under that same admitted root before
    it receives connection authority. Filesystem resolution failures remain
    inside the same content-free origin-admission boundary. This rejects a stale
    or preloaded ``pg8000.dbapi`` module from a different filesystem location
    while avoiding a second distribution-metadata lookup. Service-file support
    is opt-in through one caller-selected path; ambient ``PGSERVICEFILE``
    discovery remains outside the admitted contract.

    Args:
        service_file: Optional explicit ``pg_service.conf`` path. When omitted,
            ``service=`` selectors remain fail closed.

    Returns:
        A canonical PostgreSQL driver port backed by exact pg8000 1.31.5.

    Raises:
        Pg8000DriverUnavailableError: If pg8000 is absent, its version, package
            origin, or returned DB-API module origin is not admitted, or its
            DB-API module is absent.
        ModuleNotFoundError: If importing pg8000 exposes an unrelated missing
            dependency, preserving the packaging defect for root-cause repair.
    """
    try:
        installed_distribution = distribution("pg8000")
    except PackageNotFoundError:
        raise Pg8000DriverUnavailableError("PostgreSQL driver is unavailable") from None

    if installed_distribution.version != PG8000_ADMITTED_VERSION:
        raise Pg8000DriverUnavailableError(
            "PostgreSQL driver version is not admitted"
        )

    expected_root = _require_admitted_pg8000_origin(installed_distribution)

    try:
        dbapi_module = import_module("pg8000.dbapi")
    except ModuleNotFoundError as exc:
        if exc.name not in {"pg8000", "pg8000.dbapi"}:
            raise
        raise Pg8000DriverUnavailableError("PostgreSQL driver is unavailable") from None

    _require_admitted_pg8000_dbapi_origin(dbapi_module, expected_root)

    service_resolver = (
        None
        if service_file is None
        else Pg8000CandidateServiceFileResolver(service_file)
    )
    return Pg8000DriverAdapter(
        dbapi_module,
        service_resolver=service_resolver,
    )
