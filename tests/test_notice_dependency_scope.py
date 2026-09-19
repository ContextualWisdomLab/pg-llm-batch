# SPDX-License-Identifier: Apache-2.0
"""Keep packaged third-party notices aligned with dependency scope."""

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10 compatibility
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]


def _dependency_names(requirements: list[str]) -> set[str]:
    """Return normalized distribution names from simple PEP 508 requirements."""
    return {
        requirement.split("[", 1)[0]
        .split(";", 1)[0]
        .split("==", 1)[0]
        .split(">=", 1)[0]
        .strip()
        .lower()
        for requirement in requirements
    }


def test_notice_matches_default_and_optional_postgres_driver_scopes() -> None:
    """Prevent an optional legacy adapter from replacing the runtime driver notice."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    notice = (ROOT / "NOTICE").read_text(encoding="utf-8")

    runtime_names = _dependency_names(project["project"]["dependencies"])
    optional_requirements = [
        requirement
        for requirements in project["project"]["optional-dependencies"].values()
        for requirement in requirements
    ]
    optional_names = _dependency_names(optional_requirements)

    assert "pg8000" in runtime_names
    assert "psycopg" not in runtime_names
    assert "psycopg" in optional_names
    assert "pg8000 1.31.5" in notice
    assert "BSD-3-Clause" in notice
    assert "psycopg 3.3.4" in notice
    assert "optional test/development" in notice
