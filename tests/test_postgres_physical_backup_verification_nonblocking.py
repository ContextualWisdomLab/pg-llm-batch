# SPDX-License-Identifier: Apache-2.0
"""Regression tests for non-blocking local file-type validation."""

from __future__ import annotations

import io
import os
import subprocess
import tarfile
from collections.abc import Iterator
from pathlib import Path

import pytest

from pg_llm_batch.postgres_physical_backup_verification import (
    verify_postgres_physical_backup_tar,
)


_VERIFIER_IDENTITIES: set[tuple[int, int]] = set()


def _with_owner(status: os.stat_result, user_id: int) -> os.stat_result:
    """Return equivalent stat metadata with one explicit owner identity."""
    fields = list(status)
    fields[4] = user_id
    return os.stat_result(fields)


@pytest.fixture(autouse=True)
def _model_root_owned_verifiers(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Model temporary verifier fixtures as root-owned system executables."""
    _VERIFIER_IDENTITIES.clear()
    real_fstat = os.fstat

    def root_owned_verifier_metadata(file_descriptor: int) -> os.stat_result:
        status = real_fstat(file_descriptor)
        if (status.st_dev, status.st_ino) in _VERIFIER_IDENTITIES:
            return _with_owner(status, 0)
        return status

    monkeypatch.setattr(os, "fstat", root_owned_verifier_metadata)
    yield
    _VERIFIER_IDENTITIES.clear()


def _write_backup(directory: Path) -> int:
    """Create one private stdout-style tar with an injected manifest."""
    archive_path = directory / "base.tar"
    with tarfile.open(archive_path, mode="w") as archive:
        version_bytes = b"18\n"
        version = tarfile.TarInfo("PG_VERSION")
        version.size = len(version_bytes)
        archive.addfile(version, io.BytesIO(version_bytes))

        manifest_bytes = (
            b'{"PostgreSQL-Backup-Manifest-Version":2,"System-Identifier":1,'
            b'"Files":[],"WAL-Ranges":[],"Manifest-Checksum":"00"}\n'
        )
        manifest = tarfile.TarInfo("backup_manifest")
        manifest.size = len(manifest_bytes)
        archive.addfile(manifest, io.BytesIO(manifest_bytes))
    archive_path.chmod(0o600)
    return os.open(directory, os.O_RDONLY | os.O_DIRECTORY)


def _write_verifier(tmp_path: Path) -> Path:
    """Create and register one root-owned verifier fixture token."""
    executable = tmp_path / "pg_verifybackup"
    executable.write_bytes(b"trusted verifier\n")
    executable.chmod(0o500)
    status = os.stat(executable, follow_symlinks=False)
    _VERIFIER_IDENTITIES.add((status.st_dev, status.st_ino))
    return executable


def _successful_run(
    arguments: list[str], **_kwargs: object
) -> subprocess.CompletedProcess[bytes]:
    """Return one successful bounded verifier result without executing host code."""
    return subprocess.CompletedProcess(arguments, 0)


def test_base_tar_open_is_nonblocking_before_regular_file_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hostile FIFO/device named base.tar cannot block before type validation."""
    backup_directory = tmp_path / "backup"
    backup_directory.mkdir(mode=0o700)
    directory_descriptor = _write_backup(backup_directory)
    executable = _write_verifier(tmp_path)
    real_open = os.open

    def guarded_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        if path == "base.tar":
            assert flags & os.O_NONBLOCK, (
                "base.tar must be opened non-blocking before fstat rejects special files"
            )
        return real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "open", guarded_open)
    monkeypatch.setattr(subprocess, "run", _successful_run)
    try:
        assert verify_postgres_physical_backup_tar(
            directory_descriptor,
            pg_verifybackup_executable=str(executable),
        ).verified
    finally:
        os.close(directory_descriptor)


def test_verifier_open_is_nonblocking_before_regular_file_validation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A hostile FIFO/device verifier path cannot block before type validation."""
    backup_directory = tmp_path / "backup-verifier"
    backup_directory.mkdir(mode=0o700)
    directory_descriptor = _write_backup(backup_directory)
    executable = _write_verifier(tmp_path)
    real_open = os.open

    def guarded_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        if path == str(executable):
            assert flags & os.O_NONBLOCK, (
                "pg_verifybackup must be opened non-blocking before fstat rejects special files"
            )
        return real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(os, "open", guarded_open)
    monkeypatch.setattr(subprocess, "run", _successful_run)
    try:
        assert verify_postgres_physical_backup_tar(
            directory_descriptor,
            pg_verifybackup_executable=str(executable),
        ).verified
    finally:
        os.close(directory_descriptor)
