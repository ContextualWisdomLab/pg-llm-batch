# SPDX-License-Identifier: Apache-2.0
"""Contract tests for advertised and permanently tested CPython support."""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT = _ROOT / "pyproject.toml"
_CI_WORKFLOW = _ROOT / ".github" / "workflows" / "ci.yml"
_REQUIRES_PYTHON_RE = re.compile(
    r">=(?P<major>\d+)\.(?P<minor>\d+)\Z"
)
_MATRIX_RE = re.compile(r'python-version:\s*\[(?P<versions>[^\]]+)\]')
_VERSION_RE = re.compile(r'"(?P<major>\d+)\.(?P<minor>\d+)"')
_QUALITY_VERSION_RE = re.compile(r'python-version:\s*"(?P<major>\d+)\.(?P<minor>\d+)"')


def _advertised_lower_bound() -> tuple[int, int]:
    """Return the exact CPython lower bound advertised by project metadata."""
    project = tomllib.loads(_PYPROJECT.read_text(encoding="utf-8"))["project"]
    requires_python = project["requires-python"]
    assert isinstance(requires_python, str)
    matched = _REQUIRES_PYTHON_RE.fullmatch(requires_python)
    assert matched is not None, "Requires-Python must expose one explicit CPython lower bound"
    return int(matched.group("major")), int(matched.group("minor"))


def _permanent_ci_minor_versions() -> tuple[str, ...]:
    """Return the explicit CPython unit-test matrix from the permanent CI workflow."""
    workflow = _CI_WORKFLOW.read_text(encoding="utf-8")
    matched = _MATRIX_RE.search(workflow)
    assert matched is not None, "CI must declare an explicit Python minor matrix"
    return tuple(
        f"{version.group('major')}.{version.group('minor')}"
        for version in _VERSION_RE.finditer(matched.group("versions"))
    )


def _quality_gate_python_version() -> tuple[int, int]:
    """Return the CPython minor that runs coverage, docstring, and package gates."""
    workflow = _CI_WORKFLOW.read_text(encoding="utf-8")
    quality_section = workflow.split("  quality-gates:\n", 1)[1].split(
        "  container-builds:\n", 1
    )[0]
    matched = _QUALITY_VERSION_RE.search(quality_section)
    assert matched is not None, "quality gates must pin an explicit Python minor"
    return int(matched.group("major")), int(matched.group("minor"))


def test_requires_python_has_gapless_permanent_ci_evidence() -> None:
    """Every currently governed supported minor must have a permanent unit-test lane."""
    lower_major, lower_minor = _advertised_lower_bound()
    quality_major, quality_minor = _quality_gate_python_version()
    assert lower_major == quality_major == 3
    assert quality_minor >= lower_minor
    expected = tuple(
        f"{lower_major}.{minor}" for minor in range(lower_minor, quality_minor + 1)
    )
    assert expected == ("3.10", "3.11", "3.12", "3.13", "3.14")
    assert _permanent_ci_minor_versions() == expected
