# SPDX-License-Identifier: Apache-2.0
"""Create a bounded PostgreSQL ``recovery.signal`` for an isolated target."""

from __future__ import annotations

import os
import secrets
import stat

from .postgres_restore_target import (
    PostgresRestoreTargetError,
    PostgresRestoreTargetIdentity,
    verify_postgres_restore_target_isolation,
)


_RECOVERY_SIGNAL = "recovery.signal"
_STANDBY_SIGNAL = "standby.signal"
_QUARANTINE_PREFIX = ".pg_llm_batch-unverified-recovery-signal-"
_SIGNAL_MODE = 0o600


class PostgresRecoverySignalError(RuntimeError):
    """Report a fail-closed PostgreSQL recovery-signal preparation violation."""


def _verify_restore_isolation(
    *,
    live_service_name: str,
    restore_service_name: str,
    live_target_identity: PostgresRestoreTargetIdentity,
    restore_target_identity: PostgresRestoreTargetIdentity,
) -> None:
    """Map restore-target validation to one content-free recovery-signal error."""
    try:
        verify_postgres_restore_target_isolation(
            live_service_name=live_service_name,
            restore_service_name=restore_service_name,
            live_target_identity=live_target_identity,
            restore_target_identity=restore_target_identity,
        )
    except PostgresRestoreTargetError:
        raise PostgresRecoverySignalError(
            "PostgreSQL recovery target is not isolated"
        ) from None


def _close_directory_descriptor(directory_descriptor: int) -> None:
    """Best-effort close one package-owned data-directory snapshot."""
    try:
        os.close(directory_descriptor)
    except (OSError, ValueError):
        pass


def _snapshot_directory_descriptor(data_directory_descriptor: object) -> int:
    """Privately snapshot and validate one caller-owned directory capability."""
    if type(data_directory_descriptor) is not int or data_directory_descriptor < 0:
        raise PostgresRecoverySignalError(
            "invalid PostgreSQL recovery signal parameters"
        )
    try:
        directory_descriptor = os.dup(data_directory_descriptor)
    except (OSError, ValueError):
        raise PostgresRecoverySignalError(
            "PostgreSQL recovery data directory could not be inspected"
        ) from None
    try:
        status = os.fstat(directory_descriptor)
    except (OSError, ValueError):
        _close_directory_descriptor(directory_descriptor)
        raise PostgresRecoverySignalError(
            "PostgreSQL recovery data directory could not be inspected"
        ) from None
    if not stat.S_ISDIR(status.st_mode):
        _close_directory_descriptor(directory_descriptor)
        raise PostgresRecoverySignalError(
            "PostgreSQL recovery data directory descriptor is not a directory"
        )
    return directory_descriptor


