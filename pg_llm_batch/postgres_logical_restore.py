# SPDX-License-Identifier: Apache-2.0
"""Restore bounded PostgreSQL logical archives into a caller-selected target."""

from __future__ import annotations

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


class PostgresLogicalRestoreError(RuntimeError):
    """Report a fail-closed PostgreSQL logical-restore execution violation."""


@dataclass(frozen=True, slots=True)
class PostgresLogicalRestoreResult:
    """Describe the bounded archive consumed by one successful logical restore."""

    size_bytes: int


def _parameters_are_valid(
    service_name: object,
    input_descriptor: object,
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


def _libpq_environment(service_name: str, connect_timeout_seconds: int) -> dict[str, str]:
    """Return only inherited libpq variables plus bounded package overrides."""
    environment = {
        key: value for key, value in os.environ.items() if key.startswith("PG")
    }
    environment["PGSERVICE"] = service_name
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
    ]
    environment = _libpq_environment(service_name, connect_timeout_seconds)
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
    except BaseException:
        raise

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
    """Require the exact bounded archive to remain private and fully consumed."""
    try:
        final_status = os.fstat(input_descriptor)
        offset = os.lseek(input_descriptor, 0, os.SEEK_CUR)
    except (OSError, ValueError):
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore archive could not be verified"
        ) from None

    if (
        final_status.st_size != initial_status.st_size
        or final_status.st_nlink != 1
        or not _archive_is_owner_only(final_status.st_mode)
    ):
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore archive changed during execution"
        )
    if offset != initial_status.st_size:
        raise PostgresLogicalRestoreError(
            "PostgreSQL logical restore archive was not consumed completely"
        )
    return initial_status.st_size


def restore_postgres_logical_backup(
    service_name: str,
    input_descriptor: int,
    *,
    pg_restore_executable: str,
    timeout_seconds: int = 1800,
    connect_timeout_seconds: int = 15,
    maximum_archive_size_bytes: int = _DEFAULT_MAXIMUM_ARCHIVE_SIZE_BYTES,
) -> PostgresLogicalRestoreResult:
    """Restore one bounded custom archive through a caller-owned file descriptor.

    The caller selects the target libpq service and is responsible for making that
    service an isolated recovery target. The package does not receive an archive
    path, place connection material in process arguments, or reflect archive/database
    content in diagnostics. ``pg_restore`` runs with one transaction and exits on the
    first SQL error so timeout or execution failure does not intentionally commit a
    partial package restore.
    """
    if not _parameters_are_valid(
        service_name,
        input_descriptor,
        pg_restore_executable,
        timeout_seconds,
        connect_timeout_seconds,
        maximum_archive_size_bytes,
    ):
        raise PostgresLogicalRestoreError(
            "invalid PostgreSQL logical restore parameters"
        )

    initial_status = _inspect_initial_archive(
        input_descriptor,
        maximum_archive_size_bytes,
    )
    _run_pg_restore(
        service_name=service_name,
        input_descriptor=input_descriptor,
        pg_restore_executable=pg_restore_executable,
        timeout_seconds=timeout_seconds,
        connect_timeout_seconds=connect_timeout_seconds,
    )
    return PostgresLogicalRestoreResult(
        size_bytes=_verify_archive_unchanged(input_descriptor, initial_status)
    )
