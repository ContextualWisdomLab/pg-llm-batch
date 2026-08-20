# SPDX-License-Identifier: Apache-2.0
"""Error-precedence regressions for bounded PostgreSQL logical backups."""

from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import NoReturn

import pytest

import pg_llm_batch.postgres_logical_backup as logical_backup
from pg_llm_batch.postgres_logical_backup import create_postgres_logical_backup
from tests.logical_backup_test_support import install_retained_pg_dump_stub


pytestmark = pytest.mark.usefixtures(install_retained_pg_dump_stub.__name__)


class _Cancelled(BaseException):
    """Represent a cancellation-like process-control signal from provider execution."""


def test_execution_process_control_signal_wins_over_pump_io_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Do not replace cancellation with an ordinary concurrent output-pump failure."""
    output_path = tmp_path / "cancelled-logical-backup.dump"
    output_descriptor = os.open(
        output_path,
        os.O_CREAT | os.O_EXCL | os.O_RDWR,
        0o600,
    )
    pump_failed = threading.Event()

    def fail_output_copy(_descriptor: int, _chunk: bytes) -> NoReturn:
        pump_failed.set()
        raise OSError("sensitive concurrent output failure")

    def cancel_after_pump_failure(_arguments: list[str], **kwargs: object) -> NoReturn:
        provider_stdout = kwargs["stdout"]
        assert type(provider_stdout) is int
        os.write(provider_stdout, b"partial-sensitive-backup")
        assert pump_failed.wait(timeout=1.0)
        raise _Cancelled()

    monkeypatch.setattr(logical_backup, "_write_all", fail_output_copy)
    monkeypatch.setattr(logical_backup.subprocess, "run", cancel_after_pump_failure)
    try:
        with pytest.raises(_Cancelled):
            create_postgres_logical_backup(
                "safe_service",
                output_descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
        assert output_path.read_bytes() == b""
    finally:
        os.close(output_descriptor)


class _PumpCancelled(BaseException):
    """Represent a process-control signal raised by the output pump."""


def test_existing_pump_process_control_signal_remains_primary(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the prior pump signal primary when both concurrent paths cancel."""
    output_path = tmp_path / "dual-cancelled-logical-backup.dump"
    output_descriptor = os.open(
        output_path,
        os.O_CREAT | os.O_EXCL | os.O_RDWR,
        0o600,
    )
    pump_cancelled = threading.Event()

    def cancel_output_copy(_descriptor: int, _chunk: bytes) -> NoReturn:
        pump_cancelled.set()
        raise _PumpCancelled()

    def cancel_execution(_arguments: list[str], **kwargs: object) -> NoReturn:
        provider_stdout = kwargs["stdout"]
        assert type(provider_stdout) is int
        os.write(provider_stdout, b"partial-sensitive-backup")
        assert pump_cancelled.wait(timeout=1.0)
        raise _Cancelled()

    monkeypatch.setattr(logical_backup, "_write_all", cancel_output_copy)
    monkeypatch.setattr(logical_backup.subprocess, "run", cancel_execution)
    try:
        with pytest.raises(_PumpCancelled):
            create_postgres_logical_backup(
                "safe_service",
                output_descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
        assert output_path.read_bytes() == b""
    finally:
        os.close(output_descriptor)
