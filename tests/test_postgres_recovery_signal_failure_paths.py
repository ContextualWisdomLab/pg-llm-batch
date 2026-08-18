# SPDX-License-Identifier: Apache-2.0
"""Failure-path coverage for bounded PostgreSQL recovery-signal preparation."""

from __future__ import annotations

import os
import stat
from pathlib import Path
from types import SimpleNamespace

import pytest

import pg_llm_batch.postgres_recovery_signal as recovery_signal
from pg_llm_batch.postgres_recovery_signal import PostgresRecoverySignalError
from pg_llm_batch.postgres_restore_target import PostgresRestoreTargetIdentity


def _identity(value: int) -> PostgresRestoreTargetIdentity:
    """Return one caller-owned PostgreSQL cluster identity for a test."""
    return PostgresRestoreTargetIdentity(system_identifier=value)


def _directory_descriptor(path: Path) -> int:
    """Open one caller-owned directory descriptor for a test."""
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY)


def _prepare(directory_descriptor: int) -> None:
    """Prepare a signal with distinct live and restore cluster identities."""
    recovery_signal.prepare_postgres_recovery_signal(
        directory_descriptor,
        live_service_name="live-db",
        restore_service_name="restore-drill",
        live_target_identity=_identity(101),
        restore_target_identity=_identity(202),
    )


def test_directory_descriptor_inspection_failure_is_content_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Map a directory-descriptor inspection failure without leaking its detail."""
    directory_descriptor = _directory_descriptor(tmp_path)

    def fail_fstat(descriptor: int) -> os.stat_result:
        del descriptor
        raise OSError("sensitive directory diagnostic")

    monkeypatch.setattr(recovery_signal.os, "fstat", fail_fstat)
    try:
        with pytest.raises(PostgresRecoverySignalError) as caught:
            _prepare(directory_descriptor)
    finally:
        os.close(directory_descriptor)

    assert str(caught.value) == (
        "PostgreSQL recovery data directory could not be inspected"
    )
    assert not (tmp_path / "recovery.signal").exists()


def test_signal_state_inspection_failure_is_content_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Map a relative-entry inspection failure without leaking its detail."""
    directory_descriptor = _directory_descriptor(tmp_path)

    def fail_stat(*args: object, **kwargs: object) -> os.stat_result:
        del args, kwargs
        raise OSError("sensitive signal-state diagnostic")

    monkeypatch.setattr(recovery_signal.os, "stat", fail_stat)
    try:
        with pytest.raises(PostgresRecoverySignalError) as caught:
            _prepare(directory_descriptor)
    finally:
        os.close(directory_descriptor)

    assert str(caught.value) == (
        "PostgreSQL recovery signal state could not be inspected"
    )


def test_create_race_maps_file_exists_to_bounded_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Treat an O_EXCL create race as existing recovery state."""
    directory_descriptor = _directory_descriptor(tmp_path)
    real_open = recovery_signal.os.open

    def race_open(
        path: str,
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if path == "recovery.signal":
            raise FileExistsError("sensitive competing-path diagnostic")
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(recovery_signal.os, "open", race_open)
    try:
        with pytest.raises(PostgresRecoverySignalError) as caught:
            _prepare(directory_descriptor)
    finally:
        os.close(directory_descriptor)

    assert str(caught.value) == "PostgreSQL recovery signal already exists"


def test_directory_snapshot_dup_failure_is_content_free(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Map failure to duplicate the caller capability without leaking diagnostics."""
    directory_descriptor = _directory_descriptor(tmp_path)

    def fail_dup(descriptor: int) -> int:
        assert descriptor == directory_descriptor
        raise OSError("sensitive descriptor duplication diagnostic")

    monkeypatch.setattr(recovery_signal.os, "dup", fail_dup)
    try:
        with pytest.raises(PostgresRecoverySignalError) as caught:
            _prepare(directory_descriptor)
    finally:
        os.close(directory_descriptor)

    assert str(caught.value) == (
        "PostgreSQL recovery data directory could not be inspected"
    )
    assert not (tmp_path / "recovery.signal").exists()


