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
    """Require a caller-owned descriptor for one private empty regular file."""
    try:
        status = os.fstat(output_descriptor)
        offset = os.lseek(output_descriptor, 0, os.SEEK_CUR)
    except (OSError, ValueError):
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output could not be inspected"
        ) from None

    if not stat.S_ISREG(status.st_mode) or status.st_size != 0:
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output must be a private empty regular file"
        )
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
    return status


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


def _invalidate_output(output_descriptor: int) -> None:
    """Best-effort empty and rewind a partial dump without replacing a primary error."""
    try:
        os.ftruncate(output_descriptor, 0)
    except (OSError, ValueError):
        pass
    try:
        os.lseek(output_descriptor, 0, os.SEEK_SET)
    except (OSError, ValueError):
        pass


def _run_pg_dump(
    *,
    service_name: str,
    output_descriptor: int,
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
        _invalidate_output(output_descriptor)
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup executable unavailable"
        ) from None
    except subprocess.TimeoutExpired:
        _invalidate_output(output_descriptor)
        raise PostgresLogicalBackupError("PostgreSQL logical backup timed out") from None
    except Exception:
        _invalidate_output(output_descriptor)
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup execution failed"
        ) from None
    except BaseException:
        _invalidate_output(output_descriptor)
        raise

    if type(completed) is not subprocess.CompletedProcess:
        _invalidate_output(output_descriptor)
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup execution failed"
        )
    if completed.returncode != 0:
        _invalidate_output(output_descriptor)
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup command failed"
        )
    return completed


def _finalize_output(output_descriptor: int) -> int:
    """Synchronize and validate the caller-owned backup file after pg_dump exits."""
    try:
        os.fsync(output_descriptor)
        status = os.fstat(output_descriptor)
    except (OSError, ValueError):
        _invalidate_output(output_descriptor)
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output could not be finalized"
        ) from None

    if status.st_size <= 0:
        _invalidate_output(output_descriptor)
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output is incomplete"
        )
    if status.st_nlink != 1 or not _output_is_owner_only(status.st_mode):
        _invalidate_output(output_descriptor)
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output became unsafe"
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
    Any partial output selected by this function is emptied and rewound best-effort on
    failure so the caller can safely decide whether to retry or discard the descriptor.
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

    _inspect_initial_output(output_descriptor)
    _run_pg_dump(
        service_name=service_name,
        output_descriptor=output_descriptor,
        pg_dump_executable=pg_dump_executable,
        timeout_seconds=timeout_seconds,
        connect_timeout_seconds=connect_timeout_seconds,
    )
    return PostgresLogicalBackupResult(
        size_bytes=_finalize_output(output_descriptor)
    )
