"""Regression tests for immutable pg8000 source-to-wheel parity evidence.

The commercial PostgreSQL-driver migration pins the published pg8000 wheel, but
a wheel digest alone does not show that its executable package sources match the
published source distribution. These tests require a bounded, non-executing
archive verifier and require CI to run it before candidate installation.
"""

from __future__ import annotations

import importlib.util
from io import BytesIO
from pathlib import Path
import tarfile
import zipfile

import pytest


_REPOSITORY_ROOT = Path(__file__).parents[1]
_TOOL_PATH = _REPOSITORY_ROOT / "tools" / "verify_candidate_source_wheel_parity.py"


def _load_verifier():
    """Load the repository-owned parity verifier without making tools a package."""
    assert _TOOL_PATH.is_file(), "candidate source-wheel parity verifier is missing"
    spec = importlib.util.spec_from_file_location("candidate_source_wheel_parity", _TOOL_PATH)
    if spec is None or spec.loader is None:
        raise AssertionError("candidate source-wheel parity verifier could not be loaded")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _write_sdist(path: Path, sources: dict[str, bytes]) -> None:
    """Write a minimal pg8000 source distribution with executable package bytes."""
    with tarfile.open(path, "w:gz") as archive:
        for relative_path, payload in sources.items():
            member = tarfile.TarInfo(f"pg8000-1.31.5/src/pg8000/{relative_path}")
            member.size = len(payload)
            archive.addfile(member, BytesIO(payload))
        documentation = b"candidate docs\n"
        member = tarfile.TarInfo("pg8000-1.31.5/README.md")
        member.size = len(documentation)
        archive.addfile(member, BytesIO(documentation))


def _write_wheel(path: Path, sources: dict[str, bytes]) -> None:
    """Write a minimal pg8000 wheel carrying the supplied package source bytes."""
    with zipfile.ZipFile(path, "w") as archive:
        for relative_path, payload in sources.items():
            archive.writestr(f"pg8000/{relative_path}", payload)
        archive.writestr(
            "pg8000-1.31.5.dist-info/METADATA",
            "Metadata-Version: 2.4\nName: pg8000\nVersion: 1.31.5\n",
        )


def test_candidate_source_and_wheel_require_identical_python_payloads(tmp_path: Path) -> None:
    """Exact executable Python sources must agree across the two published artifacts."""
    verifier = _load_verifier()
    sources = {
        "__init__.py": b"__version__ = '1.31.5'\n",
        "core.py": b"def marker():\n    return 'same'\n",
    }
    sdist_path = tmp_path / "pg8000-1.31.5.tar.gz"
    wheel_path = tmp_path / "pg8000-1.31.5-py3-none-any.whl"
    _write_sdist(sdist_path, sources)
    _write_wheel(wheel_path, sources)

    verifier.verify_candidate_source_wheel_parity(sdist_path, wheel_path)


def test_candidate_source_wheel_parity_rejects_changed_executable_source(tmp_path: Path) -> None:
    """A wheel-side source mutation must fail even when both archive names are expected."""
    verifier = _load_verifier()
    sdist_path = tmp_path / "pg8000-1.31.5.tar.gz"
    wheel_path = tmp_path / "pg8000-1.31.5-py3-none-any.whl"
    _write_sdist(sdist_path, {"core.py": b"VALUE = 'source'\n"})
    _write_wheel(wheel_path, {"core.py": b"VALUE = 'wheel'\n"})

    with pytest.raises(
        verifier.CandidateSourceWheelParityError,
        match="package payload differs",
    ):
        verifier.verify_candidate_source_wheel_parity(sdist_path, wheel_path)


def test_candidate_source_wheel_parity_rejects_extra_wheel_python_source(tmp_path: Path) -> None:
    """The built wheel must not introduce executable Python absent from the sdist."""
    verifier = _load_verifier()
    sdist_path = tmp_path / "pg8000-1.31.5.tar.gz"
    wheel_path = tmp_path / "pg8000-1.31.5-py3-none-any.whl"
    _write_sdist(sdist_path, {"core.py": b"VALUE = 1\n"})
    _write_wheel(
        wheel_path,
        {
            "core.py": b"VALUE = 1\n",
            "injected.py": b"VALUE = 'unexpected'\n",
        },
    )

    with pytest.raises(
        verifier.CandidateSourceWheelParityError,
        match="package payload differs",
    ):
        verifier.verify_candidate_source_wheel_parity(sdist_path, wheel_path)


def test_candidate_source_wheel_parity_runs_before_candidate_install() -> None:
    """CI must hash and compare the source artifact before candidate code is installed."""
    workflow = (_REPOSITORY_ROOT / ".github" / "workflows" / "ci.yml").read_text(
        encoding="utf-8"
    )
    source_download_step = "- name: Download exact pg8000 candidate source distribution"
    source_digest_step = "- name: Verify pg8000 candidate source digest"
    parity_step = "- name: Verify pg8000 candidate source-wheel parity"
    install_step = "- name: Install exact candidate closure into release Python environments"

    assert source_download_step in workflow
    assert source_digest_step in workflow
    assert parity_step in workflow
    assert (
        "python tools/verify_candidate_source_wheel_parity.py "
        "/tmp/pg8000-candidate-source/pg8000-1.31.5.tar.gz "
        "/tmp/pg8000-candidate/pg8000-1.31.5-py3-none-any.whl"
    ) in workflow
    assert workflow.index(source_download_step) < workflow.index(source_digest_step)
    assert workflow.index(source_digest_step) < workflow.index(parity_step)
    assert workflow.index(parity_step) < workflow.index(install_step)
