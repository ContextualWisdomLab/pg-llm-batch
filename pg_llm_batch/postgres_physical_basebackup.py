# SPDX-License-Identifier: Apache-2.0
"""Create time- and byte-bounded PostgreSQL physical backups through a tar stream."""

from __future__ import annotations

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
_INHERITED_LIBPQ_VARIABLES = frozenset(
    {
        "PGPASSWORD",
        "PGPASSFILE",
        "PGSERVICEFILE",
    }
)


class PostgresPhysicalBaseBackupError(RuntimeError):
    """Report a fail-closed PostgreSQL physical base-backup execution violation."""


class _OutputByteBudgetExceeded(Exception):
    """Signal that one provider stream crossed its validated byte ceiling."""


@dataclass(frozen=True, slots=True)
class PostgresPhysicalBaseBackupResult:
    """Describe the byte size produced by one successful physical base backup."""

    size_bytes: int


def _parameters_are_valid(
    service_name: object,
    output_descriptor: object,
    pg_basebackup_executable: object,
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
        and type(pg_basebackup_executable) is str
        and os.path.isabs(pg_basebackup_executable)
        and os.path.basename(pg_basebackup_executable) == "pg_basebackup"
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
    """Retain a private descriptor to the selected backup file."""
    try:
        return os.dup(output_descriptor)
    except (OSError, OverflowError, ValueError):
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup output could not be retained"
        ) from None


def _open_independent_output(cleanup_descriptor: int) -> int:
    """Open retained output with an independent open-file description and offset."""
    try:
        return os.open(
            f"/proc/self/fd/{cleanup_descriptor}",
            os.O_WRONLY | getattr(os, "O_CLOEXEC", 0),
        )
    except (OSError, OverflowError, ValueError):
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup output could not be isolated"
        ) from None


def _close_cleanup_descriptor(cleanup_descriptor: int) -> None:
    """Best-effort close a package-owned descriptor without replacing primary evidence."""
    try:
        os.close(cleanup_descriptor)
    except (OSError, ValueError):
        pass


def _retain_pg_basebackup_executable(pg_basebackup_executable: str) -> int:
    """Fail closed unless root-owned executable inode authority can be retained."""
    try:
        executable_descriptor = os.open(
            pg_basebackup_executable,
            os.O_RDONLY | getattr(os, "O_CLOEXEC", 0),
        )
    except (OSError, ValueError):
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup executable is unsafe"
        ) from None

    try:
        try:
            status = os.fstat(executable_descriptor)
        except (OSError, ValueError):
            raise PostgresPhysicalBaseBackupError(
                "PostgreSQL physical base-backup executable is unsafe"
            ) from None
        if (
            not stat.S_ISREG(status.st_mode)
            or status.st_uid != 0
            or status.st_mode & (stat.S_IWGRP | stat.S_IWOTH)
            or status.st_mode & (stat.S_ISUID | stat.S_ISGID)
            or status.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH) == 0
        ):
            raise PostgresPhysicalBaseBackupError(
                "PostgreSQL physical base-backup executable is unsafe"
            )
    except BaseException:
        _close_cleanup_descriptor(executable_descriptor)
        raise
    return executable_descriptor


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
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup output could not be invalidated"
        ) from None


def _copy_bounded_output(
    read_descriptor: int,
    output_descriptor: int,
    maximum_output_bytes: int,
    failures: list[BaseException],
) -> None:
    """Copy a provider pipe to private output using bounded memory and byte authority."""
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
                permitted = chunk[:remaining]
                if os.write(output_descriptor, permitted) != len(permitted):
                    raise OSError("short physical backup output write")
                raise _OutputByteBudgetExceeded()
            if os.write(output_descriptor, chunk) != len(chunk):
                raise OSError("short physical backup output write")
            remaining -= len(chunk)
    except BaseException as error:
        failures.append(error)
    finally:
        _close_cleanup_descriptor(read_descriptor)


