# SPDX-License-Identifier: Apache-2.0
"""Contract tests for the first-class OpenTelemetry optional dependency."""

from __future__ import annotations

from pathlib import Path

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - Python 3.10
    import tomli as tomllib


ROOT = Path(__file__).resolve().parents[1]
OBSERVABILITY_API_REQUIREMENT = "opentelemetry-api>=1.44,<2"


def _project_metadata() -> dict[str, object]:
    """Load the package metadata used by build and installation tooling."""
    return tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))[
        "project"
    ]


def test_observability_extra_declares_api_only_dependency() -> None:
    """Package metadata exposes bounded API-only OpenTelemetry installation."""
    project = _project_metadata()
    extras = project["optional-dependencies"]

    assert extras["observability"] == [OBSERVABILITY_API_REQUIREMENT]
    assert not any(
        requirement.startswith("opentelemetry-sdk")
        for requirement in extras["observability"]
    )


def test_base_runtime_remains_opentelemetry_independent() -> None:
    """The default install must not silently acquire telemetry dependencies."""
    project = _project_metadata()
    dependencies = project["dependencies"]

    assert not any(
        requirement.startswith("opentelemetry-") for requirement in dependencies
    )


def test_observability_extra_has_one_explicit_runtime_requirement() -> None:
    """Keep the optional installation surface minimal and reviewable."""
    project = _project_metadata()
    extras = project["optional-dependencies"]

    assert set(extras) >= {"observability", "secrets", "test"}
    assert len(extras["observability"]) == 1
