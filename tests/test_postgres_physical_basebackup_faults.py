# SPDX-License-Identifier: Apache-2.0
"""Fault-injection regressions for PostgreSQL physical base-backup boundaries."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

import pg_llm_batch.postgres_physical_basebackup as physical_basebackup
from pg_llm_batch.postgres_physical_basebackup import PostgresPhysicalBaseBackupError


def _open_output(tmp_path: Path, name: str) -> tuple[Path, int]:
    """Create one private regular file suitable for direct boundary tests."""
    path = tmp_path / name
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    return path, descriptor


@pytest.mark.parametrize(
    ("maximum_output_bytes", "payload"),
    [(1, b"ab"), (10, b"ab")],
)
def test_output_copier_records_short_writes_without_escaping_thread(
    monkeypatch: pytest.MonkeyPatch,
    maximum_output_bytes: int,
    payload: bytes,
) -> None:
    """Short writes fail inside the copier for both bounded-write paths."""
    reads = iter((payload,))
    monkeypatch.setattr(
        physical_basebackup.os,
        "read",
        lambda _descriptor, _size: next(reads, b""),
    )
    monkeypatch.setattr(
        physical_basebackup.os,
        "write",
        lambda _descriptor, _payload: 0,
    )
    monkeypatch.setattr(
        physical_basebackup,
        "_close_cleanup_descriptor",
        lambda _descriptor: None,
    )
    failures: list[BaseException] = []

    physical_basebackup._copy_bounded_output(
        71,
        72,
        maximum_output_bytes,
        failures,
    )

    assert len(failures) == 1
    assert type(failures[0]) is OSError
    assert str(failures[0]) == "short physical backup output write"


def test_partial_pipe_setup_failure_closes_both_pipe_descriptors(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A metadata failure after pipe creation closes both ends and invalidates output."""
    path, output_descriptor = _open_output(tmp_path, "pipe-setup.tar")
    os.write(output_descriptor, b"partial")
    read_descriptor, write_descriptor = os.pipe()
    real_fstat = os.fstat

    monkeypatch.setattr(
        physical_basebackup.os,
        "pipe",
        lambda: (read_descriptor, write_descriptor),
    )

    def fail_pipe_metadata(descriptor: int) -> os.stat_result:
        if descriptor == write_descriptor:
            raise OSError("private pipe diagnostic")
        return real_fstat(descriptor)

    monkeypatch.setattr(physical_basebackup.os, "fstat", fail_pipe_metadata)
    try:
        with pytest.raises(
            PostgresPhysicalBaseBackupError,
            match="^PostgreSQL physical base-backup execution failed$",
        ):
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
        assert path.read_bytes() == b""
        for descriptor in (read_descriptor, write_descriptor):
            with pytest.raises(OSError):
                os.fstat(descriptor)
    finally:
        os.close(output_descriptor)


