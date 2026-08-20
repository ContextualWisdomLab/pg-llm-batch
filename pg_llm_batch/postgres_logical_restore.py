# SPDX-License-Identifier: Apache-2.0
"""Restore bounded PostgreSQL logical archives into a caller-selected target."""

from __future__ import annotations

import fcntl
import os
import re
import stat
import subprocess
from dataclasses import dataclass


_SERVICE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MAX_TIMEOUT_SECONDS = 86_400
_MAX_CONNECT_TIMEOUT_SECONDS = 60
_MAX_SIGNED_BIGINT = (1 << 63) - 1
_DEFAULT_MAXIMUM_ARCHIVE_SIZE_BYTES = 64 * 1024 * 1024 * 1024
_MISSING_ARCHIVE_METADATA = object()
_INHERITED_LIBPQ_VARIABLES = frozenset(
    {
        "PGPASSWORD",
        "PGPASSFILE",
        "PGSERVICEFILE",
    }
)


class PostgresLogicalRestoreError(RuntimeError):
    """Report a fail-closed PostgreSQL logical-restore execution violation."""


@dataclass(frozen=True, slots=True)
class PostgresLogicalRestoreResult:
    """Describe the bounded archive consumed by one successful logical restore."""

    size_bytes: int


def _parameters_are_valid(
    service_name: object,
    input_descriptor: object,
    source_superusers_trusted: object,
    pg_restore_executable: object,
    timeout_seconds: object,
    connect_timeout_seconds: object,
    maximum_archive_size_bytes: object,
) -> bool:
    """Return whether execution-authority parameters satisfy the narrow contract."""
    return (
        type(service_name) is str
        and _SERVICE_NAME_RE.fullmatch(service_name) is not None
        and type(input_descriptor) is int
        and input_descriptor >= 0
        and type(source_superusers_trusted) is bool
        and type(pg_restore_executable) is str
        and os.path.isabs(pg_restore_executable)
        and os.path.basename(pg_restore_executable) == "pg_restore"
        and type(timeout_seconds) is int
        and 1 <= timeout_seconds <= _MAX_TIMEOUT_SECONDS
        and type(connect_timeout_seconds) is int
        and 1 <= connect_timeout_seconds <= _MAX_CONNECT_TIMEOUT_SECONDS
        and type(maximum_archive_size_bytes) is int
        and 1 <= maximum_archive_size_bytes <= _MAX_SIGNED_BIGINT
    )


def _archive_is_owner_only(mode: int) -> bool:
    """Return whether an archive mode grants no group or other permissions."""
    return mode & (stat.S_IRWXG | stat.S_IRWXO) == 0


def _archive_metadata(status: object) -> tuple[object, ...]:
    """Return observable file identity metadata used to detect archive mutation."""
    return (
        getattr(status, "st_mode", _MISSING_ARCHIVE_METADATA),
        getattr(status, "st_size", _MISSING_ARCHIVE_METADATA),
        getattr(status, "st_nlink", _MISSING_ARCHIVE_METADATA),
        getattr(status, "st_dev", _MISSING_ARCHIVE_METADATA),
        getattr(status, "st_ino", _MISSING_ARCHIVE_METADATA),
        getattr(status, "st_mtime_ns", _MISSING_ARCHIVE_METADATA),
        getattr(status, "st_ctime_ns", _MISSING_ARCHIVE_METADATA),
    )


def _duplicate_archive_descriptor(input_descriptor: int) -> int:
    """Snapshot caller archive authority before inspection or package reopening."""
    try:
        return os.dup(input_descriptor)
    except (OSError, ValueError, OverflowError):
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore archive could not be inspected"
        ) from None


