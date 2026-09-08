"""Production-loader contract for the admitted pg8000 PostgreSQL driver."""

from __future__ import annotations

from importlib.metadata import PackageNotFoundError
from types import ModuleType

import pytest

import pg_llm_batch.pg8000_driver_adapter as pg8000_driver_adapter
from pg_llm_batch.pg8000_driver_adapter import (
    PG8000_ADMITTED_VERSION,
    Pg8000DriverAdapter,
    Pg8000DriverUnavailableError,
    load_pg8000_driver,
)


def _dbapi_module() -> ModuleType:
    module = ModuleType("pg8000.dbapi")
    module.apilevel = "2.0"
    module.paramstyle = "format"
    module.threadsafety = 1
    module.connect = lambda **kwargs: object()
    return module


def test_loader_accepts_only_exact_admitted_distribution(monkeypatch) -> None:
    imported: list[str] = []
    module = _dbapi_module()
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "distribution_version",
        lambda package: PG8000_ADMITTED_VERSION,
    )
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "import_module",
        lambda name: imported.append(name) or module,
    )

    driver = load_pg8000_driver()

    assert isinstance(driver, Pg8000DriverAdapter)
    assert imported == ["pg8000.dbapi"]


def test_loader_rejects_unadmitted_version_before_import(monkeypatch) -> None:
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "distribution_version",
        lambda package: "1.31.4",
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
    def missing_distribution(package: str) -> str:
        raise PackageNotFoundError(package)

    monkeypatch.setattr(
        pg8000_driver_adapter,
        "distribution_version",
        missing_distribution,
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
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "distribution_version",
        lambda package: PG8000_ADMITTED_VERSION,
    )

    def missing_module(name: str) -> ModuleType:
        raise ModuleNotFoundError("pg8000 missing", name="pg8000.dbapi")

    monkeypatch.setattr(pg8000_driver_adapter, "import_module", missing_module)

    with pytest.raises(
        Pg8000DriverUnavailableError,
        match="^PostgreSQL driver is unavailable$",
    ):
        load_pg8000_driver()


def test_loader_preserves_unrelated_import_failure(monkeypatch) -> None:
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "distribution_version",
        lambda package: PG8000_ADMITTED_VERSION,
    )

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
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "distribution_version",
        lambda package: PG8000_ADMITTED_VERSION,
    )
    monkeypatch.setattr(pg8000_driver_adapter, "import_module", lambda name: module)

    driver = load_pg8000_driver(service_file=service_file)

    assert driver.parse_conninfo("service=runtime") == {
        "user": "service_user",
        "host": "db.internal",
        "port": "5433",
        "dbname": "batch",
    }