def test_pump_start_failure_invalidates_without_executing_provider(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failure to start the copier thread closes pipe authority before provider execution."""
    path, output_descriptor = _open_output(tmp_path, "pump-start.tar")
    os.write(output_descriptor, b"partial")

    class FailingThread:
        def start(self) -> None:
            raise RuntimeError("private thread diagnostic")

        def join(self) -> None:
            raise AssertionError("join must not run when start fails")

    monkeypatch.setattr(
        physical_basebackup.threading,
        "Thread",
        lambda **_kwargs: FailingThread(),
    )
    monkeypatch.setattr(
        physical_basebackup.subprocess,
        "run",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("provider must not execute when pump start fails")
        ),
    )
    try:
        with pytest.raises(
            PostgresPhysicalBaseBackupError,
            match="^PostgreSQL physical base-backup execution failed$",
        ):
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
        assert path.read_bytes() == b""
    finally:
        os.close(output_descriptor)


def test_post_execution_pipe_metadata_failure_is_fail_closed(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Losing pipe identity evidence after provider return invalidates copied bytes."""
    path, output_descriptor = _open_output(tmp_path, "pipe-identity.tar")
    real_pipe = os.pipe
    real_fstat = os.fstat
    captured_write_descriptor: int | None = None
    pipe_fstat_calls = 0

    def capture_pipe() -> tuple[int, int]:
        nonlocal captured_write_descriptor
        descriptors = real_pipe()
        captured_write_descriptor = descriptors[1]
        return descriptors

    def fail_second_pipe_fstat(descriptor: int) -> os.stat_result:
        nonlocal pipe_fstat_calls
        if descriptor == captured_write_descriptor:
            pipe_fstat_calls += 1
            if pipe_fstat_calls == 2:
                raise OSError("private pipe metadata diagnostic")
        return real_fstat(descriptor)

    def successful_run(
        arguments: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        stdout = kwargs["stdout"]
        assert type(stdout) is int
        os.write(stdout, b"provider-bytes")
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(physical_basebackup.os, "pipe", capture_pipe)
    monkeypatch.setattr(physical_basebackup.os, "fstat", fail_second_pipe_fstat)
    monkeypatch.setattr(physical_basebackup.subprocess, "run", successful_run)
    try:
        with pytest.raises(
            PostgresPhysicalBaseBackupError,
            match="^PostgreSQL physical base-backup output changed during execution$",
        ):
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
        assert pipe_fstat_calls == 2
        assert path.read_bytes() == b""
    finally:
        os.close(output_descriptor)


def test_pump_join_control_signal_survives_invalidation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A join-time process-control signal outranks a secondary cleanup failure."""
    _path, output_descriptor = _open_output(tmp_path, "join-control.tar")

    class Cancelled(BaseException):
        """Represent a cancellation-like process-control signal."""

    class CancellingThread:
        def start(self) -> None:
            return None

        def join(self) -> None:
            raise Cancelled()

    monkeypatch.setattr(
        physical_basebackup.threading,
        "Thread",
        lambda **_kwargs: CancellingThread(),
    )
    monkeypatch.setattr(
        physical_basebackup.subprocess,
        "run",
        lambda arguments, **_kwargs: subprocess.CompletedProcess(arguments, 0),
    )
    monkeypatch.setattr(
        physical_basebackup.os,
        "ftruncate",
        lambda *_args: (_ for _ in ()).throw(OSError("private cleanup diagnostic")),
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
    finally:
        os.close(output_descriptor)


def test_pump_control_signal_survives_invalidation_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A copier process-control signal remains primary when invalidation also fails."""
    _path, output_descriptor = _open_output(tmp_path, "pump-control.tar")

    class Cancelled(BaseException):
        """Represent a cancellation-like process-control signal."""

    failure = Cancelled()

    class FailedPumpThread:
        def __init__(self, *, args: tuple[object, ...], **_kwargs: object) -> None:
            self._read_descriptor = args[0]
            self._failures = args[-1]

        def start(self) -> None:
            assert type(self._read_descriptor) is int
            assert type(self._failures) is list
            os.close(self._read_descriptor)
            self._failures.append(failure)

        def join(self) -> None:
            return None

    monkeypatch.setattr(physical_basebackup.threading, "Thread", FailedPumpThread)
    monkeypatch.setattr(
        physical_basebackup.subprocess,
        "run",
        lambda arguments, **_kwargs: subprocess.CompletedProcess(arguments, 0),
    )
    monkeypatch.setattr(
        physical_basebackup.os,
        "ftruncate",
        lambda *_args: (_ for _ in ()).throw(OSError("private cleanup diagnostic")),
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
    finally:
        os.close(output_descriptor)


def test_ordinary_pump_failure_is_content_free_and_invalidates_output(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An ordinary copier failure becomes a stable package error after invalidation."""
    path, output_descriptor = _open_output(tmp_path, "pump-error.tar")
    os.write(output_descriptor, b"partial")

    class FailedPumpThread:
        def __init__(self, *, args: tuple[object, ...], **_kwargs: object) -> None:
            self._read_descriptor = args[0]
            self._failures = args[-1]

        def start(self) -> None:
            assert type(self._read_descriptor) is int
            assert type(self._failures) is list
            os.close(self._read_descriptor)
            self._failures.append(OSError("private pump diagnostic"))

        def join(self) -> None:
            return None

    monkeypatch.setattr(physical_basebackup.threading, "Thread", FailedPumpThread)
    monkeypatch.setattr(
        physical_basebackup.subprocess,
        "run",
        lambda arguments, **_kwargs: subprocess.CompletedProcess(arguments, 0),
    )
    try:
        with pytest.raises(
            PostgresPhysicalBaseBackupError,
            match="^PostgreSQL physical base-backup execution failed$",
        ) as caught:
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
        assert "private pump diagnostic" not in str(caught.value)
        assert path.read_bytes() == b""
    finally:
        os.close(output_descriptor)


def test_finalization_rejects_initial_inode_identity_mismatch(
    tmp_path: Path,
) -> None:
    """Final acceptance invalidates bytes when the inspected inode identity disagrees."""
    path, output_descriptor = _open_output(tmp_path, "selected.tar")
    _other_path, other_descriptor = _open_output(tmp_path, "other.tar")
    os.write(output_descriptor, b"provider-bytes")
    initial_status = os.fstat(other_descriptor)
    try:
        with pytest.raises(
            PostgresPhysicalBaseBackupError,
            match="^PostgreSQL physical base-backup output changed during execution$",
        ):
            physical_basebackup._finalize_output(
                output_descriptor,
                output_descriptor,
                initial_status,
                1024,
            )
        assert path.read_bytes() == b""
    finally:
        os.close(other_descriptor)
        os.close(output_descriptor)
