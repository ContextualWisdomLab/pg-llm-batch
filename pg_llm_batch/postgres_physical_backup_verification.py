# SPDX-License-Identifier: Apache-2.0
"""Verify one PostgreSQL stdout-tar physical backup without path extraction."""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
import tarfile
import tempfile
from dataclasses import dataclass
from typing import BinaryIO


_MAX_TIMEOUT_SECONDS = 86_400
_NONBLOCKING_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_INVALID_PARAMETERS = "invalid PostgreSQL physical-backup verification parameters"
_MANIFEST_ERROR = "PostgreSQL physical backup must contain one regular backup manifest"
_VERIFICATION_FAILED = "PostgreSQL physical backup verification failed"


class PostgresPhysicalBackupVerificationError(RuntimeError):
    """Report a content-free PostgreSQL physical-backup verification failure."""


@dataclass(frozen=True, slots=True)
class PostgresPhysicalBackupVerificationResult:
    """Describe whether PostgreSQL accepted one physical-backup tar."""

    verified: bool


def _parameters_are_valid(
    backup_directory_descriptor: object,
    pg_verifybackup_executable: object,
    timeout_seconds: object,
) -> bool:
    """Return whether caller authority and execution budget are narrowly valid."""
    return (
        type(backup_directory_descriptor) is int
        and backup_directory_descriptor >= 0
        and type(pg_verifybackup_executable) is str
        and os.path.isabs(pg_verifybackup_executable)
        and os.path.basename(pg_verifybackup_executable) == "pg_verifybackup"
        and type(timeout_seconds) is int
        and 1 <= timeout_seconds <= _MAX_TIMEOUT_SECONDS
    )


def _retain_backup_directory(backup_directory_descriptor: int) -> int:
    """Snapshot caller directory authority before later inspection or child use."""
    try:
        return os.dup(backup_directory_descriptor)
    except (OSError, OverflowError, ValueError):
        raise PostgresPhysicalBackupVerificationError(_INVALID_PARAMETERS) from None


def _close_descriptor(file_descriptor: int) -> None:
    """Best-effort close package-owned descriptor authority."""
    try:
        os.close(file_descriptor)
    except (OSError, ValueError):
        pass


def _retain_pg_verifybackup_executable(pg_verifybackup_executable: str) -> int:
    """Snapshot one trusted-owner executable inode before child-process use."""
    try:
        executable_descriptor = os.open(
            pg_verifybackup_executable,
            _NONBLOCKING_READ_FLAGS,
        )
    except (OSError, ValueError):
        raise PostgresPhysicalBackupVerificationError(_INVALID_PARAMETERS) from None
    try:
        status = os.fstat(executable_descriptor)
        effective_user_id = os.geteuid()
    except (AttributeError, OSError, ValueError):
        _close_descriptor(executable_descriptor)
        raise PostgresPhysicalBackupVerificationError(_INVALID_PARAMETERS) from None
    if (
        not stat.S_ISREG(status.st_mode)
        or status.st_uid not in (0, effective_user_id)
        or status.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
        or status.st_mode & 0o111 == 0
    ):
        _close_descriptor(executable_descriptor)
        raise PostgresPhysicalBackupVerificationError(_INVALID_PARAMETERS)
    return executable_descriptor


def _inspect_backup_directory(backup_directory_descriptor: int) -> None:
    """Require process-owned private single-tar directory authority."""
    try:
        status = os.fstat(backup_directory_descriptor)
        effective_user_id = os.geteuid()
    except (AttributeError, OSError, ValueError):
        raise PostgresPhysicalBackupVerificationError(_INVALID_PARAMETERS) from None
    if (
        not stat.S_ISDIR(status.st_mode)
        or status.st_uid != effective_user_id
        or status.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
    ):
        raise PostgresPhysicalBackupVerificationError(_INVALID_PARAMETERS)
    try:
        entries = os.listdir(backup_directory_descriptor)
    except (OSError, ValueError):
        raise PostgresPhysicalBackupVerificationError(_INVALID_PARAMETERS) from None
    if entries != ["base.tar"]:
        raise PostgresPhysicalBackupVerificationError(_VERIFICATION_FAILED)


def _open_base_tar(backup_directory_descriptor: int) -> int:
    """Open the exact process-owned stdout tar relative to pinned directory authority."""
    try:
        base_tar_descriptor = os.open(
            "base.tar",
            _NONBLOCKING_READ_FLAGS,
            dir_fd=backup_directory_descriptor,
        )
    except (OSError, ValueError):
        raise PostgresPhysicalBackupVerificationError(_VERIFICATION_FAILED) from None
    try:
        status = os.fstat(base_tar_descriptor)
        effective_user_id = os.geteuid()
    except (AttributeError, OSError, ValueError):
        _close_descriptor(base_tar_descriptor)
        raise PostgresPhysicalBackupVerificationError(_VERIFICATION_FAILED) from None
    if (
        not stat.S_ISREG(status.st_mode)
        or status.st_uid != effective_user_id
        or status.st_nlink != 1
        or status.st_mode & (stat.S_IRWXG | stat.S_IRWXO)
    ):
        _close_descriptor(base_tar_descriptor)
        raise PostgresPhysicalBackupVerificationError(_VERIFICATION_FAILED)
    return base_tar_descriptor


def _retain_base_tar(base_tar_descriptor: int) -> int:
    """Retain private tar authority or cross the content-free verification boundary."""
    try:
        return os.dup(base_tar_descriptor)
    except (OSError, OverflowError, ValueError):
        raise PostgresPhysicalBackupVerificationError(_VERIFICATION_FAILED) from None


