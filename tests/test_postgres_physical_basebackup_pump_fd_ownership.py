# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for physical-backup copier descriptor ownership."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import pg_llm_batch.postgres_physical_basebackup as physical_basebackup


def _open_output(tmp_path: Path) -> tuple[Path, int]:
    """Create one private output file for direct pipe-boundary tests."""
    path = tmp_path / "pump-fd-ownership.tar"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    return path, descriptor


def test_join_signal_does_not_close_descriptor_reused_after_worker_exit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """After start, only the copier may close its process-wide read descriptor number."""
    _path, output_descriptor = _open_output(tmp_path)
    replacement_descriptor: int | None = None

    class Cancelled(BaseException):
        """Represent a join-time process-control signal."""

    class WorkerExitedThenJoinCancelled:
        def __init__(self, *, args: tuple[object, ...], **_kwargs: object) -> None:
            self._read_descriptor = args[0]

        def start(self) -> None:
            nonlocal replacement_descriptor
            assert type(self._read_descriptor) is int
            os.close(self._read_descriptor)
            replacement_descriptor = os.open(os.devnull, os.O_RDONLY)
            assert replacement_descriptor == self._read_descriptor

        def join(self) -> None:
            raise Cancelled()

    monkeypatch.setattr(
        physical_basebackup.threading,
        "Thread",
        WorkerExitedThenJoinCancelled,
    )
    monkeypatch.setattr(
        physical_basebackup.subprocess,
        "run",
        lambda arguments, **_kwargs: subprocess.CompletedProcess(arguments, 0),
    )

    try:
        with pytest.raises(Cancelled):
            physical_basebackup._run_pg_basebackup(
                service_name="physical_backup_source",
                output_descriptor=output_descriptor,
                cleanup_descriptor=output_descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
                executable_descriptor=0,
                timeout_seconds=30,
                connect_timeout_seconds=5,
                maximum_output_bytes=1024,
            )

        assert replacement_descriptor is not None
        os.fstat(replacement_descriptor)
    finally:
        if replacement_descriptor is not None:
            try:
                os.close(replacement_descriptor)
            except OSError:
                pass
        os.close(output_descriptor)
