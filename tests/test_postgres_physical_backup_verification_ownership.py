# SPDX-License-Identifier: Apache-2.0
"""Ownership and cleanup regressions for physical-backup verification."""

from __future__ import annotations

import io
import os
import stat
import tarfile
from pathlib import Path

import pytest

from pg_llm_batch.postgres_physical_backup_verification import (
    PostgresPhysicalBackupVerificationError,
    _inspect_backup_directory,
    _open_base_tar,
    _retain_pg_verifybackup_executable,
)


_INVALID_PARAMETERS = "^invalid PostgreSQL physical-backup verification parameters$"
_VERIFICATION_FAILED = "^PostgreSQL physical backup verification failed$"


def _private_backup_directory(tmp_path: Path, name: str) -> tuple[Path, int]:
    """Create one process-owned private directory with a minimal base tar."""
    directory = tmp_path / name
    directory.mkdir(mode=0o700)
    archive_path = directory / "base.tar"
    manifest = b'{"PostgreSQL-Backup-Manifest-Version":2,"Files":[]}\n'
    with tarfile.open(archive_path, mode="w") as archive:
        version_bytes = b"18\n"
        version = tarfile.TarInfo("PG_VERSION")
        version.size = len(version_bytes)
        archive.addfile(version, io.BytesIO(version_bytes))
        manifest_member = tarfile.TarInfo("backup_manifest")
        manifest_member.size = len(manifest)
        archive.addfile(manifest_member, io.BytesIO(manifest))
    archive_path.chmod(0o600)
    return directory, os.open(directory, os.O_RDONLY | os.O_DIRECTORY)


def _with_owner(status: os.stat_result, user_id: int) -> os.stat_result:
    """Return equivalent stat metadata with one explicit owner identity."""
    fields = list(status)
    fields[4] = user_id
    return os.stat_result(fields)


def _with_mode(status: os.stat_result, mode: int) -> os.stat_result:
    """Return equivalent stat metadata with one explicit mode."""
    fields = list(status)
    fields[0] = mode
    return os.stat_result(fields)


def _foreign_owner(status: os.stat_result) -> os.stat_result:
    """Return equivalent stat metadata whose owner is another local principal."""
    effective_user_id = os.geteuid()
    foreign_user_id = (
        effective_user_id + 1
        if effective_user_id < 2**31 - 1
        else effective_user_id - 1
    )
    return _with_owner(status, foreign_user_id)


def test_backup_directory_must_be_owned_by_effective_process_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A different directory owner must not retain mutation authority during verification."""
    _directory, descriptor = _private_backup_directory(tmp_path, "foreign-directory")
    real_fstat = os.fstat
    status = real_fstat(descriptor)
    identity = (status.st_dev, status.st_ino)

    def foreign_directory_owner(file_descriptor: int) -> os.stat_result:
        observed = real_fstat(file_descriptor)
        if (observed.st_dev, observed.st_ino) == identity:
            return _foreign_owner(observed)
        return observed

    monkeypatch.setattr(os, "fstat", foreign_directory_owner)
    try:
        with pytest.raises(
            PostgresPhysicalBackupVerificationError,
            match=_INVALID_PARAMETERS,
        ):
            _inspect_backup_directory(descriptor)
    finally:
        os.close(descriptor)


def test_base_tar_must_be_owned_by_effective_process_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A different file owner must not retain mutation authority to accepted backup bytes."""
    directory, descriptor = _private_backup_directory(tmp_path, "foreign-base-tar")
    real_fstat = os.fstat
    archive_status = os.stat(directory / "base.tar", follow_symlinks=False)
    archive_identity = (archive_status.st_dev, archive_status.st_ino)
    returned_descriptor: int | None = None

    def foreign_archive_owner(file_descriptor: int) -> os.stat_result:
        observed = real_fstat(file_descriptor)
        if (observed.st_dev, observed.st_ino) == archive_identity:
            return _foreign_owner(observed)
        return observed

    monkeypatch.setattr(os, "fstat", foreign_archive_owner)
    try:
        with pytest.raises(
            PostgresPhysicalBackupVerificationError,
            match=_VERIFICATION_FAILED,
        ):
            returned_descriptor = _open_base_tar(descriptor)
    finally:
        if returned_descriptor is not None:
            os.close(returned_descriptor)
        os.close(descriptor)


