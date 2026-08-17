# SPDX-License-Identifier: Apache-2.0
"""Contract tests for advertised and permanently tested CPython support."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _ROOT / "pyproject.toml"
_CI_WORKFLOW = _ROOT / ".github" / "workflows" / "ci.yml"
_BOUNDED_REQUIRES_PYTHON = re.compile(
    r">=(?P<lower_major>\d+)\.(?P<lower_minor>\d+),<(?P<upper_major>\d+)\.(?P<upper_minor>\d+)\Z"
)
_MATRIX_RE = re.compile(r'python-version:\s*\[(?P<versions>[^\]]+)\]')
_VERSION_RE = re.compile(r'"(?P<major>\d+)\.(?P<minor>\d+)"')


def _advertised_minor_versions() -> tuple[str, ...]:
    """Derive every CPython minor advertised by the bounded package metadata."""
    project = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]
    requires_python = project["requires-python"]
    assert isinstance(requires_python, str)
    matched = _BOUNDED_REQUIRES_PYTHON.fullmatch(requires_python)
    assert matched is not None, "Requires-Python must have explicit lower and upper minor bounds"
    lower_major = int(matched.group("lower_major"))
    lower_minor = int(matched.group("lower_minor"))
    upper_major = int(matched.group("upper_major"))
    upper_minor = int(matched.group("upper_minor"))
    assert lower_major == upper_major == 3
    assert upper_minor > lower_minor
    return tuple(f"3.{minor}" for minor in range(lower_minor, upper_minor))


def _permanent_ci_minor_versions() -> tuple[str, ...]:
    """Return the explicit CPython unit-test matrix from the permanent CI workflow."""
    workflow = _CI_WORKFLOW.read_text(encoding="utf-8")
    matched = _MATRIX_RE.search(workflow)
    assert matched is not None, "CI must declare an explicit Python minor matrix"
    return tuple(
        f"{version.group('major')}.{version.group('minor')}"
        for version in _VERSION_RE.finditer(matched.group("versions"))
    )


def test_requires_python_matches_every_permanent_ci_minor() -> None:
    """Every installer-advertised CPython minor must have a permanent unit-test lane."""
    assert _advertised_minor_versions() == (
        "3.10",
        "3.11",
        "3.12",
        "3.13",
        "3.14",
    )
    assert _permanent_ci_minor_versions() == _advertised_minor_versions()
