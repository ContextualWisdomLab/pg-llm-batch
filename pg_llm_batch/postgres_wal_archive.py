# SPDX-License-Identifier: Apache-2.0
"""Receive PostgreSQL WAL through a bounded replication stream."""

from __future__ import annotations

import os
import re
import stat
import subprocess
from dataclasses import dataclass


_SERVICE_NAME_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,63}\Z")
_SLOT_NAME_RE = re.compile(r"[a-z0-9_]{1,63}\Z")
_LSN_RE = re.compile(r"[0-9A-F]{1,8}/[0-9A-F]{1,8}\Z")
_MAX_TIMEOUT_SECONDS = 86_400
_MAX_CONNECT_TIMEOUT_SECONDS = 60
_INHERITED_LIBPQ_VARIABLES = frozenset(
    {
        "PGPASSWORD",
        "PGPASSFILE",
        "PGSERVICEFILE",
    }
)
_APPLICATION_NAME = "pg_llm_batch_wal_archive"


class PostgresWalArchiveError(RuntimeError):
    """Report a fail-closed PostgreSQL WAL archive execution violation."""


@dataclass(frozen=True, slots=True)
class PostgresWalArchiveResult:
    """Describe the reviewed end LSN reached by one successful WAL receive run."""

    end_lsn: str


def _parameters_are_valid(
    service_name: object,
    slot_name: object,
    end_lsn: object,
    archive_directory_descriptor: object,
    pg_receivewal_executable: object,
    timeout_seconds: object,
    connect_timeout_seconds: object,
) -> bool:
    """Return whether execution-authority parameters satisfy the bounded contract."""
    return (
        type(service_name) is str
        and _SERVICE_NAME_RE.fullmatch(service_name) is not None
        and type(slot_name) is str
        and _SLOT_NAME_RE.fullmatch(slot_name) is not None
        and type(end_lsn) is str
        and _LSN_RE.fullmatch(end_lsn) is not None
        and int(end_lsn.replace("/", ""), 16) != 0
        and type(archive_directory_descriptor) is int
        and archive_directory_descriptor >= 0
        and type(pg_receivewal_executable) is str
        and os.path.isabs(pg_receivewal_executable)
        and os.path.basename(pg_receivewal_executable) == "pg_receivewal"
        and type(timeout_seconds) is int
        and 1 <= timeout_seconds <= _MAX_TIMEOUT_SECONDS
        and type(connect_timeout_seconds) is int
        and 1 <= connect_timeout_seconds <= _MAX_CONNECT_TIMEOUT_SECONDS
    )


def _directory_is_owner_only(mode: int) -> bool:
    """Return whether a directory mode grants no group or other permissions."""
    return mode & (stat.S_IRWXG | stat.S_IRWXO) == 0


def _retain_archive_directory(archive_directory_descriptor: int) -> int:
    """Snapshot caller directory authority into one package-owned descriptor."""
    try:
        return os.dup(archive_directory_descriptor)
    except (OSError, OverflowError, ValueError):
        raise PostgresWalArchiveError(
            "PostgreSQL WAL archive directory could not be retained"
        ) from None


def _close_archive_directory(archive_directory_descriptor: int) -> None:
    """Best-effort close package-owned directory authority without replacing evidence."""
    try:
        os.close(archive_directory_descriptor)
    except (OSError, ValueError):
        pass


def _inspect_archive_directory(
    archive_directory_descriptor: int,
) -> os.stat_result:
    """Require a process-owned, private, initially empty directory pinned by an open fd."""
    try:
        status = os.fstat(archive_directory_descriptor)
        effective_user_id = os.geteuid()
    except (AttributeError, OSError, ValueError):
        raise PostgresWalArchiveError(
            "PostgreSQL WAL archive directory could not be inspected"
        ) from None
    if not stat.S_ISDIR(status.st_mode):
        raise PostgresWalArchiveError(
            "PostgreSQL WAL archive output must be a private directory"
        )
    if status.st_uid != effective_user_id:
        raise PostgresWalArchiveError(
            "PostgreSQL WAL archive directory must be owned by the effective process user"
        )
    if not _directory_is_owner_only(status.st_mode):
        raise PostgresWalArchiveError(
            "PostgreSQL WAL archive directory must be owner-only"
        )
    try:
        with os.scandir(archive_directory_descriptor) as directory_entries:
            has_entry = next(directory_entries, None) is not None
    except (OSError, ValueError):
        raise PostgresWalArchiveError(
            "PostgreSQL WAL archive directory could not be inspected"
        ) from None
    if has_entry:
        raise PostgresWalArchiveError(
            "PostgreSQL WAL archive directory must start empty"
        )
    return status


def _libpq_environment(service_name: str, connect_timeout_seconds: int) -> dict[str, str]:
    """Return allowlisted credential sources plus package-owned connection authority."""
    environment = {
        key: os.environ[key]
        for key in _INHERITED_LIBPQ_VARIABLES
        if key in os.environ
    }
    environment["PGSERVICE"] = service_name
    environment["PGCONNECT_TIMEOUT"] = str(connect_timeout_seconds)
    environment["PGAPPNAME"] = _APPLICATION_NAME
    return environment


