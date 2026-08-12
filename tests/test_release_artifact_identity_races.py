# SPDX-License-Identifier: Apache-2.0
"""Regular-file replacement races for reproducible release evidence."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pg_llm_batch.release_evidence import ReleaseEvidenceError, verify_reproducible_release


DISTRIBUTION = "pg-llm-batch"
VERSION = "0.1.0"
COMMIT = "a" * 40
SOURCE_DATE_EPOCH = 1_786_000_000
WHEEL = "pg_llm_batch-0.1.0-py3-none-any.whl"
SDIST = "pg_llm_batch-0.1.0.tar.gz"


def _write_release(directory: Path) -> None:
    """Create one deterministic release output directory."""
    directory.mkdir()
    (directory / WHEEL).write_bytes(b"wheel")
    (directory / SDIST).write_bytes(b"sdist")


def _verify(first: Path, second: Path) -> dict[str, object]:
    """Run the public verifier with deterministic metadata."""
    return verify_reproducible_release(  # type: ignore[return-value]
        first,
        second,
        distribution_name=DISTRIBUTION,
        version=VERSION,
        source_commit=COMMIT,
        source_date_epoch=SOURCE_DATE_EPOCH,
    )


def test_verifier_refuses_same_bytes_regular_replacement_before_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Bind each open to the inode observed during the initial directory scan."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    _write_release(second)
    original_open = os.open
    replacement_directories = iter((first, second))

    def racing_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if dir_fd is not None and os.fspath(path) == WHEEL:
            directory = next(replacement_directories)
            target = directory / WHEEL
            target.rename(tmp_path / f"{directory.name}-original.whl")
            target.write_bytes(b"wheel")
        return original_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(os, "open", racing_open)

    with pytest.raises(ReleaseEvidenceError, match="changed during verification"):
        _verify(first, second)


def test_verifier_refuses_same_name_replacement_before_final_rescan(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Compare final entry identity, not only the bounded artifact names."""
    first = tmp_path / "first"
    second = tmp_path / "second"
    _write_release(first)
    _write_release(second)
    original_scandir = os.scandir
    descriptor_scans = 0

    def racing_scandir(path: str | bytes | os.PathLike[str] | int):  # type: ignore[no-untyped-def]
        nonlocal descriptor_scans
        if isinstance(path, int):
            descriptor_scans += 1
            if descriptor_scans == 2:
                target = first / WHEEL
                target.rename(tmp_path / "first-original.whl")
                target.write_bytes(b"wheel")
        return original_scandir(path)

    monkeypatch.setattr(os, "scandir", racing_scandir)

    with pytest.raises(ReleaseEvidenceError, match="directory changed during verification"):
        _verify(first, second)
