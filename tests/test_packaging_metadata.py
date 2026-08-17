# SPDX-License-Identifier: Apache-2.0
"""Contract tests for standardized package licensing metadata."""

from __future__ import annotations

from importlib.metadata import metadata
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_uses_pep639_license_metadata() -> None:
    """Source metadata exactly pins uv_build and includes PEP 639 legal files."""
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    exact_uv_build_pin = re.search(
        r'^requires = \["uv_build==\d+\.\d+\.\d+"\]$',
        project,
        flags=re.MULTILINE,
    )
    assert exact_uv_build_pin is not None
    assert 'requires = ["uv_build>=' not in project
    assert 'build-backend = "uv_build"' in project
    assert 'module-root = ""' in project
    assert 'license = "Apache-2.0"' in project
    assert 'license-files = ["LICENSE", "NOTICE"]' in project
    assert "license = {" not in project
    assert "License ::" not in project


def test_installed_distribution_exposes_normalized_license_metadata() -> None:
    """Installed metadata exposes the SPDX expression and both legal files."""
    package_metadata = metadata("pg-llm-batch")
    assert package_metadata["License-Expression"] == "Apache-2.0"
    assert set(package_metadata.get_all("License-File") or ()) == {
        "LICENSE",
        "NOTICE",
    }
    assert package_metadata.get("License") is None
