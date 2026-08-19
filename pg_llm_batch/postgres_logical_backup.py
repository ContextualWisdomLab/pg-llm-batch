# SPDX-License-Identifier: Apache-2.0
"""Create bounded PostgreSQL logical backups through a caller-owned private file."""

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


class PostgresLogicalBackupError(RuntimeError):
    """Report a fail-closed PostgreSQL logical-backup execution violation."""


@dataclass(frozen=True, slots=True)
class PostgresLogicalBackupResult:
    """Describe the bounded output produced by one successful logical backup."""

    size_bytes: int


def _parameters_are_valid(
    service_name: object,
    output_descriptor: object,
    pg_dump_executable: object,
    timeout_seconds: object,
    connect_timeout_seconds: object,
) -> bool:
    """Return whether execution-authority parameters satisfy the narrow contract."""
    return (
        type(service_name) is str
        and _SERVICE_NAME_RE.fullmatch(service_name) is not None
        and type(output_descriptor) is int
        and output_descriptor >= 0
        and type(pg_dump_executable) is str
        and os.path.isabs(pg_dump_executable)
        and os.path.basename(pg_dump_executable) == "pg_dump"
        and type(timeout_seconds) is int
        and 1 <= timeout_seconds <= _MAX_TIMEOUT_SECONDS
        and type(connect_timeout_seconds) is int
        and 1 <= connect_timeout_seconds <= _MAX_CONNECT_TIMEOUT_SECONDS
    )


def _output_is_owner_only(mode: int) -> bool:
    """Return whether an output mode grants no group or other permissions."""
    return mode & (stat.S_IRWXG | stat.S_IRWXO) == 0


def _inspect_initial_output(output_descriptor: int) -> os.stat_result:
    """Require one private empty regular file through snapshotted descriptor authority."""
    try:
        status = os.fstat(output_descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_size != 0:
            raise PostgresLogicalBackupError(
                "PostgreSQL logical backup output must be a private empty regular file"
            )
        offset = os.lseek(output_descriptor, 0, os.SEEK_CUR)
    except PostgresLogicalBackupError:
        raise
    except (OSError, ValueError):
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output could not be inspected"
        ) from None

    if offset != 0:
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output must start at offset zero"
        )
    if not _output_is_owner_only(status.st_mode):
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output must be owner-only"
        )
    if status.st_nlink != 1:
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output must have one link"
        )
    if status.st_uid != os.geteuid():
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output must be owned by the effective process user"
        )
    return status


def _duplicate_output_for_cleanup(output_descriptor: int) -> int:
    """Snapshot caller output authority before inspection, execution, and cleanup."""
    try:
        return os.dup(output_descriptor)
    except (OSError, ValueError, OverflowError):
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output could not be retained"
        ) from None


def _open_independent_output(cleanup_descriptor: int) -> int:
    """Open the retained file with an independent offset for child execution."""
    try:
        return os.open(
            f"/proc/self/fd/{cleanup_descriptor}",
            os.O_WRONLY | getattr(os, "O_CLOEXEC", 0),
        )
    except (OSError, ValueError, OverflowError):
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output could not be isolated"
        ) from None


def _close_cleanup_descriptor(cleanup_descriptor: int) -> None:
    """Best-effort close package-owned output authority without replacing evidence."""
    try:
        os.close(cleanup_descriptor)
    except (OSError, ValueError):
        pass


def _libpq_environment(service_name: str, connect_timeout_seconds: int) -> dict[str, str]:
    """Return allowlisted libpq credentials plus package-owned connection authority."""
    environment = {
        key: os.environ[key]
        for key in _INHERITED_LIBPQ_VARIABLES
        if key in os.environ
    }
    environment["PGSERVICE"] = service_name
    environment["PGCONNECT_TIMEOUT"] = str(connect_timeout_seconds)
    return environment


def _invalidate_output(cleanup_descriptor: int) -> None:
    """Empty and rewind retained output or report content-free cleanup failure."""
    invalidation_failed = False
    try:
        os.ftruncate(cleanup_descriptor, 0)
    except (OSError, ValueError):
        invalidation_failed = True
    try:
        os.lseek(cleanup_descriptor, 0, os.SEEK_SET)
    except (OSError, ValueError):
        invalidation_failed = True
    if invalidation_failed:
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output could not be invalidated"
        ) from None


