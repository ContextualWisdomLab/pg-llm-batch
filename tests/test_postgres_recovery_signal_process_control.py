# SPDX-License-Identifier: Apache-2.0
"""Process-control regressions for PostgreSQL recovery-signal preparation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import pg_llm_batch.postgres_recovery_signal as recovery_signal
from pg_llm_batch.postgres_recovery_signal import PostgresRecoverySignalError
from pg_llm_batch.postgres_restore_target import PostgresRestoreTargetIdentity


def _identity(value: int) -> PostgresRestoreTargetIdentity:
    """Return one caller-owned PostgreSQL cluster identity for a test."""
    return PostgresRestoreTargetIdentity(system_identifier=value)


@pytest.mark.parametrize("signal_type", [KeyboardInterrupt, SystemExit])
def test_quarantine_failure_does_not_mask_process_control_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    signal_type: type[BaseException],
) -> None:
    """Keep process control primary when unverified-trigger quarantine also fails."""
    directory_descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)
    signal = signal_type("process control sentinel")

    def interrupt_identity_capture(signal_descriptor: int) -> tuple[int, int]:
        del signal_descriptor
        raise signal

    def fail_rename(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise OSError("sensitive quarantine diagnostic")

    monkeypatch.setattr(
        recovery_signal,
        "_capture_created_signal_identity",
        interrupt_identity_capture,
    )
    monkeypatch.setattr(recovery_signal.os, "rename", fail_rename)
    try:
        with pytest.raises(signal_type) as caught:
            recovery_signal.prepare_postgres_recovery_signal(
                directory_descriptor,
                live_service_name="live-db",
                restore_service_name="restore-drill",
                live_target_identity=_identity(101),
                restore_target_identity=_identity(202),
            )
    finally:
        os.close(directory_descriptor)

    assert caught.value is signal
    cleanup_error = caught.value.__cause__
    assert type(cleanup_error) is PostgresRecoverySignalError
    assert str(cleanup_error) == (
        "PostgreSQL recovery trigger could not be quarantined after inspection failure"
    )
    assert "sensitive" not in str(cleanup_error)