def _run_pg_receivewal(
    *,
    service_name: str,
    slot_name: str,
    end_lsn: str,
    archive_directory_descriptor: int,
    pg_receivewal_executable: str,
    timeout_seconds: int,
    connect_timeout_seconds: int,
) -> subprocess.CompletedProcess[bytes]:
    """Receive synchronously flushed WAL to one pinned directory through an existing slot."""
    arguments = [
        pg_receivewal_executable,
        f"--directory=/proc/self/fd/{archive_directory_descriptor}",
        f"--endpos={end_lsn}",
        f"--slot={slot_name}",
        "--synchronous",
        "--no-loop",
        "--no-password",
    ]
    environment = _libpq_environment(service_name, connect_timeout_seconds)
    try:
        completed = subprocess.run(
            arguments,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=timeout_seconds,
            check=False,
            close_fds=True,
            pass_fds=(archive_directory_descriptor,),
            env=environment,
        )
    except FileNotFoundError:
        raise PostgresWalArchiveError(
            "PostgreSQL WAL archive executable unavailable"
        ) from None
    except subprocess.TimeoutExpired:
        raise PostgresWalArchiveError(
            "PostgreSQL WAL archive reception timed out"
        ) from None
    except Exception:
        raise PostgresWalArchiveError(
            "PostgreSQL WAL archive execution failed"
        ) from None
    except BaseException:
        raise
    if type(completed) is not subprocess.CompletedProcess:
        raise PostgresWalArchiveError(
            "PostgreSQL WAL archive execution failed"
        )
    if completed.returncode != 0:
        raise PostgresWalArchiveError(
            "PostgreSQL WAL archive command failed"
        )
    return completed


def _finalize_archive_directory(
    archive_directory_descriptor: int,
    initial_status: os.stat_result,
) -> None:
    """Synchronize directory entries and require the same private owner identity."""
    try:
        os.fsync(archive_directory_descriptor)
        status = os.fstat(archive_directory_descriptor)
    except (OSError, ValueError):
        raise PostgresWalArchiveError(
            "PostgreSQL WAL archive directory could not be finalized"
        ) from None
    if status.st_uid != initial_status.st_uid or not _directory_is_owner_only(status.st_mode):
        raise PostgresWalArchiveError(
            "PostgreSQL WAL archive directory became unsafe"
        )
    if not stat.S_ISDIR(status.st_mode) or (
        status.st_dev,
        status.st_ino,
    ) != (
        initial_status.st_dev,
        initial_status.st_ino,
    ):
        raise PostgresWalArchiveError(
            "PostgreSQL WAL archive directory changed during execution"
        )


def receive_postgres_wal_archive(
    service_name: str,
    slot_name: str,
    end_lsn: str,
    archive_directory_descriptor: int,
    *,
    pg_receivewal_executable: str,
    timeout_seconds: int = 7200,
    connect_timeout_seconds: int = 15,
) -> PostgresWalArchiveResult:
    """Receive a finite PostgreSQL WAL stream through an existing replication slot.

    The caller owns an already-open private archive directory descriptor and the
    lifecycle of its WAL files. The package snapshots that descriptor into private
    authority before inspection and subprocess execution, so later caller-side close or
    descriptor-number replacement cannot redirect this invocation. The directory must
    be empty at invocation start so pre-existing local WAL state cannot choose
    ``pg_receivewal``'s starting position. Emptiness inspection consumes at most one
    directory entry rather than materializing attacker-influenced directory contents.
    The subprocess sees only the package-owned pinned directory as
    ``/proc/self/fd/<fd>``; no caller filesystem path or connection secret is placed in
    argv. The selected replication slot must already exist and remain an
    operator-governed server resource. The package never creates or drops slots.

    ``pg_receivewal`` is invoked with ``--synchronous`` so received WAL is flushed in
    real time, ``--no-loop`` so connection loss is returned to the caller rather than
    retried indefinitely, and an exact ``--endpos`` LSN so a successful invocation is
    finite. The package sets a stable application name and callers must ensure that
    server ``synchronous_standby_names`` policy does not select this receiver when
    ``synchronous_commit=remote_apply``.

    Success proves only that ``pg_receivewal`` exited successfully after reaching the
    requested end LSN while the pinned archive directory retained its reviewed owner,
    permissions, and identity. It does not prove a gap-free archive before the slot's
    retained start, validate every WAL segment, configure ``restore_command``, replay
    WAL, execute PITR, or establish deployment RPO/RTO.
    """
    if not _parameters_are_valid(
        service_name,
        slot_name,
        end_lsn,
        archive_directory_descriptor,
        pg_receivewal_executable,
        timeout_seconds,
        connect_timeout_seconds,
    ):
        raise PostgresWalArchiveError(
            "invalid PostgreSQL WAL archive parameters"
        )

    private_archive_descriptor = _retain_archive_directory(archive_directory_descriptor)
    try:
        initial_status = _inspect_archive_directory(private_archive_descriptor)
        _run_pg_receivewal(
            service_name=service_name,
            slot_name=slot_name,
            end_lsn=end_lsn,
            archive_directory_descriptor=private_archive_descriptor,
            pg_receivewal_executable=pg_receivewal_executable,
            timeout_seconds=timeout_seconds,
            connect_timeout_seconds=connect_timeout_seconds,
        )
        _finalize_archive_directory(private_archive_descriptor, initial_status)
        return PostgresWalArchiveResult(end_lsn=end_lsn)
    finally:
        _close_archive_directory(private_archive_descriptor)
