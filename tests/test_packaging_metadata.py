# SPDX-License-Identifier: Apache-2.0
"""Contract tests for standardized package licensing metadata."""

from __future__ import annotations

from importlib.metadata import metadata
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_pyproject_uses_pep639_license_metadata() -> None:
    """Source metadata uses a bounded backend and PEP 639 legal-file fields."""
    project = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert 'requires = ["uv_build>=0.11.32,<0.12"]' in project
    assert 'build-backend = "uv_build"' in project
    assert 'module-root = ""' in project
    assert 'license = "Apache-2.0"' in project
    assert 'license-files = ["LICENSE", "NOTICE"]' in project
    assert "license = {" not in project
    assert "License ::" not in project


def test_component_image_copies_pep639_legal_files_before_build() -> None:
    """The component builder receives every legal file required by metadata."""
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")
    assert "COPY pyproject.toml uv.lock README.md LICENSE NOTICE ./" in dockerfile


def test_installed_distribution_exposes_normalized_license_metadata() -> None:
    """Installed metadata exposes the SPDX expression and both legal files."""
    package_metadata = metadata("pg-llm-batch")
    assert package_metadata["License-Expression"] == "Apache-2.0"
    assert set(package_metadata.get_all("License-File") or ()) == {
        "LICENSE",
        "NOTICE",
    }
    assert package_metadata.get("License") is None