def _entry_status(directory_descriptor: int, entry_name: str) -> os.stat_result | None:
    """Return one relative entry status without following a symbolic link."""
    try:
        return os.stat(
            entry_name,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except FileNotFoundError:
        return None
    except (OSError, ValueError):
        raise PostgresRecoverySignalError(
            "PostgreSQL recovery signal state could not be inspected"
        ) from None


def _require_signal_state_absent(directory_descriptor: int) -> None:
    """Refuse pre-existing recovery state and PostgreSQL standby-mode precedence."""
    if _entry_status(directory_descriptor, _STANDBY_SIGNAL) is not None:
        raise PostgresRecoverySignalError(
            "PostgreSQL standby signal prevents isolated recovery preparation"
        )
    if _entry_status(directory_descriptor, _RECOVERY_SIGNAL) is not None:
        raise PostgresRecoverySignalError(
            "PostgreSQL recovery signal already exists"
        )


def _open_recovery_signal(directory_descriptor: int) -> int:
    """Exclusively create an empty relative recovery signal without following links."""
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_CLOEXEC | os.O_NOFOLLOW
    try:
        return os.open(
            _RECOVERY_SIGNAL,
            flags,
            _SIGNAL_MODE,
            dir_fd=directory_descriptor,
        )
    except FileExistsError:
        raise PostgresRecoverySignalError(
            "PostgreSQL recovery signal already exists"
        ) from None
    except (OSError, ValueError):
        raise PostgresRecoverySignalError(
            "PostgreSQL recovery signal could not be created"
        ) from None


def _capture_created_signal_identity(signal_descriptor: int) -> tuple[int, int]:
    """Capture identity before any later hardening step can fail."""
    try:
        status = os.fstat(signal_descriptor)
    except (OSError, ValueError):
        raise PostgresRecoverySignalError(
            "PostgreSQL recovery signal identity could not be captured"
        ) from None
    if not (
        stat.S_ISREG(status.st_mode)
        and status.st_size == 0
        and status.st_nlink == 1
    ):
        raise PostgresRecoverySignalError(
            "PostgreSQL recovery signal is not an empty regular file"
        )
    return status.st_dev, status.st_ino


def _harden_created_signal(
    signal_descriptor: int,
    created_identity: tuple[int, int],
) -> None:
    """Force private mode and re-verify the exact created descriptor identity."""
    try:
        os.fchmod(signal_descriptor, _SIGNAL_MODE)
        status = os.fstat(signal_descriptor)
    except (OSError, ValueError):
        raise PostgresRecoverySignalError(
            "PostgreSQL recovery signal could not be inspected"
        ) from None
    if not (
        stat.S_ISREG(status.st_mode)
        and status.st_size == 0
        and stat.S_IMODE(status.st_mode) == _SIGNAL_MODE
        and status.st_nlink == 1
        and (status.st_dev, status.st_ino) == created_identity
    ):
        raise PostgresRecoverySignalError(
            "PostgreSQL recovery signal is not a private empty regular file"
        )


def _require_created_path_identity(
    directory_descriptor: int,
    created_identity: tuple[int, int],
) -> None:
    """Fail closed if the relative signal path no longer names the created inode."""
    status = _entry_status(directory_descriptor, _RECOVERY_SIGNAL)
    if status is None or (status.st_dev, status.st_ino) != created_identity:
        raise PostgresRecoverySignalError(
            "PostgreSQL recovery signal changed during preparation"
        )


def _sync_descriptor(descriptor: int) -> None:
    """Synchronize one signal or directory descriptor with content-free failure."""
    try:
        os.fsync(descriptor)
    except (OSError, ValueError):
        raise PostgresRecoverySignalError(
            "PostgreSQL recovery signal could not be synchronized"
        ) from None


def _cleanup_created_signal(
    directory_descriptor: int,
    created_identity: tuple[int, int],
) -> None:
    """Best-effort unlink only the exact signal inode created by this invocation."""
    try:
        status = os.stat(
            _RECOVERY_SIGNAL,
            dir_fd=directory_descriptor,
            follow_symlinks=False,
        )
    except (FileNotFoundError, OSError, ValueError):
        return
    if (status.st_dev, status.st_ino) != created_identity:
        return
    try:
        os.unlink(_RECOVERY_SIGNAL, dir_fd=directory_descriptor)
    except (FileNotFoundError, OSError, ValueError):
        return
    try:
        os.fsync(directory_descriptor)
    except (OSError, ValueError):
        pass


def _quarantine_unverified_signal(directory_descriptor: int) -> None:
    """Atomically move an unverified trigger to an inert content-free quarantine name."""
    quarantine_name = f"{_QUARANTINE_PREFIX}{secrets.token_hex(32)}"
    try:
        os.rename(
            _RECOVERY_SIGNAL,
            quarantine_name,
            src_dir_fd=directory_descriptor,
            dst_dir_fd=directory_descriptor,
        )
        os.fsync(directory_descriptor)
    except (OSError, ValueError):
        raise PostgresRecoverySignalError(
            "PostgreSQL recovery trigger could not be quarantined after inspection failure"
        ) from None


def _close_signal_descriptor(signal_descriptor: int) -> None:
    """Best-effort close the package-owned signal descriptor after final evidence."""
    try:
        os.close(signal_descriptor)
    except (OSError, ValueError):
        pass


def prepare_postgres_recovery_signal(
    data_directory_descriptor: int,
    *,
    live_service_name: str,
    restore_service_name: str,
    live_target_identity: PostgresRestoreTargetIdentity,
    restore_target_identity: PostgresRestoreTargetIdentity,
) -> None:
    """Create ``recovery.signal`` only for a caller-verified isolated restore target.

    The caller supplies an already-open PostgreSQL data-directory descriptor and the
    same live/restore service names and cluster identities used by the protected
    restore-target isolation contract. Isolation is checked before package filesystem
    mutation. The package duplicates the caller's directory descriptor before it is
    validated or used, so later replacement of the caller-owned descriptor number
    cannot redirect this invocation's relative filesystem operations. The private
    snapshot is closed before return. The package receives no directory path, DSN,
    password, restore command, WAL content, tenant scope, or business content.

    A pre-existing ``recovery.signal`` is never adopted or truncated. A present
    ``standby.signal`` is rejected because PostgreSQL gives standby mode precedence
    when both files exist. The new signal is created relative to the private directory
    capability with exclusive/no-follow semantics. Its descriptor identity is captured
    before permission hardening so a later failure can remove only that exact inode.
    If initial descriptor inspection fails before ownership can be proved, the package
    atomically renames the trigger to a high-entropy package-reserved quarantine name
    and synchronizes the directory instead of deleting unverified bytes or leaving
    PostgreSQL's magic recovery trigger published. A quarantine failure is surfaced as
    an explicit content-free error so callers know not to start the restore cluster.
    If process control interrupts initial identity capture, that signal remains primary
    even when the quarantine attempt also fails; the bounded cleanup error is chained.

    After identity capture, the signal is forced to owner read/write mode, re-verified
    as the same empty one-link regular inode, synchronized, rechecked against a standby
    race, and followed by a directory synchronization. Any later failure attempts
    cleanup only when the relative path still names the exact created inode.

    This seam does not prove that the supplied directory descriptor belongs to the
    restore cluster represented by ``restore_target_identity``; that mapping remains
    caller/deployer authority. It does not configure ``restore_command``, start or
    promote PostgreSQL, replay WAL, prove archive continuity, or establish RPO/RTO,
    HA, DR, CSAP, or SOC 2 capability.
    """
    _verify_restore_isolation(
        live_service_name=live_service_name,
        restore_service_name=restore_service_name,
        live_target_identity=live_target_identity,
        restore_target_identity=restore_target_identity,
    )
    directory_descriptor = _snapshot_directory_descriptor(data_directory_descriptor)
    try:
        _require_signal_state_absent(directory_descriptor)
        signal_descriptor = _open_recovery_signal(directory_descriptor)
        try:
            created_identity = _capture_created_signal_identity(signal_descriptor)
        except BaseException as primary_error:
            _close_signal_descriptor(signal_descriptor)
            try:
                _quarantine_unverified_signal(directory_descriptor)
            except BaseException as cleanup_error:
                if isinstance(primary_error, (KeyboardInterrupt, SystemExit)):
                    raise primary_error from cleanup_error
                raise
            raise
        try:
            _harden_created_signal(signal_descriptor, created_identity)
            _require_created_path_identity(directory_descriptor, created_identity)
            _sync_descriptor(signal_descriptor)
            if _entry_status(directory_descriptor, _STANDBY_SIGNAL) is not None:
                raise PostgresRecoverySignalError(
                    "PostgreSQL standby signal prevents isolated recovery preparation"
                )
            _require_created_path_identity(directory_descriptor, created_identity)
            _sync_descriptor(directory_descriptor)
        except BaseException:
            _cleanup_created_signal(directory_descriptor, created_identity)
            raise
        finally:
            _close_signal_descriptor(signal_descriptor)
    finally:
        _close_directory_descriptor(directory_descriptor)
