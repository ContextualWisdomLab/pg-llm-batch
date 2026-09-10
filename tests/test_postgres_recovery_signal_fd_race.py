# SPDX-License-Identifier: Apache-2.0
"""Regression for caller descriptor replacement during recovery-signal preparation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pg_llm_batch import postgres_recovery_signal
from pg_llm_batch.postgres_recovery_signal import prepare_postgres_recovery_signal
from pg_llm_batch.postgres_restore_target import PostgresRestoreTargetIdentity


def _open_directory(path: Path) -> int:
    """Open one caller-owned directory capability."""
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY)


def test_recovery_signal_snapshots_directory_fd_before_relative_mutation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replacing the caller FD after validation must not redirect filesystem mutation."""
    original_directory = tmp_path / "original-data"
    replacement_directory = tmp_path / "replacement-data"
    original_directory.mkdir()
    replacement_directory.mkdir()
    original_fd = _open_directory(original_directory)
    replacement_fd = _open_directory(replacement_directory)
    real_stat = os.stat
    swapped = False

    def swap_caller_fd_then_stat(path: object, *args: object, **kwargs: object) -> os.stat_result:
        nonlocal swapped
        if not swapped:
            swapped = True
            os.dup2(replacement_fd, original_fd)
        return real_stat(path, *args, **kwargs)  # type: ignore[arg-type]

    monkeypatch.setattr(postgres_recovery_signal.os, "stat", swap_caller_fd_then_stat)
    try:
        prepare_postgres_recovery_signal(
            original_fd,
            live_service_name="live-db",
            restore_service_name="restore-drill",
            live_target_identity=PostgresRestoreTargetIdentity(system_identifier=101),
            restore_target_identity=PostgresRestoreTargetIdentity(system_identifier=202),
        )
    finally:
        monkeypatch.undo()
        os.close(replacement_fd)
        os.close(original_fd)

    assert swapped
    assert (original_directory / "recovery.signal").is_file()
    assert not (replacement_directory / "recovery.signal").exists()
