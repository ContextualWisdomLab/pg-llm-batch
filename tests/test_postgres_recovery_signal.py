# SPDX-License-Identifier: Apache-2.0
"""Regression tests for fail-closed PostgreSQL recovery-signal preparation."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from pg_llm_batch.postgres_recovery_signal import (
    PostgresRecoverySignalError,
    prepare_postgres_recovery_signal,
)
from pg_llm_batch.postgres_restore_target import PostgresRestoreTargetIdentity


def _identity(value: int) -> PostgresRestoreTargetIdentity:
    """Return one caller-owned PostgreSQL cluster identity for a test."""
    return PostgresRestoreTargetIdentity(system_identifier=value)


def _directory_descriptor(path: Path) -> int:
    """Open one directory descriptor without granting path authority to the package."""
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY)


def _prepare(directory_descriptor: int) -> None:
    """Prepare a recovery signal with a distinct reviewed restore identity."""
    prepare_postgres_recovery_signal(
        directory_descriptor,
        live_service_name="live-db",
        restore_service_name="restore-drill",
        live_target_identity=_identity(101),
        restore_target_identity=_identity(202),
    )


def test_prepare_recovery_signal_creates_private_empty_regular_file(tmp_path: Path) -> None:
    """Create exactly one durable empty recovery.signal in an isolated target."""
    directory_descriptor = _directory_descriptor(tmp_path)
    try:
        _prepare(directory_descriptor)
    finally:
        os.close(directory_descriptor)

    signal_path = tmp_path / "recovery.signal"
    status = signal_path.lstat()
    assert stat.S_ISREG(status.st_mode)
    assert status.st_size == 0
    assert stat.S_IMODE(status.st_mode) == 0o600
    assert status.st_nlink == 1
    assert not (tmp_path / "standby.signal").exists()


@pytest.mark.parametrize("descriptor", [True, -1, "7"])
def test_prepare_recovery_signal_rejects_invalid_descriptor(descriptor: object) -> None:
    """Reject non-exact or negative directory-descriptor authority."""
    with pytest.raises(PostgresRecoverySignalError, match="invalid PostgreSQL recovery signal parameters"):
        _prepare(descriptor)  # type: ignore[arg-type]


def test_prepare_recovery_signal_rejects_regular_file_descriptor(tmp_path: Path) -> None:
    """Reject a descriptor that does not identify a directory."""
    regular_path = tmp_path / "not-a-directory"
    regular_path.write_bytes(b"")
    descriptor = os.open(regular_path, os.O_RDONLY)
    try:
        with pytest.raises(PostgresRecoverySignalError, match="data directory"):
            _prepare(descriptor)
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("mode", [0o770, 0o707])
def test_prepare_recovery_signal_rejects_writable_data_directory(
    tmp_path: Path,
    mode: int,
) -> None:
    """Reject restore directories writable by another group member or local user."""
    data_directory = tmp_path / "restore-data"
    data_directory.mkdir(mode=0o700)
    data_directory.chmod(mode)
    directory_descriptor = _directory_descriptor(data_directory)
    try:
        with pytest.raises(PostgresRecoverySignalError, match="data directory"):
            _prepare(directory_descriptor)
    finally:
        os.close(directory_descriptor)
        data_directory.chmod(0o700)

    assert not (data_directory / "recovery.signal").exists()


def test_prepare_recovery_signal_preserves_existing_recovery_signal(tmp_path: Path) -> None:
    """Fail closed instead of adopting or truncating a pre-existing recovery signal."""
    signal_path = tmp_path / "recovery.signal"
    signal_path.write_bytes(b"operator-owned")
    descriptor = _directory_descriptor(tmp_path)
    try:
        with pytest.raises(PostgresRecoverySignalError, match="already exists"):
            _prepare(descriptor)
    finally:
        os.close(descriptor)

    assert signal_path.read_bytes() == b"operator-owned"


def test_prepare_recovery_signal_refuses_standby_mode(tmp_path: Path) -> None:
    """Refuse a target where standby.signal would take precedence over recovery.signal."""
    standby_path = tmp_path / "standby.signal"
    standby_path.write_bytes(b"")
    descriptor = _directory_descriptor(tmp_path)
    try:
        with pytest.raises(PostgresRecoverySignalError, match="standby signal"):
            _prepare(descriptor)
    finally:
        os.close(descriptor)

    assert not (tmp_path / "recovery.signal").exists()


@pytest.mark.parametrize(
    ("live_service", "restore_service", "live_id", "restore_id"),
    [
        ("same-db", "same-db", 101, 202),
        ("live-db", "restore-drill", 101, 101),
    ],
)
def test_prepare_recovery_signal_requires_restore_target_isolation(
    tmp_path: Path,
    live_service: str,
    restore_service: str,
    live_id: int,
    restore_id: int,
) -> None:
    """Refuse filesystem mutation unless service and cluster identities are distinct."""
    descriptor = _directory_descriptor(tmp_path)
    try:
        with pytest.raises(PostgresRecoverySignalError, match="not isolated"):
            prepare_postgres_recovery_signal(
                descriptor,
                live_service_name=live_service,
                restore_service_name=restore_service,
                live_target_identity=_identity(live_id),
                restore_target_identity=_identity(restore_id),
            )
    finally:
        os.close(descriptor)

    assert not (tmp_path / "recovery.signal").exists()


def test_prepare_recovery_signal_sanitizes_create_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Map lower-level creation failures to one content-free package error."""
    import pg_llm_batch.postgres_recovery_signal as recovery_signal

    directory_descriptor = _directory_descriptor(tmp_path)
    real_open = recovery_signal.os.open

    def fail_signal_open(path: str, flags: int, *args: object, **kwargs: object) -> int:
        if path == "recovery.signal":
            raise OSError("sensitive host path and kernel detail")
        return real_open(path, flags, *args, **kwargs)

    monkeypatch.setattr(recovery_signal.os, "open", fail_signal_open)
    try:
        with pytest.raises(PostgresRecoverySignalError) as caught:
            _prepare(directory_descriptor)
    finally:
        os.close(directory_descriptor)

    assert "sensitive" not in str(caught.value)
    assert not (tmp_path / "recovery.signal").exists()


