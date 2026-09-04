"""Regression tests for immutable candidate-wheel license admission.

The pg8000 migration is intended to remove an LGPL-family production dependency.
Hash-pinning a candidate wheel closure proves artifact identity but does not prove
that every installed transitive dependency satisfies the repository's inbound
license policy. These tests keep that commercial-policy decision executable.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import zipfile

import pytest


_REPOSITORY_ROOT = Path(__file__).parents[1]
_TOOL_PATH = _REPOSITORY_ROOT / "tools" / "verify_candidate_wheel_licenses.py"


def _load_verifier():
    """Load the repository-owned verifier without turning tools into a package."""
    spec = importlib.util.spec_from_file_location("candidate_license_verifier", _TOOL_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("candidate license verifier could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_wheel(directory: Path, filename: str, *, name: str, version: str, license_lines: tuple[str, ...]) -> None:
    """Write the smallest synthetic wheel metadata fixture needed by the verifier."""
    metadata = [
        "Metadata-Version: 2.4",
        f"Name: {name}",
        f"Version: {version}",
        *license_lines,
        "",
    ]
    dist_info = filename.split("-", 1)[0].replace("-", "_")
    with zipfile.ZipFile(directory / filename, "w") as archive:
        archive.writestr(f"{dist_info}-{version}.dist-info/METADATA", "\n".join(metadata))


def _write_valid_closure(directory: Path) -> None:
    """Create license metadata matching the exact pg8000 candidate closure."""
    _write_wheel(
        directory,
        "pg8000-1.31.5-py3-none-any.whl",
        name="pg8000",
        version="1.31.5",
        license_lines=("License-Expression: BSD-3-Clause",),
    )
    _write_wheel(
        directory,
        "python_dateutil-2.9.0.post0-py2.py3-none-any.whl",
        name="python-dateutil",
        version="2.9.0.post0",
        license_lines=(
            "License: Dual License",
            "Classifier: License :: OSI Approved :: Apache Software License",
            "Classifier: License :: OSI Approved :: BSD License",
        ),
    )
    _write_wheel(
        directory,
        "scramp-1.4.17-py3-none-any.whl",
        name="scramp",
        version="1.4.17",
        license_lines=("License-Expression: MIT-0",),
    )
    _write_wheel(
        directory,
        "asn1crypto-1.5.1-py2.py3-none-any.whl",
        name="asn1crypto",
        version="1.5.1",
        license_lines=("License: MIT",),
    )
    _write_wheel(
        directory,
        "six-1.17.0-py2.py3-none-any.whl",
        name="six",
        version="1.17.0",
        license_lines=("License: MIT",),
    )


def test_exact_candidate_closure_requires_permissive_license_evidence(tmp_path: Path) -> None:
    verifier = _load_verifier()
    _write_valid_closure(tmp_path)

    verifier.verify_candidate_wheel_licenses(tmp_path)


def test_candidate_closure_rejects_gpl_family_metadata_even_with_permissive_marker(tmp_path: Path) -> None:
    verifier = _load_verifier()
    _write_valid_closure(tmp_path)
    wheel_path = tmp_path / "scramp-1.4.17-py3-none-any.whl"
    wheel_path.unlink()
    _write_wheel(
        tmp_path,
        wheel_path.name,
        name="scramp",
        version="1.4.17",
        license_lines=(
            "License-Expression: MIT-0",
            "Classifier: License :: OSI Approved :: GNU Lesser General Public License v3 (LGPLv3)",
        ),
    )

    with pytest.raises(verifier.CandidateWheelLicenseError, match="disallowed license"):
        verifier.verify_candidate_wheel_licenses(tmp_path)


def test_candidate_closure_rejects_missing_positive_license_evidence(tmp_path: Path) -> None:
    verifier = _load_verifier()
    _write_valid_closure(tmp_path)
    wheel_path = tmp_path / "six-1.17.0-py2.py3-none-any.whl"
    wheel_path.unlink()
    _write_wheel(
        tmp_path,
        wheel_path.name,
        name="six",
        version="1.17.0",
        license_lines=("License: UNKNOWN",),
    )

    with pytest.raises(verifier.CandidateWheelLicenseError, match="approved license evidence"):
        verifier.verify_candidate_wheel_licenses(tmp_path)


def test_candidate_closure_rejects_unexpected_wheel_set(tmp_path: Path) -> None:
    verifier = _load_verifier()
    _write_valid_closure(tmp_path)
    _write_wheel(
        tmp_path,
        "unexpected-1.0-py3-none-any.whl",
        name="unexpected",
        version="1.0",
        license_lines=("License: MIT",),
    )

    with pytest.raises(verifier.CandidateWheelLicenseError, match="wheel set is invalid"):
        verifier.verify_candidate_wheel_licenses(tmp_path)


def test_candidate_license_gate_runs_before_candidate_install() -> None:
    """CI must verify license metadata before any candidate wheel is installed."""
    workflow = (_REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    verification_step = "- name: Verify pg8000 candidate dependency licenses"
    install_step = "- name: Install exact candidate closure into the CI environment"

    assert verification_step in workflow
    assert "python tools/verify_candidate_wheel_licenses.py /tmp/pg8000-candidate" in workflow
    assert workflow.index(verification_step) < workflow.index(install_step)
