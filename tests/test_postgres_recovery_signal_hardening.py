# SPDX-License-Identifier: Apache-2.0
"""Hardening regressions for PostgreSQL recovery-signal preparation."""

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


def _prepare(directory_descriptor: int) -> None:
    """Prepare a signal with distinct reviewed live and restore identities."""
    recovery_signal.prepare_postgres_recovery_signal(
        directory_descriptor,
        live_service_name="live-db",
        restore_service_name="restore-drill",
        live_target_identity=_identity(101),
        restore_target_identity=_identity(202),
    )


def test_permission_hardening_failure_removes_exact_created_signal(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Do not strand a recovery marker when post-create permission hardening fails."""
    directory_descriptor = os.open(tmp_path, os.O_RDONLY | os.O_DIRECTORY)

    def fail_fchmod(descriptor: int, mode: int) -> None:
        del descriptor, mode
        raise OSError("sensitive filesystem detail")

    monkeypatch.setattr(recovery_signal.os, "fchmod", fail_fchmod)
    try:
        with pytest.raises(PostgresRecoverySignalError, match="could not be inspected"):
            _prepare(directory_descriptor)
    finally:
        os.close(directory_descriptor)

    assert not (tmp_path / "recovery.signal").exists()