def _copy_manifest_to_private_file(
    base_tar_descriptor: int,
    manifest_file: BinaryIO,
) -> int:
    """Copy exactly one regular injected manifest to anonymous descriptor authority."""
    base_tar_snapshot = _retain_base_tar(base_tar_descriptor)
    try:
        with os.fdopen(base_tar_snapshot, "rb", closefd=False) as base_tar_file:
            try:
                with tarfile.open(fileobj=base_tar_file, mode="r:*") as archive:
                    manifest_members = [
                        member
                        for member in archive.getmembers()
                        if member.name == "backup_manifest"
                    ]
                    if len(manifest_members) != 1 or not manifest_members[0].isreg():
                        raise PostgresPhysicalBackupVerificationError(_MANIFEST_ERROR)
                    manifest_source = archive.extractfile(manifest_members[0])
                    if manifest_source is None:
                        raise PostgresPhysicalBackupVerificationError(_MANIFEST_ERROR)
                    with manifest_source:
                        shutil.copyfileobj(manifest_source, manifest_file)
            except PostgresPhysicalBackupVerificationError:
                raise
            except (OSError, ValueError, tarfile.TarError):
                raise PostgresPhysicalBackupVerificationError(
                    _VERIFICATION_FAILED
                ) from None
    finally:
        _close_descriptor(base_tar_snapshot)
    try:
        manifest_file.flush()
        manifest_file.seek(0)
        return manifest_file.fileno()
    except (OSError, ValueError):
        raise PostgresPhysicalBackupVerificationError(_VERIFICATION_FAILED) from None


def _run_pg_verifybackup(
    *,
    backup_directory_descriptor: int,
    manifest_descriptor: int,
    pg_verifybackup_executable: str,
    timeout_seconds: int,
) -> None:
    """Run PostgreSQL's tar verifier through inherited descriptor authority."""
    executable_descriptor = _retain_pg_verifybackup_executable(
        pg_verifybackup_executable
    )
    try:
        arguments = [
            f"/proc/self/fd/{executable_descriptor}",
            "--format=tar",
            "--no-parse-wal",
            "--quiet",
            "--exit-on-error",
            f"--manifest-path=/proc/self/fd/{manifest_descriptor}",
            f"/proc/self/fd/{backup_directory_descriptor}",
        ]
        try:
            completed = subprocess.run(
                arguments,
                stdin=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                close_fds=True,
                pass_fds=(
                    executable_descriptor,
                    backup_directory_descriptor,
                    manifest_descriptor,
                ),
                timeout=timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired):
            raise PostgresPhysicalBackupVerificationError(_VERIFICATION_FAILED) from None
        except Exception:
            raise PostgresPhysicalBackupVerificationError(_VERIFICATION_FAILED) from None
        except BaseException:
            raise
        if type(completed) is not subprocess.CompletedProcess or completed.returncode != 0:
            raise PostgresPhysicalBackupVerificationError(_VERIFICATION_FAILED)
    finally:
        _close_descriptor(executable_descriptor)


def verify_postgres_physical_backup_tar(
    backup_directory_descriptor: int,
    *,
    pg_verifybackup_executable: str,
    timeout_seconds: int = 1800,
) -> PostgresPhysicalBackupVerificationResult:
    """Verify one single-tablespace PostgreSQL stdout-format base-backup tar.

    The caller owns an already-open private backup-directory descriptor whose
    only entry is the owner-only, single-link ``base.tar`` emitted by
    ``pg_basebackup --pgdata=- --format=tar``. The package snapshots that
    directory before inspection and requires both the retained directory and
    ``base.tar`` to be owned by the effective process user so another local file
    owner cannot retain mutation authority to the accepted backup bytes. It
    opens ``base.tar`` non-blocking relative to the pinned directory without
    following a final symlink and copies exactly one regular injected
    ``backup_manifest`` into anonymous temporary-file authority. No backup
    member is extracted to a caller-visible path. The absolute trusted
    ``pg_verifybackup`` path is likewise opened non-blocking before regular-file
    validation and without following its final symlink, rejected unless its
    owner is root or the effective process user and it is executable without
    group/other write authority, and executed only through the retained
    descriptor so a later pathname swap cannot replace the accepted verifier
    inode. Descriptor-retention and local staging failures cross fixed
    content-free package boundaries rather than exposing host diagnostics.

    PostgreSQL 18 cannot parse WAL directly from tar-format backups, so the
    verifier runs ``pg_verifybackup --format=tar --no-parse-wal`` and supplies
    the injected manifest separately through ``/proc/self/fd``. Success proves
    only PostgreSQL's bounded backup-verification checks for these bytes; it
    does not perform WAL replay, test restore/application validation, PITR,
    timeline continuity, or establish RPO/RTO, HA/DR, CSAP, or SOC 2 claims.
    """
    if not _parameters_are_valid(
        backup_directory_descriptor,
        pg_verifybackup_executable,
        timeout_seconds,
    ):
        raise PostgresPhysicalBackupVerificationError(_INVALID_PARAMETERS)

    private_directory_descriptor = _retain_backup_directory(
        backup_directory_descriptor
    )
    try:
        _inspect_backup_directory(private_directory_descriptor)
        base_tar_descriptor = _open_base_tar(private_directory_descriptor)
        try:
            with tempfile.TemporaryFile(mode="w+b") as manifest_file:
                manifest_descriptor = _copy_manifest_to_private_file(
                    base_tar_descriptor,
                    manifest_file,
                )
                _run_pg_verifybackup(
                    backup_directory_descriptor=private_directory_descriptor,
                    manifest_descriptor=manifest_descriptor,
                    pg_verifybackup_executable=pg_verifybackup_executable,
                    timeout_seconds=timeout_seconds,
                )
        finally:
            _close_descriptor(base_tar_descriptor)
    finally:
        _close_descriptor(private_directory_descriptor)
    return PostgresPhysicalBackupVerificationResult(verified=True)
