# SPDX-License-Identifier: Apache-2.0
"""Bind a caller-owned PostgreSQL data-directory descriptor to cluster identity.

This module deliberately accepts file descriptors rather than filesystem paths.
The caller owns both the data-directory descriptor and the trusted
``pg_controldata`` executable descriptor.  The verifier snapshots those
capabilities onto private descriptors before validation and child-process use,
suppresses diagnostics that could contain host information, bounds execution
time and captured output, and compares the one reported PostgreSQL system
identifier with an independently collected restore identity.
"""

from __future__ import annotations

import os
import stat
import subprocess

from .postgres_restore_target import PostgresRestoreTargetIdentity


_MAX_SYSTEM_IDENTIFIER = (1 << 64) - 1
_MAX_SYSTEM_IDENTIFIER_DIGITS = 20
_MAX_CONTROL_OUTPUT_BYTES = 16_384
_CONTROL_TIMEOUT_SECONDS = 5.0
_INVALID_INPUT = "invalid PostgreSQL data-directory identity inputs"
_INSPECTION_FAILED = "could not inspect PostgreSQL data-directory identity"
_IDENTITY_MISMATCH = "PostgreSQL data directory does not match restore target identity"
_IDENTIFIER_PREFIX = "Database system identifier:"


class PostgresDataDirectoryIdentityError(ValueError):
    """Report a content-free data-directory identity verification failure."""


def _raise_invalid_input() -> None:
    """Raise the fixed diagnostic for invalid caller-owned capabilities."""
    raise PostgresDataDirectoryIdentityError(_INVALID_INPUT)


def _raise_inspection_failed() -> None:
    """Raise the fixed diagnostic for untrusted or unavailable tool output."""
    raise PostgresDataDirectoryIdentityError(_INSPECTION_FAILED)


def _is_plain_descriptor(value: object) -> bool:
    """Return whether ``value`` is an exact non-negative file descriptor."""
    return type(value) is int and value >= 0


def _is_expected_identity(value: object) -> bool:
    """Return whether ``value`` is an exact valid restore-target identity."""
    return (
        type(value) is PostgresRestoreTargetIdentity
        and type(value.system_identifier) is int
        and 1 <= value.system_identifier <= _MAX_SYSTEM_IDENTIFIER
    )


def _duplicate_descriptor_or_invalid(file_descriptor: int) -> int:
    """Snapshot one caller descriptor or cross the fixed invalid-input boundary."""
    try:
        return os.dup(file_descriptor)
    except (OSError, OverflowError):
        _raise_invalid_input()


def _close_snapshot_descriptor(file_descriptor: int) -> None:
    """Best-effort close one package-owned descriptor without masking evidence."""
    try:
        os.close(file_descriptor)
    except (OSError, ValueError):
        pass


def _fstat_or_invalid(file_descriptor: int) -> os.stat_result:
    """Inspect one open descriptor or cross the fixed invalid-input boundary."""
    try:
        return os.fstat(file_descriptor)
    except OSError:
        _raise_invalid_input()


def _validate_snapshot(
    *,
    data_directory_fd: int,
    pg_controldata_fd: int,
    expected_identity: PostgresRestoreTargetIdentity,
) -> PostgresRestoreTargetIdentity:
    """Validate privately owned descriptor snapshots and the expected identity."""
    data_stat = _fstat_or_invalid(data_directory_fd)
    control_stat = _fstat_or_invalid(pg_controldata_fd)

    if not stat.S_ISDIR(data_stat.st_mode):
        _raise_invalid_input()
    if not stat.S_ISREG(control_stat.st_mode):
        _raise_invalid_input()
    if control_stat.st_mode & 0o111 == 0:
        _raise_invalid_input()

    return expected_identity


def _inspect_system_identifier(*, data_directory_fd: int, pg_controldata_fd: int) -> int:
    """Run the trusted control utility through two inherited FD capabilities."""
    command = (
        f"/proc/self/fd/{pg_controldata_fd}",
        "-D",
        f"/proc/self/fd/{data_directory_fd}",
    )
    try:
        result = subprocess.run(
            command,
            pass_fds=(pg_controldata_fd, data_directory_fd),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=_CONTROL_TIMEOUT_SECONDS,
            cwd="/",
            env={"LANG": "C", "LC_ALL": "C", "PG_COLOR": "never"},
            close_fds=True,
        )
    except (OSError, subprocess.TimeoutExpired):
        _raise_inspection_failed()

    if result.returncode != 0:
        _raise_inspection_failed()
    if type(result.stdout) is not bytes:
        _raise_inspection_failed()
    if len(result.stdout) > _MAX_CONTROL_OUTPUT_BYTES:
        _raise_inspection_failed()

    try:
        text = result.stdout.decode("ascii")
    except UnicodeDecodeError:
        _raise_inspection_failed()

    identifiers = [
        line.removeprefix(_IDENTIFIER_PREFIX).strip()
        for line in text.splitlines()
        if line.startswith(_IDENTIFIER_PREFIX)
    ]
    if len(identifiers) != 1:
        _raise_inspection_failed()

    raw_identifier = identifiers[0]
    if (
        not raw_identifier
        or not raw_identifier.isascii()
        or not raw_identifier.isdecimal()
        or len(raw_identifier) > _MAX_SYSTEM_IDENTIFIER_DIGITS
    ):
        _raise_inspection_failed()

    identifier = int(raw_identifier, 10)
    if not 1 <= identifier <= _MAX_SYSTEM_IDENTIFIER:
        _raise_inspection_failed()
    return identifier


def verify_postgres_data_directory_identity(
    *,
    data_directory_fd: int,
    pg_controldata_fd: int,
    expected_identity: PostgresRestoreTargetIdentity,
) -> None:
    """Fail closed unless a data directory has the expected cluster identity.

    ``expected_identity`` must be the exact protected
    :class:`~pg_llm_batch.postgres_restore_target.PostgresRestoreTargetIdentity`
    previously collected from the isolated restore cluster.  Exact integer
    descriptor arguments are duplicated before either descriptor is validated,
    so later replacement of the caller-owned descriptor numbers cannot change
    the capabilities used by this verification call. Package-owned duplicates
    are released best-effort after verification so close-time operating-system
    diagnostics cannot replace a verified result or leak host detail. The
    function does not accept a path, DSN, password, WAL segment, tenant
    identifier, or business payload. It does not start PostgreSQL, configure
    recovery, replay WAL, or claim that the directory is otherwise safe to
    promote.
    """
    if not _is_plain_descriptor(data_directory_fd):
        _raise_invalid_input()
    if not _is_plain_descriptor(pg_controldata_fd):
        _raise_invalid_input()
    if not _is_expected_identity(expected_identity):
        _raise_invalid_input()

    data_snapshot_fd = _duplicate_descriptor_or_invalid(data_directory_fd)
    try:
        control_snapshot_fd = _duplicate_descriptor_or_invalid(pg_controldata_fd)
        try:
            identity = _validate_snapshot(
                data_directory_fd=data_snapshot_fd,
                pg_controldata_fd=control_snapshot_fd,
                expected_identity=expected_identity,
            )
            observed_identifier = _inspect_system_identifier(
                data_directory_fd=data_snapshot_fd,
                pg_controldata_fd=control_snapshot_fd,
            )
            if observed_identifier != identity.system_identifier:
                raise PostgresDataDirectoryIdentityError(_IDENTITY_MISMATCH)
        finally:
            _close_snapshot_descriptor(control_snapshot_fd)
    finally:
        _close_snapshot_descriptor(data_snapshot_fd)