def _validate_snapshot_descriptor(input_descriptor: int) -> None:
    """Require snapshot regularity, readability, and a zero shared-file offset."""
    try:
        status = os.fstat(input_descriptor)
    except (OSError, ValueError):
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore archive could not be inspected"
        ) from None
    if not stat.S_ISREG(status.st_mode):
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore archive must be a private regular file"
        )
    try:
        access_mode = fcntl.fcntl(input_descriptor, fcntl.F_GETFL) & os.O_ACCMODE
        offset = os.lseek(input_descriptor, 0, os.SEEK_CUR)
    except (OSError, ValueError, OverflowError):
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore archive could not be inspected"
        ) from None
    if access_mode not in (os.O_RDONLY, os.O_RDWR):
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore archive descriptor must be readable"
        )
    if offset != 0:
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore archive must start at offset zero"
        )


def _open_independent_archive(input_descriptor: int) -> int:
    """Reopen retained archive authority with an independent package read offset."""
    try:
        return os.open(
            f"/proc/self/fd/{input_descriptor}",
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0),
        )
    except (OSError, ValueError, OverflowError):
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore archive could not be isolated"
        ) from None


def _close_retained_archive_descriptor(input_descriptor: int) -> None:
    """Best-effort close package-owned archive authority without masking evidence."""
    try:
        os.close(input_descriptor)
    except (OSError, ValueError):
        pass


def _inspect_initial_archive(
    input_descriptor: int,
    maximum_archive_size_bytes: int,
) -> os.stat_result:
    """Require a private, bounded, non-empty regular archive at offset zero."""
    try:
        status = os.fstat(input_descriptor)
    except (OSError, ValueError):
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore archive could not be inspected"
        ) from None

    if not stat.S_ISREG(status.st_mode):
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore archive must be a private regular file"
        )
    if status.st_size <= 0 or status.st_size > maximum_archive_size_bytes:
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore archive must be non-empty and bounded"
        )
    try:
        offset = os.lseek(input_descriptor, 0, os.SEEK_CUR)
    except (OSError, ValueError):
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore archive could not be inspected"
        ) from None
    if offset != 0:
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore archive must start at offset zero"
        )
    if not _archive_is_owner_only(status.st_mode):
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore archive must be owner-only"
        )
    if status.st_nlink != 1:
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore archive must have one link"
        )
    return status


def _libpq_environment(connect_timeout_seconds: int) -> dict[str, str]:
    """Return allowlisted libpq credentials plus the bounded connect timeout."""
    environment = {
        key: os.environ[key]
        for key in _INHERITED_LIBPQ_VARIABLES
        if key in os.environ
    }
    environment["PGCONNECT_TIMEOUT"] = str(connect_timeout_seconds)
    return environment


def _run_pg_restore(
    *,
    service_name: str,
    input_descriptor: int,
    pg_restore_executable: str,
    timeout_seconds: int,
    connect_timeout_seconds: int,
) -> None:
    """Run one shell-free, single-transaction pg_restore with bounded diagnostics."""
    arguments = [
        pg_restore_executable,
        "--single-transaction",
        "--exit-on-error",
        f"--dbname=service={service_name}",
    ]
    environment = _libpq_environment(connect_timeout_seconds)
    try:
        completed = subprocess.run(
            arguments,
            stdin=input_descriptor,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_seconds,
            check=False,
            close_fds=True,
            env=environment,
        )
    except FileNotFoundError:
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore executable unavailable"
        ) from None
    except subprocess.TimeoutExpired:
        raise PostgresLogicalRestoreError("PostgreSQL logical restore timed out") from None
    except Exception:
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore execution failed"
        ) from None

    if type(completed) is not subprocess.CompletedProcess:
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore execution failed"
        )
    if completed.returncode != 0:
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore command failed"
        )


def _verify_archive_unchanged(
    input_descriptor: int,
    initial_status: os.stat_result,
) -> int:
    """Require the exact bounded archive to remain private after restore."""
    try:
        final_status = os.fstat(input_descriptor)
        os.lseek(input_descriptor, 0, os.SEEK_CUR)
    except (OSError, ValueError):
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore archive could not be verified"
        ) from None

    if _archive_metadata(final_status) != _archive_metadata(initial_status):
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore archive changed during execution"
        )
    return initial_status.st_size


