# SPDX-License-Identifier: Apache-2.0
"""Race regressions for PostgreSQL physical-backup verification authority."""

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


_TRUSTED_EXECUTABLE_BYTES = b"trusted pg_verifybackup binary\n"
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


def _write_stdout_style_base_tar(directory: Path) -> int:
    """Create the single-tablespace tar shape accepted by the verifier."""
    archive_path = directory / "base.tar"
    manifest = (
        b'{"PostgreSQL-Backup-Manifest-Version":2,"System-Identifier":1,'
        b'"Files":[],"WAL-Ranges":[],"Manifest-Checksum":"00"}\n'
    )
    with tarfile.open(archive_path, mode="w") as archive:
        version_payload = b"18\n"
        version = tarfile.TarInfo("PG_VERSION")
        version.size = len(version_payload)
        archive.addfile(version, io.BytesIO(version_payload))
        manifest_member = tarfile.TarInfo("backup_manifest")
        manifest_member.size = len(manifest)
        archive.addfile(manifest_member, io.BytesIO(manifest))
    os.chmod(archive_path, 0o600)
    return os.open(directory, os.O_RDONLY | os.O_DIRECTORY)


def _write_private_pg_verifybackup(tmp_path: Path) -> Path:
    """Create and register one root-owned verifier fixture token."""
    executable = tmp_path / "pg_verifybackup"
    executable.write_bytes(_TRUSTED_EXECUTABLE_BYTES)
    executable.chmod(0o500)
    status = os.stat(executable, follow_symlinks=False)
    _VERIFIER_IDENTITIES.add((status.st_dev, status.st_ino))
    return executable


def test_base_tar_path_replacement_cannot_change_child_backup_authority(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The verifier child must consume the exact tar inode inspected by the package."""
    backup_directory = tmp_path / "backup-path-race"
    backup_directory.mkdir(mode=0o700)
    directory_descriptor = _write_stdout_style_base_tar(backup_directory)
    executable_path = _write_private_pg_verifybackup(tmp_path)
    original_status = os.stat(backup_directory / "base.tar")

    def replace_path_then_run(
        arguments: list[str], **_kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        retained_path = backup_directory / "retained-original.tar"
        (backup_directory / "base.tar").rename(retained_path)
        replacement_path = backup_directory / "base.tar"
        replacement_path.write_bytes(b"replacement bytes must never become verifier authority")
        replacement_path.chmod(0o600)

        verification_directory_fd = int(arguments[-1].rsplit("/", 1)[-1])
        child_tar_fd = os.open(
            "base.tar",
            os.O_RDONLY,
            dir_fd=verification_directory_fd,
        )
        try:
            child_status = os.fstat(child_tar_fd)
            assert (child_status.st_dev, child_status.st_ino) == (
                original_status.st_dev,
                original_status.st_ino,
            )
        finally:
            os.close(child_tar_fd)
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(subprocess, "run", replace_path_then_run)
    try:
        assert verify_postgres_physical_backup_tar(
            directory_descriptor,
            pg_verifybackup_executable=str(executable_path),
        ).verified
    finally:
        os.close(directory_descriptor)