def test_verifier_must_not_be_owned_by_effective_service_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A service account must not retain chmod or rewrite authority to verifier bytes."""
    executable = tmp_path / "pg_verifybackup"
    executable.write_bytes(b"service-owned verifier\n")
    executable.chmod(0o500)
    real_fstat = os.fstat
    executable_status = os.stat(executable, follow_symlinks=False)
    executable_identity = (executable_status.st_dev, executable_status.st_ino)
    simulated_effective_user_id = 4242
    retained_descriptor: int | None = None

    def service_owned_executable(file_descriptor: int) -> os.stat_result:
        observed = real_fstat(file_descriptor)
        if (observed.st_dev, observed.st_ino) == executable_identity:
            return _with_owner(observed, simulated_effective_user_id)
        return observed

    monkeypatch.setattr(os, "geteuid", lambda: simulated_effective_user_id)
    monkeypatch.setattr(os, "fstat", service_owned_executable)
    try:
        with pytest.raises(
            PostgresPhysicalBackupVerificationError,
            match=_INVALID_PARAMETERS,
        ):
            retained_descriptor = _retain_pg_verifybackup_executable(str(executable))
    finally:
        if retained_descriptor is not None:
            os.close(retained_descriptor)


def test_verifier_must_be_owned_by_root(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An unrelated executable owner must not retain in-place mutation authority."""
    executable = tmp_path / "pg_verifybackup"
    executable.write_bytes(b"trusted verifier\n")
    executable.chmod(0o500)
    real_fstat = os.fstat
    executable_status = os.stat(executable, follow_symlinks=False)
    executable_identity = (executable_status.st_dev, executable_status.st_ino)
    retained_descriptor: int | None = None

    def foreign_executable_owner(file_descriptor: int) -> os.stat_result:
        observed = real_fstat(file_descriptor)
        if (observed.st_dev, observed.st_ino) == executable_identity:
            return _foreign_owner(observed)
        return observed

    monkeypatch.setattr(os, "fstat", foreign_executable_owner)
    try:
        with pytest.raises(
            PostgresPhysicalBackupVerificationError,
            match=_INVALID_PARAMETERS,
        ):
            retained_descriptor = _retain_pg_verifybackup_executable(str(executable))
    finally:
        if retained_descriptor is not None:
            os.close(retained_descriptor)


@pytest.mark.parametrize("privilege_bit", [stat.S_ISUID, stat.S_ISGID])
def test_verifier_rejects_setid_root_owned_executable(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    privilege_bit: int,
) -> None:
    """A trusted verifier must not gain user or group identity through set-id bits."""
    executable = tmp_path / "pg_verifybackup"
    executable.write_bytes(b"set-id verifier\n")
    executable.chmod(0o500)
    real_fstat = os.fstat
    executable_status = os.stat(executable, follow_symlinks=False)
    executable_identity = (executable_status.st_dev, executable_status.st_ino)
    retained_descriptor: int | None = None

    def setid_root_owned_executable(file_descriptor: int) -> os.stat_result:
        observed = real_fstat(file_descriptor)
        if (observed.st_dev, observed.st_ino) == executable_identity:
            observed = _with_owner(observed, 0)
            return _with_mode(observed, observed.st_mode | privilege_bit)
        return observed

    monkeypatch.setattr(os, "fstat", setid_root_owned_executable)
    try:
        with pytest.raises(
            PostgresPhysicalBackupVerificationError,
            match=_INVALID_PARAMETERS,
        ):
            retained_descriptor = _retain_pg_verifybackup_executable(str(executable))
    finally:
        if retained_descriptor is not None:
            os.close(retained_descriptor)


def test_base_tar_descriptor_is_closed_when_initial_fstat_fails(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An inspection failure after open must not leak package-owned file authority."""
    _directory, directory_descriptor = _private_backup_directory(
        tmp_path,
        "base-tar-fstat-failure",
    )
    real_open = os.open
    real_fstat = os.fstat
    opened: list[int] = []

    def tracked_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        *args: object,
        **kwargs: object,
    ) -> int:
        file_descriptor = real_open(path, flags, *args, **kwargs)  # type: ignore[arg-type]
        if path == "base.tar":
            opened.append(file_descriptor)
        return file_descriptor

    def fail_base_tar_fstat(file_descriptor: int) -> os.stat_result:
        if opened and file_descriptor == opened[-1]:
            raise OSError("sensitive base-tar stat diagnostic")
        return real_fstat(file_descriptor)

    monkeypatch.setattr(os, "open", tracked_open)
    monkeypatch.setattr(os, "fstat", fail_base_tar_fstat)
    try:
        with pytest.raises(
            PostgresPhysicalBackupVerificationError,
            match=_VERIFICATION_FAILED,
        ):
            _open_base_tar(directory_descriptor)
        assert opened
        with pytest.raises(OSError):
            real_fstat(opened[-1])
    finally:
        if opened:
            try:
                os.close(opened[-1])
            except OSError:
                pass
        os.close(directory_descriptor)
