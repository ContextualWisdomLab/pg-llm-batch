"""Origin-resolution failure regressions for the admitted pg8000 loader."""

from __future__ import annotations

from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

import pg_llm_batch.pg8000_driver_adapter as pg8000_driver_adapter
from pg_llm_batch.pg8000_driver_adapter import (
    PG8000_ADMITTED_VERSION,
    Pg8000DriverUnavailableError,
    load_pg8000_driver,
)


_ADMITTED_PACKAGE_ROOT = Path("/opt/admitted/site-packages/pg8000")


class _AdmittedDistribution:
    """Expose one admitted version and package path from one metadata snapshot."""

    version = PG8000_ADMITTED_VERSION

    def locate_file(self, path: str) -> Path:
        """Return the package directory selected by installed metadata."""
        assert str(path) == "pg8000"
        return _ADMITTED_PACKAGE_ROOT


def _dbapi_module() -> ModuleType:
    """Return one structurally valid DB-API module at the admitted path."""
    module = ModuleType("pg8000.dbapi")
    module.__file__ = str(_ADMITTED_PACKAGE_ROOT / "dbapi.py")
    module.apilevel = "2.0"
    module.paramstyle = "format"
    module.threadsafety = 1
    module.connect = lambda **kwargs: object()
    return module


def _install_metadata(monkeypatch: pytest.MonkeyPatch, module: ModuleType) -> None:
    """Install one internally consistent distribution/spec/import fixture."""
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "distribution",
        lambda package: _AdmittedDistribution(),
    )
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "find_spec",
        lambda name: SimpleNamespace(
            origin=str(_ADMITTED_PACKAGE_ROOT / "__init__.py"),
            submodule_search_locations=[str(_ADMITTED_PACKAGE_ROOT)],
        ),
    )
    monkeypatch.setattr(pg8000_driver_adapter, "import_module", lambda name: module)


def test_loader_normalizes_installed_root_resolution_failure_before_import(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Filesystem lookup failures must not escape the content-free origin boundary."""
    module = _dbapi_module()
    _install_metadata(monkeypatch, module)

    real_path = Path

    class _RootResolutionFailure:
        def __init__(self, value: object) -> None:
            self._value = value

        def resolve(self) -> Path:
            if str(self._value) == str(_ADMITTED_PACKAGE_ROOT):
                raise OSError("sensitive installed-root lookup detail")
            return real_path(self._value).resolve()

    monkeypatch.setattr(pg8000_driver_adapter, "Path", _RootResolutionFailure)
    monkeypatch.setattr(
        pg8000_driver_adapter,
        "import_module",
        lambda name: pytest.fail("origin lookup failure must block candidate import"),
    )

    with pytest.raises(
        Pg8000DriverUnavailableError,
        match="^PostgreSQL driver origin is not admitted$",
    ):
        load_pg8000_driver()


def test_loader_normalizes_returned_module_origin_resolution_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Returned-module path lookup failures must stay inside the origin boundary."""
    module = _dbapi_module()
    _install_metadata(monkeypatch, module)

    real_path = Path

    class _DbapiResolutionFailure:
        def __init__(self, value: object) -> None:
            self._value = value

        def resolve(self) -> Path:
            if str(self._value).endswith("/pg8000/dbapi.py"):
                raise OSError("sensitive dbapi-origin lookup detail")
            return real_path(self._value).resolve()

    monkeypatch.setattr(pg8000_driver_adapter, "Path", _DbapiResolutionFailure)

    with pytest.raises(
        Pg8000DriverUnavailableError,
        match="^PostgreSQL driver origin is not admitted$",
    ):
        load_pg8000_driver()
