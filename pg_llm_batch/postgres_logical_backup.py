# SPDX-License-Identifier: Apache-2.0
"""Create time- and byte-bounded PostgreSQL logical backups."""

from __future__ import annotations

import fcntl
import os
import re
import stat
import subprocess
import threading
from dataclasses import dataclass


_SERVICE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_MAX_TIMEOUT_SECONDS = 86_400
_MAX_CONNECT_TIMEOUT_SECONDS = 60
_MAX_SIGNED_BIGINT = (1 << 63) - 1
_DEFAULT_MAXIMUM_OUTPUT_BYTES = 64 * 1024 * 1024 * 1024
_OUTPUT_CHUNK_BYTES = 1024 * 1024
_NONBLOCKING_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
_INHERITED_LIBPQ_VARIABLES = frozenset(
    {
        "PGPASSWORD",
        "PGPASSFILE",
        "PGSERVICEFILE",
    }
)


class PostgresLogicalBackupError(RuntimeError):
    """Report a fail-closed PostgreSQL logical-backup execution violation."""


class _OutputByteBudgetExceeded(Exception):
    """Signal that pg_dump crossed the validated output byte ceiling."""


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
    maximum_output_bytes: object,
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
        and type(maximum_output_bytes) is int
        and 1 <= maximum_output_bytes <= _MAX_SIGNED_BIGINT
    )


def _output_is_owner_only(mode: int) -> bool:
    """Return whether an output mode grants no group or other permissions."""
    return mode & (stat.S_IRWXG | stat.S_IRWXO) == 0


def _inspect_initial_output(output_descriptor: int) -> os.stat_result:
    """Require one private empty writable file through snapshotted descriptor authority."""
    try:
        status = os.fstat(output_descriptor)
        if not stat.S_ISREG(status.st_mode) or status.st_size != 0:
            raise PostgresLogicalBackupError(
                "PostgreSQL logical backup output must be a private empty regular file"
            )
        access_mode = fcntl.fcntl(output_descriptor, fcntl.F_GETFL) & os.O_ACCMODE
        offset = os.lseek(output_descriptor, 0, os.SEEK_CUR)
    except PostgresLogicalBackupError:
        raise
    except (OSError, ValueError):
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output could not be inspected"
        ) from None

    if access_mode not in (os.O_WRONLY, os.O_RDWR):
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output descriptor must be writable"
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
    """Open the retained file with an independent offset for package output."""
    try:
        return os.open(
            f"/proc/self/fd/{cleanup_descriptor}",
            os.O_WRONLY | getattr(os, "O_CLOEXEC", 0),
        )
    except (OSError, ValueError, OverflowError):
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output could not be isolated"
        ) from None


def _close_descriptor(file_descriptor: int) -> None:
    """Best-effort close package-owned descriptor authority without replacing evidence."""
    try:
        os.close(file_descriptor)
    except (OSError, ValueError):
        pass


def _retain_pg_dump_executable(pg_dump_executable: str) -> int:
    """Snapshot one root-owned non-set-id pg_dump executable inode before child use."""
    try:
        executable_descriptor = os.open(
            pg_dump_executable,
            _NONBLOCKING_READ_FLAGS,
        )
    except FileNotFoundError:
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup executable unavailable"
        ) from None
    except (OSError, ValueError):
        raise PostgresLogicalBackupError(
            "invalid PostgreSQL logical backup parameters"
        ) from None

    try:
        status = os.fstat(executable_descriptor)
    except (AttributeError, OSError, ValueError):
        _close_descriptor(executable_descriptor)
        raise PostgresLogicalBackupError(
            "invalid PostgreSQL logical backup parameters"
        ) from None

    if (
        not stat.S_ISREG(status.st_mode)
        or status.st_uid != 0
        or status.st_mode & (stat.S_IWGRP | stat.S_IWOTH | stat.S_ISUID | stat.S_ISGID)
        or status.st_mode & 0o111 == 0
    ):
        _close_descriptor(executable_descriptor)
        raise PostgresLogicalBackupError(
            "invalid PostgreSQL logical backup parameters"
        )
    return executable_descriptor


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
    """Durably empty and rewind retained output or report content-free cleanup failure."""
    invalidation_failed = False
    truncation_completed = False
    try:
        os.ftruncate(cleanup_descriptor, 0)
        truncation_completed = True
    except (OSError, ValueError):
        invalidation_failed = True
    try:
        os.lseek(cleanup_descriptor, 0, os.SEEK_SET)
    except (OSError, ValueError):
        invalidation_failed = True
    if truncation_completed:
        try:
            os.fsync(cleanup_descriptor)
        except (OSError, ValueError):
            invalidation_failed = True
    if invalidation_failed:
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output could not be invalidated"
        ) from None


