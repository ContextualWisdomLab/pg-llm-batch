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


def _snapshot_expected_identity_or_invalid(value: object) -> int:
    """Snapshot one exact valid restore-target identifier or fail closed."""
    if type(value) is not PostgresRestoreTargetIdentity:
        _raise_invalid_input()
    system_identifier = value.system_identifier
    if (
        type(system_identifier) is not int
        or not 1 <= system_identifier <= _MAX_SYSTEM_IDENTIFIER
    ):
        _raise_invalid_input()
    return system_identifier


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


def _validate_snapshot(*, data_directory_fd: int, pg_controldata_fd: int) -> None:
    """Validate privately owned descriptor snapshots."""
    data_stat = _fstat_or_invalid(data_directory_fd)
    control_stat = _fstat_or_invalid(pg_controldata_fd)
    effective_user_id = os.geteuid()

    if not stat.S_ISDIR(data_stat.st_mode):
        _raise_invalid_input()
    if data_stat.st_uid != effective_user_id:
        _raise_invalid_input()
    if data_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        _raise_invalid_input()
    if not stat.S_ISREG(control_stat.st_mode):
        _raise_invalid_input()
    if control_stat.st_uid != 0:
        _raise_invalid_input()
    if control_stat.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
        _raise_invalid_input()
    if control_stat.st_mode & 0o111 == 0:
        _raise_invalid_input()


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
    previously collected from the isolated restore cluster. The verifier
    snapshots its bounded system identifier before invoking child-process or
    operating-system work, so later caller mutation cannot rewrite accepted
    identity authority. Exact integer descriptor arguments are duplicated
    before either descriptor is validated, so later replacement of the
    caller-owned descriptor numbers cannot change the capabilities used by
    this verification call. The retained data directory must be owned by the
    effective process user; the retained ``pg_controldata`` executable must be
    a root-owned regular executable with no group/other write authority. This
    Linux system-package boundary prevents a non-root service account from
    retaining chmod or in-place rewrite authority to the validated executable
    inode. The data directory also rejects group/other write authority while
    permitting PostgreSQL-compatible read/search sharing. Package-owned
    duplicates are released best-effort after verification so close-time
    operating-system diagnostics cannot replace a verified result or leak host
    detail. The function does not accept a path, DSN, password, WAL segment,
    tenant identifier, or business payload. It does not start PostgreSQL,
    configure recovery, replay WAL, or claim that the directory is otherwise
    safe to promote.
    """
    if not _is_plain_descriptor(data_directory_fd):
        _raise_invalid_input()
    if not _is_plain_descriptor(pg_controldata_fd):
        _raise_invalid_input()
    expected_system_identifier = _snapshot_expected_identity_or_invalid(
        expected_identity
    )

    data_snapshot_fd = _duplicate_descriptor_or_invalid(data_directory_fd)
    try:
        control_snapshot_fd = _duplicate_descriptor_or_invalid(pg_controldata_fd)
        try:
            _validate_snapshot(
                data_directory_fd=data_snapshot_fd,
                pg_controldata_fd=control_snapshot_fd,
            )
            observed_identifier = _inspect_system_identifier(
                data_directory_fd=data_snapshot_fd,
                pg_controldata_fd=control_snapshot_fd,
            )
            if observed_identifier != expected_system_identifier:
                raise PostgresDataDirectoryIdentityError(_IDENTITY_MISMATCH)
        finally:
            _close_snapshot_descriptor(control_snapshot_fd)
    finally:
        _close_snapshot_descriptor(data_snapshot_fd)
