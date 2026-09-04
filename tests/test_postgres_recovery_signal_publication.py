# SPDX-License-Identifier: Apache-2.0
"""Publication-safety regression for PostgreSQL recovery-signal preparation."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

import pg_llm_batch.postgres_recovery_signal as recovery_signal
from pg_llm_batch.postgres_recovery_signal import PostgresRecoverySignalError
from pg_llm_batch.postgres_restore_target import PostgresRestoreTargetIdentity


def _identity(value: int) -> PostgresRestoreTargetIdentity:
    """Return one caller-owned PostgreSQL cluster identity for a test."""
    return PostgresRestoreTargetIdentity(system_identifier=value)


def test_identity_capture_failure_does_not_publish_recovery_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Never leave PostgreSQL's recovery trigger published after a failed prepare."""
    directory_descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    real_fstat = recovery_signal.os.fstat

    def fail_signal_fstat(descriptor: int) -> os.stat_result:
        status = real_fstat(descriptor)
        if stat.S_ISDIR(status.st_mode):
            return status
        raise OSError("sensitive created-inode diagnostic")

    monkeypatch.setattr(recovery_signal.os, "fstat", fail_signal_fstat)
    try:
        with pytest.raises(
            PostgresRecoverySignalError,
            match="recovery signal identity could not be captured",
        ):
            recovery_signal.prepare_postgres_recovery_signal(
                directory_descriptor,
                live_service_name="live-db",
                restore_service_name="restore-drill",
                live_target_identity=_identity(101),
                restore_target_identity=_identity(202),
            )
    finally:
        os.close(directory_descriptor)

    assert not (tmp_path / "recovery.signal").exists()