def restore_postgres_logical_backup(
    service_name: str,
    input_descriptor: int,
    *,
    source_superusers_trusted: bool = False,
    pg_restore_executable: str,
    timeout_seconds: int = 1800,
    connect_timeout_seconds: int = 15,
    maximum_archive_size_bytes: int = _DEFAULT_MAXIMUM_ARCHIVE_SIZE_BYTES,
) -> PostgresLogicalRestoreResult:
    """Restore one bounded custom archive through isolated caller file authority.

    The caller must explicitly assert that the archive originates from trusted source
    superusers. This assertion is a caller-owned precondition, not package proof that
    archive definitions, ownership, or privileges are safe. The caller also selects
    the target libpq service and is responsible for making that service an isolated
    recovery target; the service name is not an authorization or proof-of-isolation
    boundary. The package first duplicates the caller descriptor so later numeric-FD
    replacement cannot substitute another archive. That snapshot must itself carry
    readable authority and be positioned at byte zero; package code does not widen a
    write-only caller capability. The snapshot is retained through execution and
    reopened through ``/proc/self/fd`` so ``pg_restore`` receives an independent
    package-owned open file description and read offset. That independent descriptor
    must pass the private, one-link, bounded regular-file inspection before child
    execution. Seeking or replacing the caller descriptor after the snapshot therefore
    cannot redirect the child or move its archive read position. The retained snapshot
    is reverified after execution against the inspected child-archive metadata so the
    original snapshotted authority, rather than only the reopened stream, remains the
    post-restore integrity boundary. The caller keeps ownership of the original
    descriptor; package cleanup closes only package-owned descriptors. The package does
    not receive an archive path, place credentials in process arguments, or reflect
    archive/database content in diagnostics. Only ``PGPASSWORD``, ``PGPASSFILE``, and
    ``PGSERVICEFILE`` may be inherited, so ambient host/database/options/SSL-mode
    variables cannot silently redirect or weaken the target session. The validated
    non-secret service selector is supplied through ``--dbname=service=...`` so
    ``pg_restore`` performs a direct database restore rather than merely rendering
    SQL. The command runs with one transaction and exits on the first SQL error, so
    timeout or execution failure does not intentionally commit a partial package
    restore. Descriptor identity and observable archive metadata are revalidated after
    the restore to reject in-place mutation detected during execution. Custom-format
    ``pg_restore`` seeks to the table of contents and data blocks, so a successful
    restore is not required to leave the descriptor at end-of-file. A post-restore
    metadata mismatch means the SQL transaction may already have committed; callers
    must treat that error as unsafe rather than as proof that no restore occurred.
    """
    if not _parameters_are_valid(
        service_name,
        input_descriptor,
        source_superusers_trusted,
        pg_restore_executable,
        timeout_seconds,
        connect_timeout_seconds,
        maximum_archive_size_bytes,
    ):
        raise PostgresLogicalRestoreError(
            "invalid PostgreSQL logical restore parameters"
        )
    if not source_superusers_trusted:
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore requires trusted source superusers"
        )

    snapshot_descriptor = _duplicate_archive_descriptor(input_descriptor)
    try:
        _validate_snapshot_descriptor(snapshot_descriptor)
        retained_descriptor = _open_independent_archive(snapshot_descriptor)
        try:
            initial_status = _inspect_initial_archive(
                retained_descriptor,
                maximum_archive_size_bytes,
            )
            _run_pg_restore(
                service_name=service_name,
                input_descriptor=retained_descriptor,
                pg_restore_executable=pg_restore_executable,
                timeout_seconds=timeout_seconds,
                connect_timeout_seconds=connect_timeout_seconds,
            )
            return PostgresLogicalRestoreResult(
                size_bytes=_verify_archive_unchanged(
                    snapshot_descriptor,
                    initial_status,
                )
            )
        finally:
            _close_retained_archive_descriptor(retained_descriptor)
    finally:
        _close_retained_archive_descriptor(snapshot_descriptor)
