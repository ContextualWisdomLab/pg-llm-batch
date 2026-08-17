# SPDX-License-Identifier: Apache-2.0
"""Create bounded PostgreSQL physical base backups through a private tar stream."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from dataclasses import dataclass


_SERVICE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MAX_TIMEOUT_SECONDS = 86_400
_MAX_CONNECT_TIMEOUT_SECONDS = 60
_INHERITED_LIBPQ_VARIABLES = frozenset(
    {
        "PGPASSWORD",
        "PGPASSFILE",
        "PGSERVICEFILE",
    }
)


class PostgresPhysicalBaseBackupError(RuntimeError):
    """Report a fail-closed PostgreSQL physical base-backup execution violation."""


@dataclass(frozen=True, slots=True)
class PostgresPhysicalBaseBackupResult:
    """Describe the bounded bytes produced by one successful physical base backup."""

    size_bytes: int


def _parameters_are_valid(
    service_name: object,
    output_descriptor: object,
    pg_basebackup_executable: object,
    timeout_seconds: object,
    connect_timeout_seconds: object,
) -> bool:
    """Return whether execution-authority parameters satisfy the narrow contract."""
    return (
        type(service_name) is str
        and _SERVICE_NAME_RE.fullmatch(service_name) is not None
        and type(output_descriptor) is int
        and output_descriptor >= 0
        and type(pg_basebackup_executable) is str
        and os.path.isabs(pg_basebackup_executable)
        and os.path.basename(pg_basebackup_executable) == "pg_basebackup"
        and type(timeout_seconds) is int
        and 1 <= timeout_seconds <= _MAX_TIMEOUT_SECONDS
        and type(connect_timeout_seconds) is int
        and 1 <= connect_timeout_seconds <= _MAX_CONNECT_TIMEOUT_SECONDS
    )


def _output_is_owner_only(mode: int) -> bool:
    """Return whether an output mode grants no group or other permissions."""
    return mode & (stat.S_IRWXG | stat.S_IRWXO) == 0


def _inspect_initial_output(output_descriptor: int) -> os.stat_result:
    """Require a process-owned descriptor for one private empty regular file."""
    try:
        status = os.fstat(output_descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_size != 0:
            raise PostgresPhysicalBaseBackupError(
                "PostgreSQL physical base-backup output must be a private empty regular file"
            )
        offset = os.lseek(output_descriptor, 0, os.SEEK_CUR)
        effective_user_id = os.geteuid()
    except PostgresPhysicalBaseBackupError:
        raise
    except (AttributeError, OSError, ValueError):
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup output could not be inspected"
        ) from None

    if offset != 0:
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup output must start at offset zero"
        )
    if status.st_uid != effective_user_id:
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup output must be owned by the effective process user"
        )
    if not _output_is_owner_only(status.st_mode):
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup output must be owner-only"
        )
    if status.st_nlink != 1:
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup output must have one link"
        )
    return status


def _duplicate_output_for_cleanup(output_descriptor: int) -> int:
    """Retain the inspected file for safe invalidation if caller fd identity changes."""
    try:
        return os.dup(output_descriptor)
    except (OSError, ValueError):
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup output could not be retained"
        ) from None


def _close_cleanup_descriptor(cleanup_descriptor: int) -> None:
    """Best-effort close a package-owned duplicate without replacing primary evidence."""
    try:
        os.close(cleanup_descriptor)
    except (OSError, ValueError):
        pass


def _libpq_environment(service_name: str, connect_timeout_seconds: int) -> dict[str, str]:
    """Return allowlisted libpq credential sources plus package-owned connection authority."""
    environment = {
        key: os.environ[key]
        for key in _INHERITED_LIBPQ_VARIABLES
        if key in os.environ
    }
    environment["PGSERVICE"] = service_name
    environment["PGCONNECT_TIMEOUT"] = str(connect_timeout_seconds)
    return environment


def _invalidate_output(cleanup_descriptor: int) -> None:
    """Best-effort empty and rewind only the originally inspected backup file."""
    try:
        os.ftruncate(cleanup_descriptor, 0)
    except (OSError, ValueError):
        pass
    try:
        os.lseek(cleanup_descriptor, 0, os.SEEK_SET)
    except (OSError, ValueError):
        pass


def _run_pg_basebackup(
    *,
    service_name: str,
    output_descriptor: int,
    cleanup_descriptor: int,
    pg_basebackup_executable: str,
    timeout_seconds: int,
    connect_timeout_seconds: int,
) -> subprocess.CompletedProcess[bytes]:
    """Run one shell-free single-tablespace tar base backup with content-free errors."""
    arguments = [
        pg_basebackup_executable,
        "--pgdata=-",
        "--format=tar",
        "--wal-method=fetch",
        "--checkpoint=spread",
        "--manifest-checksums=SHA256",
        "--no-password",
    ]
    environment = _libpq_environment(service_name, connect_timeout_seconds)
    try:
        completed = subprocess.run(
            arguments,
            stdout=output_descriptor,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            timeout=timeout_seconds,
            check=False,
            close_fds=True,
            env=environment,
        )
    except FileNotFoundError:
        _invalidate_output(cleanup_descriptor)
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup executable unavailable"
        ) from None
    except subprocess.TimeoutExpired:
        _invalidate_output(cleanup_descriptor)
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base backup timed out"
        ) from None
    except Exception:
        _invalidate_output(cleanup_descriptor)
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup execution failed"
        ) from None
    except BaseException:
        _invalidate_output(cleanup_descriptor)
        raise

    if type(completed) is not subprocess.CompletedProcess:
        _invalidate_output(cleanup_descriptor)
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup execution failed"
        )
    if completed.returncode != 0:
        _invalidate_output(cleanup_descriptor)
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup command failed"
        )
    return completed


def _finalize_output(
    output_descriptor: int,
    cleanup_descriptor: int,
    initial_status: os.stat_result,
) -> int:
    """Synchronize and validate the same private backup file after pg_basebackup exits."""
    try:
        os.fsync(cleanup_descriptor)
        status = os.fstat(output_descriptor)
    except (OSError, ValueError):
        _invalidate_output(cleanup_descriptor)
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup output could not be finalized"
        ) from None

    if status.st_size <= 0:
        _invalidate_output(cleanup_descriptor)
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup output is incomplete"
        )
    if (
        status.st_uid != initial_status.st_uid
        or status.st_nlink != 1
        or not _output_is_owner_only(status.st_mode)
    ):
        _invalidate_output(cleanup_descriptor)
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup output became unsafe"
        )
    if (status.st_dev, status.st_ino) != (initial_status.st_dev, initial_status.st_ino):
        _invalidate_output(cleanup_descriptor)
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup output changed during execution"
        )
    return status.st_size


def create_postgres_physical_basebackup(
    service_name: str,
    output_descriptor: int,
    *,
    pg_basebackup_executable: str,
    timeout_seconds: int = 7200,
    connect_timeout_seconds: int = 15,
) -> PostgresPhysicalBaseBackupResult:
    """Create one bounded full-cluster tar base backup with required WAL included.

    The output is the tar stream emitted by ``pg_basebackup --pgdata=- --format=tar``
    with ``--wal-method=fetch``. PostgreSQL therefore fails this narrow mode when the
    source has additional tablespaces; this seam intentionally does not accept
    tablespace mappings or server-side output paths. The caller owns filesystem
    placement and descriptor lifetime and must treat the bytes as highly sensitive
    cluster material. The package never receives an output path and never places
    connection material in process arguments.

    ``service_name`` is a libpq service selector, not a tenant authorization boundary.
    Only ``PGPASSWORD``, ``PGPASSFILE``, and ``PGSERVICEFILE`` may be inherited; the
    package owns ``PGSERVICE`` and the bounded ``PGCONNECT_TIMEOUT``. The source role
    and server still must satisfy PostgreSQL's replication-protocol prerequisites.
    A SHA-256 backup manifest is requested and pg_basebackup's normal durable-sync
    behavior is retained; this function additionally fsyncs the caller-owned stream.

    Successful execution proves only that PostgreSQL produced one physical base-backup
    tar containing WAL required for backup consistency. It does not establish a
    continuous WAL archive, perform WAL replay/PITR, prove restore usability, recover
    external keys/configuration/provider state, or establish deployment RPO/RTO.
    """
    if not _parameters_are_valid(
        service_name,
        output_descriptor,
        pg_basebackup_executable,
        timeout_seconds,
        connect_timeout_seconds,
    ):
        raise PostgresPhysicalBaseBackupError(
            "invalid PostgreSQL physical base-backup parameters"
        )

    initial_status = _inspect_initial_output(output_descriptor)
    cleanup_descriptor = _duplicate_output_for_cleanup(output_descriptor)
    try:
        _run_pg_basebackup(
            service_name=service_name,
            output_descriptor=output_descriptor,
            cleanup_descriptor=cleanup_descriptor,
            pg_basebackup_executable=pg_basebackup_executable,
            timeout_seconds=timeout_seconds,
            connect_timeout_seconds=connect_timeout_seconds,
        )
        return PostgresPhysicalBaseBackupResult(
            size_bytes=_finalize_output(
                output_descriptor,
                cleanup_descriptor,
                initial_status,
            )
        )
    finally:
        _close_cleanup_descriptor(cleanup_descriptor)