def _run_pg_dump(
    *,
    service_name: str,
    output_descriptor: int,
    cleanup_descriptor: int,
    pg_dump_executable: str,
    timeout_seconds: int,
    connect_timeout_seconds: int,
) -> subprocess.CompletedProcess[bytes]:
    """Run one shell-free pg_dump process with content-free diagnostics."""
    arguments = [
        pg_dump_executable,
        "--format=custom",
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
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup executable unavailable"
        ) from None
    except subprocess.TimeoutExpired:
        _invalidate_output(cleanup_descriptor)
        raise PostgresLogicalBackupError("PostgreSQL logical backup timed out") from None
    except Exception:
        _invalidate_output(cleanup_descriptor)
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup execution failed"
        ) from None
    except BaseException:
        try:
            _invalidate_output(cleanup_descriptor)
        except PostgresLogicalBackupError:
            pass
        raise

    if type(completed) is not subprocess.CompletedProcess:
        _invalidate_output(cleanup_descriptor)
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup execution failed"
        )
    if completed.returncode != 0:
        _invalidate_output(cleanup_descriptor)
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup command failed"
        )
    return completed


def _finalize_output(
    output_descriptor: int,
    cleanup_descriptor: int,
    initial_status: os.stat_result,
) -> int:
    """Synchronize and validate the snapshotted backup file after pg_dump exits."""
    try:
        os.fsync(cleanup_descriptor)
        status = os.fstat(output_descriptor)
    except (OSError, ValueError):
        _invalidate_output(cleanup_descriptor)
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output could not be finalized"
        ) from None

    if status.st_size <= 0:
        _invalidate_output(cleanup_descriptor)
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output is incomplete"
        )
    if (
        status.st_nlink != 1
        or not _output_is_owner_only(status.st_mode)
        or status.st_uid != initial_status.st_uid
    ):
        _invalidate_output(cleanup_descriptor)
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output became unsafe"
        )
    if (status.st_dev, status.st_ino) != (initial_status.st_dev, initial_status.st_ino):
        _invalidate_output(cleanup_descriptor)
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output changed during execution"
        )
    return status.st_size


def create_postgres_logical_backup(
    service_name: str,
    output_descriptor: int,
    *,
    pg_dump_executable: str,
    timeout_seconds: int = 1800,
    connect_timeout_seconds: int = 15,
) -> PostgresLogicalBackupResult:
    """Create one custom-format pg_dump into a pre-opened private regular file.

    The caller owns filesystem placement and descriptor lifetime. ``service_name`` is
    only a libpq service selector and is not a tenant authorization boundary. The
    package never receives an output path or places connection material in process
    arguments. Only ``PGPASSWORD``, ``PGPASSFILE``, and ``PGSERVICEFILE`` may be
    inherited; the package owns ``PGSERVICE`` and the bounded ``PGCONNECT_TIMEOUT``.
    Before output inspection, the package duplicates the caller descriptor for stable
    cleanup authority. It then reopens that retained file through ``/proc/self/fd`` so
    the child receives an independent open-file description and file offset. Replacing
    the caller descriptor number or seeking it after the snapshot therefore cannot
    redirect backup bytes or move the child's output position. Environments without
    this process-descriptor reopening boundary fail closed before ``pg_dump`` runs.
    """
    if not _parameters_are_valid(
        service_name,
        output_descriptor,
        pg_dump_executable,
        timeout_seconds,
        connect_timeout_seconds,
    ):
        raise PostgresLogicalBackupError(
            "invalid PostgreSQL logical backup parameters"
        )

    cleanup_descriptor = _duplicate_output_for_cleanup(output_descriptor)
    try:
        initial_status = _inspect_initial_output(cleanup_descriptor)
        execution_descriptor = _open_independent_output(cleanup_descriptor)
        try:
            _run_pg_dump(
                service_name=service_name,
                output_descriptor=execution_descriptor,
                cleanup_descriptor=cleanup_descriptor,
                pg_dump_executable=pg_dump_executable,
                timeout_seconds=timeout_seconds,
                connect_timeout_seconds=connect_timeout_seconds,
            )
            return PostgresLogicalBackupResult(
                size_bytes=_finalize_output(
                    execution_descriptor,
                    cleanup_descriptor,
                    initial_status,
                )
            )
        finally:
            _close_cleanup_descriptor(execution_descriptor)
    finally:
        _close_cleanup_descriptor(cleanup_descriptor)
