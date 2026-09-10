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


def _raise_cleanup_failure(_descriptor: int) -> NoReturn:
    """Model cleanup failure without disclosing content or replacing cancellation."""
    raise logical_backup.PostgresLogicalBackupError("bounded cleanup failure")


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


def test_execution_process_control_signal_survives_failed_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep provider cancellation primary when concurrent pump and cleanup both fail."""
    output_path = tmp_path / "cancelled-cleanup-failed.dump"
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
    monkeypatch.setattr(logical_backup, "_invalidate_output", _raise_cleanup_failure)
    monkeypatch.setattr(logical_backup.subprocess, "run", cancel_after_pump_failure)
    try:
        with pytest.raises(_Cancelled):
            create_postgres_logical_backup(
                "safe_service",
                output_descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
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


def test_pump_process_control_signal_survives_failed_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep pump cancellation primary when output invalidation also fails."""
    output_path = tmp_path / "pump-cancelled-cleanup-failed.dump"
    output_descriptor = os.open(
        output_path,
        os.O_CREAT | os.O_EXCL | os.O_RDWR,
        0o600,
    )
    pump_cancelled = threading.Event()

    def cancel_output_copy(_descriptor: int, _chunk: bytes) -> NoReturn:
        pump_cancelled.set()
        raise _PumpCancelled()

    def successful_execution(
        arguments: list[str],
        **kwargs: object,
    ) -> logical_backup.subprocess.CompletedProcess[bytes]:
        provider_stdout = kwargs["stdout"]
        assert type(provider_stdout) is int
        os.write(provider_stdout, b"partial-sensitive-backup")
        assert pump_cancelled.wait(timeout=1.0)
        return logical_backup.subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(logical_backup, "_write_all", cancel_output_copy)
    monkeypatch.setattr(logical_backup, "_invalidate_output", _raise_cleanup_failure)
    monkeypatch.setattr(logical_backup.subprocess, "run", successful_execution)
    try:
        with pytest.raises(_PumpCancelled):
            create_postgres_logical_backup(
                "safe_service",
                output_descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
    finally:
        os.close(output_descriptor)


def test_thread_start_process_control_signal_survives_failed_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep a thread-start cancellation primary when output invalidation fails."""
    output_path = tmp_path / "start-cancelled-cleanup-failed.dump"
    output_descriptor = os.open(
        output_path,
        os.O_CREAT | os.O_EXCL | os.O_RDWR,
        0o600,
    )

    class StartCancelledThread:
        """Raise a process-control signal before output-pump ownership transfers."""

        def __init__(self, **_kwargs: object) -> None:
            pass

        def start(self) -> NoReturn:
            raise _Cancelled()

    monkeypatch.setattr(logical_backup.threading, "Thread", StartCancelledThread)
    monkeypatch.setattr(logical_backup, "_invalidate_output", _raise_cleanup_failure)
    monkeypatch.setattr(
        logical_backup.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("provider must not run"),
    )
    try:
        with pytest.raises(_Cancelled):
            create_postgres_logical_backup(
                "safe_service",
                output_descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
    finally:
        os.close(output_descriptor)


def test_thread_join_process_control_signal_survives_failed_cleanup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep a thread-join cancellation primary when output invalidation fails."""
    output_path = tmp_path / "join-cancelled-cleanup-failed.dump"
    output_descriptor = os.open(
        output_path,
        os.O_CREAT | os.O_EXCL | os.O_RDWR,
        0o600,
    )

    class JoinCancelledThread:
        """Release worker read authority, then cancel while joining the worker."""

        def __init__(self, **kwargs: object) -> None:
            arguments = kwargs["args"]
            assert type(arguments) is tuple
            read_descriptor = arguments[0]
            assert type(read_descriptor) is int
            self.read_descriptor = read_descriptor

        def start(self) -> None:
            os.close(self.read_descriptor)

        def join(self) -> NoReturn:
            raise _Cancelled()

    def successful_execution(
        arguments: list[str],
        **_kwargs: object,
    ) -> logical_backup.subprocess.CompletedProcess[bytes]:
        return logical_backup.subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(logical_backup.threading, "Thread", JoinCancelledThread)
    monkeypatch.setattr(logical_backup, "_invalidate_output", _raise_cleanup_failure)
    monkeypatch.setattr(logical_backup.subprocess, "run", successful_execution)
    try:
        with pytest.raises(_Cancelled):
            create_postgres_logical_backup(
                "safe_service",
                output_descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
    finally:
        os.close(output_descriptor)
