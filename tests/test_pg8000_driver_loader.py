"""Production-loader contract for the admitted pg8000 PostgreSQL driver."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import pg_llm_batch.pg8000_driver_adapter as pg8000_driver_adapter
from pg_llm_batch.pg8000_driver_adapter import (
    PG8000_ADMITTED_VERSION,
    Pg8000DriverAdapter,
    Pg8000DriverUnavailableError,
    load_pg8000_driver,
)


_ADMITTED_PACKAGE_ROOT = Path("/opt/admitted/site-packages/pg8000")


class _AdmittedDistribution:
    """Expose one admitted version and package path from the same metadata snapshot."""

    version = PG8000_ADMITTED_VERSION

    def locate_file(self, path: str) -> Path:
        """Resolve the package directory without importing candidate code."""
        assert str(path) == "pg8000"
        return _ADMITTED_PACKAGE_ROOT


class _MismatchedDistribution(_AdmittedDistribution):
    """Expose origin metadata from a distribution with an unadmitted version."""

    version = "1.31.4"


def _dbapi_module() -> ModuleType:
    module = ModuleType("pg8000.dbapi")
    module.__file__ = str(_ADMITTED_PACKAGE_ROOT / "dbapi.py")
    module.apilevel = "2.0"
    module.paramstyle = "format"
    module.threadsafety = 1
    module.connect = lambda **kwargs: object()
    return module


def _install_admitted_distribution_metadata(monkeypatch) -> None:
    """Model one exact installed distribution and its matching import origin."""
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "distribution",
        lambda package: _AdmittedDistribution(),
        raising=False,
    )
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "find_spec",
        lambda name: SimpleNamespace(
            origin=str(_ADMITTED_PACKAGE_ROOT / "__init__.py"),
            submodule_search_locations=[str(_ADMITTED_PACKAGE_ROOT)],
        ),
        raising=False,
    )


def test_loader_accepts_only_exact_admitted_distribution(monkeypatch) -> None:
    imported: list[str] = []
    module = _dbapi_module()
    _install_admitted_distribution_metadata(monkeypatch)
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "import_module",
        lambda name: imported.append(name) or module,
    )

    driver = load_pg8000_driver()

    assert isinstance(driver, Pg8000DriverAdapter)
    assert imported == ["pg8000.dbapi"]


def test_loader_rejects_split_version_and_origin_metadata_before_import(monkeypatch) -> None:
    """Version and import-origin admission must describe the same distribution snapshot."""
    _install_admitted_distribution_metadata(monkeypatch)
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "distribution_version",
        lambda package: PG8000_ADMITTED_VERSION,
        raising=False,
    )
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "distribution",
        lambda package: _MismatchedDistribution(),
        raising=False,
    )
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "import_module",
        lambda name: pytest.fail("mismatched distribution code must not execute"),
    )

    with pytest.raises(
        Pg8000DriverUnavailableError,
        match="^PostgreSQL driver version is not admitted$",
    ):
        load_pg8000_driver()


def test_loader_rejects_shadow_package_before_import(monkeypatch) -> None:
    """A matching distribution version must not authorize shadow package bytes."""
    _install_admitted_distribution_metadata(monkeypatch)
    shadow_root = Path("/tmp/untrusted-site-packages/pg8000")
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "find_spec",
        lambda name: SimpleNamespace(
            origin=str(shadow_root / "__init__.py"),
            submodule_search_locations=[str(shadow_root)],
        ),
        raising=False,
    )
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "import_module",
        lambda name: pytest.fail("shadow package code must not execute"),
    )

    with pytest.raises(
        Pg8000DriverUnavailableError,
        match="^PostgreSQL driver origin is not admitted$",
    ):
        load_pg8000_driver()


def test_loader_rejects_imported_dbapi_outside_admitted_distribution(monkeypatch) -> None:
    """The module actually handed to the adapter must come from the admitted root."""
    _install_admitted_distribution_metadata(monkeypatch)
    module = _dbapi_module()
    module.__file__ = "/tmp/untrusted-site-packages/pg8000/dbapi.py"
    monkeypatch.setattr(pg8000_driver_adapter, "import_module", lambda name: module)

    with pytest.raises(
        Pg8000DriverUnavailableError,
        match="^PostgreSQL driver origin is not admitted$",
    ):
        load_pg8000_driver()


def test_loader_rejects_imported_dbapi_without_origin_metadata(monkeypatch) -> None:
    """Missing module-file metadata cannot satisfy installed-artifact authority."""
    _install_admitted_distribution_metadata(monkeypatch)
    module = _dbapi_module()
    del module.__file__
    monkeypatch.setattr(pg8000_driver_adapter, "import_module", lambda name: module)

    with pytest.raises(
        Pg8000DriverUnavailableError,
        match="^PostgreSQL driver origin is not admitted$",
    ):
        load_pg8000_driver()


def test_loader_rejects_missing_package_spec_before_import(monkeypatch) -> None:
    """Missing import authority must fail closed before candidate code executes."""
    _install_admitted_distribution_metadata(monkeypatch)
    monkeypatch.setattr(pg8000_driver_adapter, "find_spec", lambda name: None, raising=False)
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "import_module",
        lambda name: pytest.fail("unresolved package code must not execute"),
    )

    with pytest.raises(
        Pg8000DriverUnavailableError,
        match="^PostgreSQL driver origin is not admitted$",
    ):
        load_pg8000_driver()


def test_loader_rejects_unadmitted_version_before_import(monkeypatch) -> None:
    """Reject a distribution whose own version metadata is outside admission."""
    _install_admitted_distribution_metadata(monkeypatch)
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "distribution",
        lambda package: _MismatchedDistribution(),
        raising=False,
    )
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "import_module",
        lambda name: pytest.fail("unadmitted artifacts must not be imported"),
    )

    with pytest.raises(
        Pg8000DriverUnavailableError,
        match="^PostgreSQL driver version is not admitted$",
    ):
        load_pg8000_driver()


def test_loader_normalizes_missing_distribution_without_import(monkeypatch) -> None:
    def missing_distribution(package: str):
        raise PackageNotFoundError(package)

    monkeypatch.setattr(
        pg8000_driver_adapter,
        "distribution",
        missing_distribution,
        raising=False,
    )
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "import_module",
        lambda name: pytest.fail("missing distributions must not be imported"),
    )

    with pytest.raises(
        Pg8000DriverUnavailableError,
        match="^PostgreSQL driver is unavailable$",
    ):
        load_pg8000_driver()


def test_loader_normalizes_distribution_disappearing_before_origin_check(monkeypatch) -> None:
    """Metadata unavailability stays content-free before candidate import."""
    _install_admitted_distribution_metadata(monkeypatch)

    def missing_distribution(package: str):
        raise PackageNotFoundError(package)

    monkeypatch.setattr(
        pg8000_driver_adapter,
        "distribution",
        missing_distribution,
        raising=False,
    )
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "import_module",
        lambda name: pytest.fail("missing distributions must not be imported"),
    )

    with pytest.raises(
        Pg8000DriverUnavailableError,
        match="^PostgreSQL driver is unavailable$",
    ):
        load_pg8000_driver()


def test_loader_normalizes_missing_pg8000_module(monkeypatch) -> None:
    _install_admitted_distribution_metadata(monkeypatch)

    def missing_module(name: str) -> ModuleType:
        raise ModuleNotFoundError("pg8000 missing", name="pg8000.dbapi")

    monkeypatch.setattr(pg8000_driver_adapter, "import_module", missing_module)

    with pytest.raises(
        Pg8000DriverUnavailableError,
        match="^PostgreSQL driver is unavailable$",
    ):
        load_pg8000_driver()


def test_loader_preserves_unrelated_import_failure(monkeypatch) -> None:
    _install_admitted_distribution_metadata(monkeypatch)

    def broken_dependency(name: str) -> ModuleType:
        raise ModuleNotFoundError("dependency missing", name="scramp")

    monkeypatch.setattr(pg8000_driver_adapter, "import_module", broken_dependency)

    with pytest.raises(ModuleNotFoundError, match="dependency missing"):
        load_pg8000_driver()


def test_loader_composes_only_explicit_service_file(monkeypatch, tmp_path) -> None:
    module = _dbapi_module()
    service_file = tmp_path / "pg_service.conf"
    service_file.write_text(
        "[runtime]\nuser=service_user\nhost=db.internal\nport=5433\ndbname=batch\n",
        encoding="utf-8",
    )
    _install_admitted_distribution_metadata(monkeypatch)
    monkeypatch.setattr(pg8000_driver_adapter, "import_module", lambda name: module)

    driver = load_pg8000_driver(service_file=service_file)

    assert driver.parse_conninfo("service=runtime") == {
        "user": "service_user",
        "host": "db.internal",
        "port": "5433",
        "dbname": "batch",
    }
