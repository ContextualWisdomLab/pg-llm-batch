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


def test_observability_extra_declares_api_only_dependency() -> None:
    """Package metadata exposes bounded API-only OpenTelemetry installation."""
    project = tomllib.loads((ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    extras = project["project"]["optional-dependencies"]

    assert extras["observability"] == [OBSERVABILITY_API_REQUIREMENT]
    assert not any(
        requirement.startswith("opentelemetry-sdk")
        for requirement in extras["observability"]
    )