def _run_pg_basebackup(
    *,
    service_name: str,
    output_descriptor: int,
    cleanup_descriptor: int,
    pg_basebackup_executable: str,
    executable_descriptor: int,
    timeout_seconds: int,
    connect_timeout_seconds: int,
    maximum_output_bytes: int,
) -> subprocess.CompletedProcess[bytes]:
    """Run one shell-free tar base backup through a finite output-volume pipe."""
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
        read_descriptor, write_descriptor = os.pipe()
        pipe_status = os.fstat(write_descriptor)
        pipe_identity = (
            pipe_status.st_dev,
            pipe_status.st_ino,
            stat.S_IFMT(pipe_status.st_mode),
        )
    except (OSError, ValueError):
        for descriptor in locals().get("read_descriptor"), locals().get("write_descriptor"):
            if type(descriptor) is int:
                _close_cleanup_descriptor(descriptor)
        _invalidate_output(cleanup_descriptor)
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup execution failed"
        ) from None

    pump_failures: list[BaseException] = []
    pump_thread = threading.Thread(
        target=_copy_bounded_output,
        args=(
            read_descriptor,
            output_descriptor,
            maximum_output_bytes,
            pump_failures,
        ),
        name="pg-llm-batch-physical-backup-output",
        daemon=True,
    )
    try:
        pump_thread.start()
    except Exception:
        _close_cleanup_descriptor(read_descriptor)
        _close_cleanup_descriptor(write_descriptor)
        _invalidate_output(cleanup_descriptor)
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup execution failed"
        ) from None

    completed: object = None
    execution_error: BaseException | None = None
    pipe_changed = False
    try:
        completed = subprocess.run(
            arguments,
            stdout=write_descriptor,
            stderr=subprocess.DEVNULL,
            stdin=subprocess.DEVNULL,
            timeout=timeout_seconds,
            check=False,
            close_fds=True,
            env=environment,
            executable=f"/proc/self/fd/{executable_descriptor}",
            pass_fds=(executable_descriptor,),
        )
    except BaseException as error:
        execution_error = error
    finally:
        if execution_error is None:
            try:
                current_pipe_status = os.fstat(write_descriptor)
                pipe_changed = (
                    current_pipe_status.st_dev,
                    current_pipe_status.st_ino,
                    stat.S_IFMT(current_pipe_status.st_mode),
                ) != pipe_identity
            except (OSError, ValueError):
                pipe_changed = True
        _close_cleanup_descriptor(write_descriptor)
        try:
            pump_thread.join()
        except BaseException:
            _close_cleanup_descriptor(read_descriptor)
            try:
                _invalidate_output(cleanup_descriptor)
            except PostgresPhysicalBaseBackupError:
                pass
            raise

    if execution_error is not None and not isinstance(execution_error, Exception):
        try:
            _invalidate_output(cleanup_descriptor)
        except PostgresPhysicalBaseBackupError:
            pass
        raise execution_error

    if pipe_changed:
        _invalidate_output(cleanup_descriptor)
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup output changed during execution"
        ) from None

    if pump_failures:
        pump_failure = pump_failures[0]
        if not isinstance(pump_failure, Exception):
            try:
                _invalidate_output(cleanup_descriptor)
            except PostgresPhysicalBaseBackupError:
                pass
            raise pump_failure
        _invalidate_output(cleanup_descriptor)
        if type(pump_failure) is _OutputByteBudgetExceeded:
            raise PostgresPhysicalBaseBackupError(
                "PostgreSQL physical base backup exceeded output byte budget"
            ) from None
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup execution failed"
        ) from None

    if execution_error is not None:
        _invalidate_output(cleanup_descriptor)
        if isinstance(execution_error, FileNotFoundError):
            raise PostgresPhysicalBaseBackupError(
                "PostgreSQL physical base-backup executable unavailable"
            ) from None
        if isinstance(execution_error, subprocess.TimeoutExpired):
            raise PostgresPhysicalBaseBackupError(
                "PostgreSQL physical base backup timed out"
            ) from None
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup execution failed"
        ) from None

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
    maximum_output_bytes: int,
) -> int:
    """Synchronize and validate the same bounded private file after pg_basebackup exits."""
    try:
        os.fsync(cleanup_descriptor)
        status = os.fstat(output_descriptor)
    except (OSError, ValueError):
        _invalidate_output(cleanup_descriptor)
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base-backup output could not be finalized"
        ) from None

    if status.st_size > maximum_output_bytes:
        _invalidate_output(cleanup_descriptor)
        raise PostgresPhysicalBaseBackupError(
            "PostgreSQL physical base backup exceeded output byte budget"
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
    maximum_output_bytes: int = _DEFAULT_MAXIMUM_OUTPUT_BYTES,
) -> PostgresPhysicalBaseBackupResult:
    """Create one time- and byte-bounded full-cluster tar backup with required WAL.

    The output is the tar stream emitted by ``pg_basebackup --pgdata=- --format=tar``
    with ``--wal-method=fetch``. PostgreSQL therefore fails this narrow mode when the
    source has additional tablespaces; this seam intentionally does not accept
    tablespace mappings or server-side output paths. The caller owns filesystem
    placement and descriptor lifetime and must treat the bytes as highly sensitive
    cluster material. The package never receives an output path and never places
    connection material in process arguments.

    ``maximum_output_bytes`` is a strict finite ceiling for provider bytes accepted by
    the package and for the selected output size observed at finalization. It defaults
    to 64 GiB and may be raised through an exact positive integer up to signed-bigint
    range when the caller has provisioned a larger private destination. Provider stdout
    is drained through a package-owned pipe in bounded-memory chunks; the copier reads
    at most one byte beyond the remaining allowance to detect an overrun, never
    publishes that extra byte, closes the provider pipe on overrun, and durably
    invalidates partial output. A provider that continues after the pipe is closed
    remains subject to the existing command timeout and ``subprocess.run``
    termination/reaping behavior. The caller retains its own file authority, so this
    boundary does not prevent caller mutation after successful return or claim host
    filesystem capacity/quota enforcement.

    ``service_name`` is a libpq service selector, not a tenant authorization boundary.
    Only ``PGPASSWORD``, ``PGPASSFILE``, and ``PGSERVICEFILE`` may be inherited; the
    package owns ``PGSERVICE`` and the bounded ``PGCONNECT_TIMEOUT``. The source role
    and server still must satisfy PostgreSQL's replication-protocol prerequisites.
    A SHA-256 backup manifest is requested and pg_basebackup's normal durable-sync
    behavior is retained; this function additionally fsyncs the caller-owned stream.

    The output descriptor is privately snapshotted before inspection. The selected
    file is then reopened through ``/proc/self/fd`` so the package-owned output copier
    has an independent open-file description and file offset. Replacing, closing, or
    seeking the caller-owned descriptor after the snapshot therefore cannot redirect
    backup bytes, move the private output offset, or redirect final validation.
    Environments unable to establish that process-descriptor reopening boundary fail
    closed before ``pg_basebackup`` runs. The selected executable inode must be a
    root-owned regular file with at least one execute bit, no set-user-ID or
    set-group-ID bits, and no group/other write authority and remains retained through
    subprocess creation, so a non-root service account cannot rewrite the validated
    inode or gain privilege-transition authority through the selected executable.

    Successful execution proves only that PostgreSQL produced one physical base-backup
    tar containing WAL required for backup consistency within the configured time and
    output-byte ceilings. It does not establish a continuous WAL archive, perform WAL
    replay/PITR, prove restore usability, recover external keys/configuration/provider
    state, or establish deployment RPO/RTO.
    """
    if not _parameters_are_valid(
        service_name,
        output_descriptor,
        pg_basebackup_executable,
        timeout_seconds,
        connect_timeout_seconds,
        maximum_output_bytes,
    ):
        raise PostgresPhysicalBaseBackupError(
            "invalid PostgreSQL physical base-backup parameters"
        )

    cleanup_descriptor = _duplicate_output_for_cleanup(output_descriptor)
    try:
        initial_status = _inspect_initial_output(cleanup_descriptor)
        executable_descriptor = _retain_pg_basebackup_executable(pg_basebackup_executable)
        try:
            execution_descriptor = _open_independent_output(cleanup_descriptor)
            try:
                _run_pg_basebackup(
                    service_name=service_name,
                    output_descriptor=execution_descriptor,
                    cleanup_descriptor=cleanup_descriptor,
                    pg_basebackup_executable=pg_basebackup_executable,
                    executable_descriptor=executable_descriptor,
                    timeout_seconds=timeout_seconds,
                    connect_timeout_seconds=connect_timeout_seconds,
                    maximum_output_bytes=maximum_output_bytes,
                )
                return PostgresPhysicalBaseBackupResult(
                    size_bytes=_finalize_output(
                        execution_descriptor,
                        cleanup_descriptor,
                        initial_status,
                        maximum_output_bytes,
                    )
                )
            finally:
                _close_cleanup_descriptor(execution_descriptor)
        finally:
            _close_cleanup_descriptor(executable_descriptor)
    finally:
        _close_cleanup_descriptor(cleanup_descriptor)
