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
_MAX_ARCHIVE_BYTES = 1024**4
_DEFAULT_ARCHIVE_BYTES = 64 * 1024**3
_NONBLOCKING_READ_FLAGS = os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK
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


@dataclass(frozen=True, slots=True, init=False)
class PostgresWalArchiveResult:
    """Record a requested end LSN without asserting that the receiver reached it."""

    requested_end_lsn: str

    def __init__(
        self,
        requested_end_lsn: str | None = None,
        *,
        end_lsn: str | None = None,
    ) -> None:
        """Build request-only evidence; ``end_lsn`` is a compatibility input alias."""
        object.__setattr__(
            self,
            "requested_end_lsn",
            requested_end_lsn if requested_end_lsn is not None else end_lsn,
        )


def _parameters_are_valid(
    service_name: object,
    slot_name: object,
    end_lsn: object,
    archive_directory_descriptor: object,
    pg_receivewal_executable: object,
    maximum_archive_bytes: object,
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
        and type(maximum_archive_bytes) is int
        and 1 <= maximum_archive_bytes <= _MAX_ARCHIVE_BYTES
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


def _close_descriptor(file_descriptor: int) -> None:
    """Best-effort close package-owned authority without replacing evidence."""
    try:
        os.close(file_descriptor)
    except (OSError, ValueError):
        pass


def _retain_pg_receivewal_executable(pg_receivewal_executable: str) -> int:
    """Retain one root-owned non-set-id pg_receivewal executable inode."""
    try:
        executable_descriptor = os.open(
            pg_receivewal_executable,
            _NONBLOCKING_READ_FLAGS,
        )
    except FileNotFoundError:
        raise PostgresWalArchiveError(
            "PostgreSQL WAL archive executable unavailable"
        ) from None
    except (OSError, ValueError):
        raise PostgresWalArchiveError(
            "invalid PostgreSQL WAL archive parameters"
        ) from None

    try:
        status = os.fstat(executable_descriptor)
    except (AttributeError, OSError, ValueError):
        _close_descriptor(executable_descriptor)
        raise PostgresWalArchiveError(
            "invalid PostgreSQL WAL archive parameters"
        ) from None
    if (
        not stat.S_ISREG(status.st_mode)
        or status.st_uid != 0
        or status.st_mode
        & (stat.S_IWGRP | stat.S_IWOTH | stat.S_ISUID | stat.S_ISGID)
        or status.st_mode & 0o111 == 0
    ):
        _close_descriptor(executable_descriptor)
        raise PostgresWalArchiveError(
            "invalid PostgreSQL WAL archive parameters"
        )
    return executable_descriptor


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


def _inspect_archive_filesystem_budget(
    archive_directory_descriptor: int,
    maximum_archive_bytes: int,
) -> int:
    """Require an isolated filesystem whose total data capacity fits the byte budget."""
    try:
        archive_status = os.fstat(archive_directory_descriptor)
        parent_status = os.stat(
            "..",
            dir_fd=archive_directory_descriptor,
            follow_symlinks=False,
        )
        filesystem_status = os.fstatvfs(archive_directory_descriptor)
        fragment_size = filesystem_status.f_frsize
        block_count = filesystem_status.f_blocks
        if (
            type(fragment_size) is not int
            or fragment_size <= 0
            or type(block_count) is not int
            or block_count < 0
        ):
            raise ValueError
        capacity_bytes = fragment_size * block_count
    except (AttributeError, OSError, OverflowError, TypeError, ValueError):
        raise PostgresWalArchiveError(
            "PostgreSQL WAL archive filesystem budget could not be inspected"
        ) from None

    if parent_status.st_dev == archive_status.st_dev:
        raise PostgresWalArchiveError(
            "PostgreSQL WAL archive requires an isolated bounded filesystem"
        )
    if capacity_bytes > maximum_archive_bytes:
        raise PostgresWalArchiveError(
            "PostgreSQL WAL archive filesystem exceeds configured byte budget"
        )
    return capacity_bytes


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
    pg_receivewal_descriptor: int,
    timeout_seconds: int,
    connect_timeout_seconds: int,
) -> subprocess.CompletedProcess[bytes]:
    """Run synchronous bounded WAL reception with one requested end-position limit."""
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
            executable=f"/proc/self/fd/{pg_receivewal_descriptor}",
            pass_fds=tuple(
                dict.fromkeys(
                    (archive_directory_descriptor, pg_receivewal_descriptor)
                )
            ),
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
    maximum_archive_bytes: int = _DEFAULT_ARCHIVE_BYTES,
    timeout_seconds: int = 7200,
    connect_timeout_seconds: int = 15,
) -> PostgresWalArchiveResult:
    """Receive a bounded PostgreSQL WAL stream through an existing replication slot.

    The caller owns an already-open private archive directory descriptor and the
    lifecycle of its WAL files. The package snapshots that descriptor into private
    authority before inspection and subprocess execution, so later caller-side close or
    descriptor-number replacement cannot redirect this invocation. The directory must
    be empty at invocation start so pre-existing local WAL state cannot choose
    ``pg_receivewal``'s starting position. Emptiness inspection consumes at most one
    directory entry rather than materializing attacker-influenced directory contents.
    The retained directory must also be the root of a distinct filesystem whose total
    data-block capacity is no larger than ``maximum_archive_bytes``. This kernel-backed
    boundary constrains aggregate receiver output across all WAL segment files without
    directory enumeration, symlink traversal, or a per-file-only resource limit. The
    subprocess sees only the package-owned pinned directory as ``/proc/self/fd/<fd>``;
    no caller filesystem path or connection secret is placed in argv. The absolute
    ``pg_receivewal`` token is opened non-blocking without following its final symlink,
    rejected unless it is a root-owned regular executable with at least one execute bit
    and without group/other write or set-user-ID/set-group-ID authority, and executed
    only through the retained descriptor. This Linux system-package boundary prevents a
    non-root service account from retaining rewrite authority and prevents a pathname
    swap from changing the child executable bytes. The selected replication slot must
    already exist and remain an operator-governed server resource. The package never
    creates or drops slots.

    ``pg_receivewal`` is invoked with ``--synchronous`` so received WAL is flushed in
    real time, ``--no-loop`` so connection loss is returned to the caller rather than
    retried indefinitely, and ``--endpos`` to request a finite endpoint. The package's
    timeout remains the hard execution bound. It also sets a stable application name,
    and callers must ensure that server ``synchronous_standby_names`` policy does not
    select this receiver when ``synchronous_commit=remote_apply``.

    A zero receiver exit status proves only that ``pg_receivewal`` reported a successful
    process exit while the pinned archive directory retained its reviewed owner,
    permissions, identity, and bounded-filesystem authority. PostgreSQL also exits
    ``pg_receivewal`` with status zero after handled ``SIGINT``/``SIGTERM``; once the
    child handles such a signal, ``subprocess.CompletedProcess`` does not preserve that
    completion cause. Therefore the returned result records only the requested end LSN
    and must not be treated as evidence that it was reached. Exact reach, gap-free WAL
    continuity, segment integrity, timeline ancestry, replay/PITR, and deployment
    RPO/RTO require independent evidence.
    """
    if not _parameters_are_valid(
        service_name,
        slot_name,
        end_lsn,
        archive_directory_descriptor,
        pg_receivewal_executable,
        maximum_archive_bytes,
        timeout_seconds,
        connect_timeout_seconds,
    ):
        raise PostgresWalArchiveError(
            "invalid PostgreSQL WAL archive parameters"
        )

    private_archive_descriptor = _retain_archive_directory(archive_directory_descriptor)
    try:
        initial_status = _inspect_archive_directory(private_archive_descriptor)
        _inspect_archive_filesystem_budget(
            private_archive_descriptor,
            maximum_archive_bytes,
        )
        executable_descriptor = _retain_pg_receivewal_executable(
            pg_receivewal_executable
        )
        try:
            _run_pg_receivewal(
                service_name=service_name,
                slot_name=slot_name,
                end_lsn=end_lsn,
                archive_directory_descriptor=private_archive_descriptor,
                pg_receivewal_executable=pg_receivewal_executable,
                pg_receivewal_descriptor=executable_descriptor,
                timeout_seconds=timeout_seconds,
                connect_timeout_seconds=connect_timeout_seconds,
            )
            _finalize_archive_directory(private_archive_descriptor, initial_status)
            return PostgresWalArchiveResult(requested_end_lsn=end_lsn)
        finally:
            _close_descriptor(executable_descriptor)
    finally:
        _close_descriptor(private_archive_descriptor)