def test_prepare_recovery_signal_cleans_created_file_after_sync_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Remove only the just-created signal when durable synchronization fails."""
    import pg_llm_batch.postgres_recovery_signal as recovery_signal

    directory_descriptor = _directory_descriptor(tmp_path)
    calls = 0
    real_fsync = recovery_signal.os.fsync

    def fail_first_fsync(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise OSError("sensitive filesystem detail")
        real_fsync(descriptor)

    monkeypatch.setattr(recovery_signal.os, "fsync", fail_first_fsync)
    try:
        with pytest.raises(PostgresRecoverySignalError, match="could not be synchronized"):
            _prepare(directory_descriptor)
    finally:
        os.close(directory_descriptor)

    assert not (tmp_path / "recovery.signal").exists()


def test_prepare_recovery_signal_rechecks_standby_race_and_cleans(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Fail closed if standby.signal appears after recovery.signal creation."""
    import pg_llm_batch.postgres_recovery_signal as recovery_signal

    directory_descriptor = _directory_descriptor(tmp_path)
    real_fsync = recovery_signal.os.fsync
    calls = 0

    def create_standby_after_signal(descriptor: int) -> None:
        nonlocal calls
        calls += 1
        real_fsync(descriptor)
        if calls == 1:
            (tmp_path / "standby.signal").write_bytes(b"")

    monkeypatch.setattr(recovery_signal.os, "fsync", create_standby_after_signal)
    try:
        with pytest.raises(PostgresRecoverySignalError, match="standby signal"):
            _prepare(directory_descriptor)
    finally:
        os.close(directory_descriptor)

    assert not (tmp_path / "recovery.signal").exists()
    assert (tmp_path / "standby.signal").exists()