def test_initial_signal_identity_inspection_failure_closes_without_blind_unlink(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Preserve an unproven path when the just-opened inode cannot be inspected."""
    directory_descriptor = _directory_descriptor(tmp_path)
    real_fstat = recovery_signal.os.fstat

    def fail_signal_fstat(descriptor: int) -> os.stat_result:
        status = real_fstat(descriptor)
        if stat.S_ISDIR(status.st_mode):
            return status
        raise OSError("sensitive created-inode diagnostic")

    monkeypatch.setattr(recovery_signal.os, "fstat", fail_signal_fstat)
    try:
        with pytest.raises(PostgresRecoverySignalError) as caught:
            _prepare(directory_descriptor)
    finally:
        os.close(directory_descriptor)

    assert str(caught.value) == (
        "PostgreSQL recovery signal identity could not be captured"
    )
    assert (tmp_path / "recovery.signal").exists()


def test_initial_signal_identity_rejects_nonempty_created_file_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Reject an untrusted initial descriptor state before claiming cleanup ownership."""
    directory_descriptor = _directory_descriptor(tmp_path)
    real_fstat = recovery_signal.os.fstat

    def nonempty_signal_fstat(descriptor: int) -> os.stat_result | SimpleNamespace:
        status = real_fstat(descriptor)
        if stat.S_ISDIR(status.st_mode):
            return status
        return SimpleNamespace(
            st_mode=status.st_mode,
            st_size=1,
            st_nlink=status.st_nlink,
            st_dev=status.st_dev,
            st_ino=status.st_ino,
        )

    monkeypatch.setattr(recovery_signal.os, "fstat", nonempty_signal_fstat)
    try:
        with pytest.raises(PostgresRecoverySignalError) as caught:
            _prepare(directory_descriptor)
    finally:
        os.close(directory_descriptor)

    assert str(caught.value) == (
        "PostgreSQL recovery signal is not an empty regular file"
    )
    assert (tmp_path / "recovery.signal").exists()


def test_post_hardening_state_mismatch_removes_exact_created_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Remove the owned inode if its post-hardening descriptor state is invalid."""
    directory_descriptor = _directory_descriptor(tmp_path)
    real_fstat = recovery_signal.os.fstat
    signal_inspections = 0

    def changed_signal_fstat(descriptor: int) -> os.stat_result | SimpleNamespace:
        nonlocal signal_inspections
        status = real_fstat(descriptor)
        if stat.S_ISDIR(status.st_mode):
            return status
        signal_inspections += 1
        if signal_inspections == 1:
            return status
        return SimpleNamespace(
            st_mode=status.st_mode,
            st_size=1,
            st_nlink=status.st_nlink,
            st_dev=status.st_dev,
            st_ino=status.st_ino,
        )

    monkeypatch.setattr(recovery_signal.os, "fstat", changed_signal_fstat)
    try:
        with pytest.raises(PostgresRecoverySignalError) as caught:
            _prepare(directory_descriptor)
    finally:
        os.close(directory_descriptor)

    assert str(caught.value) == (
        "PostgreSQL recovery signal is not a private empty regular file"
    )
    assert not (tmp_path / "recovery.signal").exists()


def test_path_disappearance_after_create_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail if the created recovery path disappears before durability evidence."""
    directory_descriptor = _directory_descriptor(tmp_path)
    real_stat = recovery_signal.os.stat
    recovery_lookups = 0

    def disappearing_stat(
        path: str,
        *args: object,
        **kwargs: object,
    ) -> os.stat_result:
        nonlocal recovery_lookups
        if path == "recovery.signal":
            recovery_lookups += 1
            if recovery_lookups == 2:
                os.unlink(path, dir_fd=kwargs.get("dir_fd"))
                raise FileNotFoundError(path)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(recovery_signal.os, "stat", disappearing_stat)
    try:
        with pytest.raises(PostgresRecoverySignalError, match="changed during"):
            _prepare(directory_descriptor)
    finally:
        os.close(directory_descriptor)

    assert not (tmp_path / "recovery.signal").exists()


def test_path_identity_replacement_after_create_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail if the recovery path no longer names the exact created inode."""
    directory_descriptor = _directory_descriptor(tmp_path)
    real_stat = recovery_signal.os.stat
    recovery_lookups = 0

    def replaced_stat(
        path: str,
        *args: object,
        **kwargs: object,
    ) -> os.stat_result | SimpleNamespace:
        nonlocal recovery_lookups
        if path == "recovery.signal":
            recovery_lookups += 1
            if recovery_lookups == 2:
                return SimpleNamespace(st_dev=-1, st_ino=-1)
        return real_stat(path, *args, **kwargs)

    monkeypatch.setattr(recovery_signal.os, "stat", replaced_stat)
    try:
        with pytest.raises(PostgresRecoverySignalError, match="changed during"):
            _prepare(directory_descriptor)
    finally:
        os.close(directory_descriptor)

    assert not (tmp_path / "recovery.signal").exists()


def test_cleanup_ignores_uninspectable_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never unlink when cleanup cannot inspect the relative path identity."""
    signal_path = tmp_path / "recovery.signal"
    signal_path.write_bytes(b"")
    status = signal_path.lstat()
    directory_descriptor = _directory_descriptor(tmp_path)

    def fail_stat(*args: object, **kwargs: object) -> os.stat_result:
        del args, kwargs
        raise OSError("sensitive cleanup diagnostic")

    monkeypatch.setattr(recovery_signal.os, "stat", fail_stat)
    try:
        recovery_signal._cleanup_created_signal(
            directory_descriptor,
            (status.st_dev, status.st_ino),
        )
    finally:
        os.close(directory_descriptor)

    monkeypatch.undo()
    assert stat.S_ISREG(signal_path.lstat().st_mode)


def test_cleanup_preserves_path_with_different_identity(tmp_path: Path) -> None:
    """Never unlink a relative path that does not match the owned inode identity."""
    signal_path = tmp_path / "recovery.signal"
    signal_path.write_bytes(b"")
    directory_descriptor = _directory_descriptor(tmp_path)
    try:
        recovery_signal._cleanup_created_signal(directory_descriptor, (-1, -1))
    finally:
        os.close(directory_descriptor)

    assert signal_path.exists()


def test_cleanup_tolerates_unlink_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Keep best-effort cleanup from replacing the primary preparation failure."""
    signal_path = tmp_path / "recovery.signal"
    signal_path.write_bytes(b"")
    status = signal_path.lstat()
    directory_descriptor = _directory_descriptor(tmp_path)

    def fail_unlink(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError("sensitive unlink diagnostic")

    monkeypatch.setattr(recovery_signal.os, "unlink", fail_unlink)
    try:
        recovery_signal._cleanup_created_signal(
            directory_descriptor,
            (status.st_dev, status.st_ino),
        )
    finally:
        os.close(directory_descriptor)

    assert stat.S_ISREG(signal_path.lstat().st_mode)


def test_cleanup_tolerates_directory_sync_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Do not replace the primary failure if post-unlink directory sync also fails."""
    signal_path = tmp_path / "recovery.signal"
    signal_path.write_bytes(b"")
    status = signal_path.lstat()
    directory_descriptor = _directory_descriptor(tmp_path)

    def fail_fsync(descriptor: int) -> None:
        del descriptor
        raise OSError("sensitive cleanup sync diagnostic")

    monkeypatch.setattr(recovery_signal.os, "fsync", fail_fsync)
    try:
        recovery_signal._cleanup_created_signal(
            directory_descriptor,
            (status.st_dev, status.st_ino),
        )
    finally:
        os.close(directory_descriptor)

    with pytest.raises(FileNotFoundError):
        signal_path.lstat()


def test_close_directory_descriptor_is_best_effort() -> None:
    """Ignore close failure while releasing the package-owned directory snapshot."""
    recovery_signal._close_directory_descriptor(-1)


def test_close_signal_descriptor_is_best_effort() -> None:
    """Ignore close failure after the package has already established final evidence."""
    recovery_signal._close_signal_descriptor(-1)