def _write_all(output_descriptor: int, chunk: bytes) -> None:
    """Write one bounded chunk fully or report a private short-write failure."""
    remaining = memoryview(chunk)
    while remaining:
        written = os.write(output_descriptor, remaining)
        if written <= 0:
            raise OSError("short logical backup output write")
        remaining = remaining[written:]


def _copy_bounded_output(
    read_descriptor: int,
    output_descriptor: int,
    maximum_output_bytes: int,
    failures: list[BaseException],
) -> None:
    """Copy pg_dump bytes with bounded memory and finite output authority."""
    remaining = maximum_output_bytes
    try:
        while True:
            chunk = os.read(
                read_descriptor,
                min(_OUTPUT_CHUNK_BYTES, remaining + 1),
            )
            if not chunk:
                break
            if len(chunk) > remaining:
                _write_all(output_descriptor, chunk[:remaining])
                raise _OutputByteBudgetExceeded()
            _write_all(output_descriptor, chunk)
            remaining -= len(chunk)
    except BaseException as error:
        failures.append(error)
    finally:
        _close_descriptor(read_descriptor)


def _run_pg_dump(
    *,
    service_name: str,
    output_descriptor: int,
    cleanup_descriptor: int,
    pg_dump_descriptor: int,
    timeout_seconds: int,
    connect_timeout_seconds: int,
    maximum_output_bytes: int,
) -> subprocess.CompletedProcess[bytes]:
    """Run one retained shell-free pg_dump through a finite output-volume pipe."""
    arguments = [
        f"/proc/self/fd/{pg_dump_descriptor}",
        "--format=custom",
        "--no-password",
    ]
    environment = _libpq_environment(service_name, connect_timeout_seconds)
    try:
        read_descriptor, write_descriptor = os.pipe()
    except (OSError, ValueError):
        _invalidate_output(cleanup_descriptor)
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup execution failed"
        ) from None

    pump_failures: list[BaseException] = []
    try:
        pump_thread = threading.Thread(
            target=_copy_bounded_output,
            args=(
                read_descriptor,
                output_descriptor,
                maximum_output_bytes,
                pump_failures,
            ),
            name="pg-llm-batch-logical-backup-output",
            daemon=True,
        )
        pump_thread.start()
    except Exception:
        _close_descriptor(read_descriptor)
        _close_descriptor(write_descriptor)
        _invalidate_output(cleanup_descriptor)
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup execution failed"
        ) from None
    except BaseException:
        _close_descriptor(read_descriptor)
        _close_descriptor(write_descriptor)
        try:
            _invalidate_output(cleanup_descriptor)
        except PostgresLogicalBackupError:
            pass
        raise

    completed: object = None
    execution_error: BaseException | None = None
    try:
        completed = subprocess.run(
            arguments,
            stdout=write_descriptor,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            timeout=timeout_seconds,
            check=False,
            close_fds=True,
            pass_fds=(pg_dump_descriptor,),
            env=environment,
        )
    except BaseException as error:
        execution_error = error
    finally:
        _close_descriptor(write_descriptor)
        try:
            pump_thread.join()
        except BaseException:
            try:
                _invalidate_output(cleanup_descriptor)
            except PostgresLogicalBackupError:
                pass
            raise

    if (
        execution_error is not None
        and not isinstance(execution_error, Exception)
        and pump_failures
        and isinstance(pump_failures[0], Exception)
    ):
        try:
            _invalidate_output(cleanup_descriptor)
        except PostgresLogicalBackupError:
            pass
        raise execution_error

    if pump_failures:
        pump_failure = pump_failures[0]
        if not isinstance(pump_failure, Exception):
            try:
                _invalidate_output(cleanup_descriptor)
            except PostgresLogicalBackupError:
                pass
            raise pump_failure
        _invalidate_output(cleanup_descriptor)
        if type(pump_failure) is _OutputByteBudgetExceeded:
            raise PostgresLogicalBackupError(
                "PostgreSQL logical backup exceeded output byte budget"
            ) from None
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup execution failed"
        ) from None

    if execution_error is not None:
        if not isinstance(execution_error, Exception):
            try:
                _invalidate_output(cleanup_descriptor)
            except PostgresLogicalBackupError:
                pass
            raise execution_error
        _invalidate_output(cleanup_descriptor)
        if isinstance(execution_error, FileNotFoundError):
            raise PostgresLogicalBackupError(
                "PostgreSQL logical backup executable unavailable"
            ) from None
        if isinstance(execution_error, subprocess.TimeoutExpired):
            raise PostgresLogicalBackupError(
                "PostgreSQL logical backup timed out"
            ) from None
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup execution failed"
        ) from None

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
    maximum_output_bytes: int,
) -> int:
    """Synchronize and validate the same bounded backup file after pg_dump exits."""
    try:
        os.fsync(cleanup_descriptor)
        status = os.fstat(output_descriptor)
    except (OSError, ValueError):
        _invalidate_output(cleanup_descriptor)
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup output could not be finalized"
        ) from None

    if status.st_size > maximum_output_bytes:
        _invalidate_output(cleanup_descriptor)
        raise PostgresLogicalBackupError(
            "PostgreSQL logical backup exceeded output byte budget"
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
    maximum_output_bytes: int = _DEFAULT_MAXIMUM_OUTPUT_BYTES,
) -> PostgresLogicalBackupResult:
    """Create one time- and byte-bounded custom-format pg_dump.

    The caller owns filesystem placement and descriptor lifetime. ``service_name`` is
    only a libpq service selector and is not a tenant authorization boundary. The
    package never receives an output path or places connection material in process
    arguments. Only ``PGPASSWORD``, ``PGPASSFILE``, and ``PGSERVICEFILE`` may be
    inherited; the package owns ``PGSERVICE`` and the bounded ``PGCONNECT_TIMEOUT``.
    ``maximum_output_bytes`` is a strict finite ceiling on provider bytes accepted by
    the package and on final output size. It defaults to 64 GiB and may be raised only
    to a validated signed-64-bit ceiling. Provider bytes cross a package-owned pipe and
    are copied with bounded memory; excess bytes are never published, and any overrun
    invalidates the retained output.

    Before output inspection, the package duplicates the caller descriptor for stable
    cleanup authority. That retained descriptor must itself carry write access; the
    package never uses ``/proc/self/fd`` to widen a caller's read-only capability. It
    then reopens that retained file through ``/proc/self/fd`` so package copying uses
    an independent open-file description and file offset. Replacing the caller
    descriptor number or seeking it after the snapshot therefore cannot redirect
    backup bytes or move the package output position. The absolute ``pg_dump`` token
    is opened non-blocking without following its final symlink, rejected unless it is
    a root-owned regular executable without group/other write or set-user-ID/set-group-ID
    authority, and executed only through the retained descriptor. This Linux
    system-package boundary prevents a non-root service account from retaining chmod,
    in-place rewrite, or executable set-id authority to the validated bytes.
    Environments without these process-descriptor boundaries fail closed before
    ``pg_dump`` runs.
    """
    if not _parameters_are_valid(
        service_name,
        output_descriptor,
        pg_dump_executable,
        timeout_seconds,
        connect_timeout_seconds,
        maximum_output_bytes,
    ):
        raise PostgresLogicalBackupError(
            "invalid PostgreSQL logical backup parameters"
        )

    cleanup_descriptor = _duplicate_output_for_cleanup(output_descriptor)
    try:
        initial_status = _inspect_initial_output(cleanup_descriptor)
        execution_descriptor = _open_independent_output(cleanup_descriptor)
        try:
            pg_dump_descriptor = _retain_pg_dump_executable(pg_dump_executable)
            try:
                _run_pg_dump(
                    service_name=service_name,
                    output_descriptor=execution_descriptor,
                    cleanup_descriptor=cleanup_descriptor,
                    pg_dump_descriptor=pg_dump_descriptor,
                    timeout_seconds=timeout_seconds,
                    connect_timeout_seconds=connect_timeout_seconds,
                    maximum_output_bytes=maximum_output_bytes,
                )
                return PostgresLogicalBackupResult(
                    size_bytes=_finalize_output(
                        execution_descriptor,
                        cleanup_descriptor,
                        initial_status,
                        maximum_output_bytes,
                    )
                )
            finally:
                _close_descriptor(pg_dump_descriptor)
        finally:
            _close_descriptor(execution_descriptor)
    finally:
        _close_descriptor(cleanup_descriptor)
