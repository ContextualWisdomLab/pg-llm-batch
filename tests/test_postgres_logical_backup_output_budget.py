# SPDX-License-Identifier: Apache-2.0
"""Regression tests for finite logical-backup output byte authority."""

from __future__ import annotations

import os
import subprocess

import pytest

import pg_llm_batch.postgres_logical_backup as logical_backup
from pg_llm_batch.postgres_logical_backup import (
    PostgresLogicalBackupError,
    PostgresLogicalBackupResult,
    create_postgres_logical_backup,
)
from tests.logical_backup_test_support import install_retained_pg_dump_stub


pytestmark = pytest.mark.usefixtures(install_retained_pg_dump_stub.__name__)


def _open_private_output(tmp_path):
    path = tmp_path / "backup.dump"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    return path, descriptor


def _read_output(descriptor: int) -> bytes:
    os.lseek(descriptor, 0, os.SEEK_SET)
    return os.read(descriptor, 1024)


def test_logical_backup_accepts_exact_output_byte_budget(tmp_path, monkeypatch):
    _path, descriptor = _open_private_output(tmp_path)

    def exact_run(argv, **kwargs):
        os.write(kwargs["stdout"], b"PGDM")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(logical_backup.subprocess, "run", exact_run)
    try:
        assert create_postgres_logical_backup(
            "safe_service",
            descriptor,
            pg_dump_executable="/usr/bin/pg_dump",
            maximum_output_bytes=4,
        ) == PostgresLogicalBackupResult(size_bytes=4)
        assert _read_output(descriptor) == b"PGDM"
    finally:
        os.close(descriptor)


def test_logical_backup_invalidates_output_when_provider_exceeds_byte_budget(
    tmp_path, monkeypatch
):
    _path, descriptor = _open_private_output(tmp_path)

    def oversized_run(argv, **kwargs):
        os.write(kwargs["stdout"], b"PGDMP")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(logical_backup.subprocess, "run", oversized_run)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup exceeded output byte budget$",
        ):
            create_postgres_logical_backup(
                "safe_service",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
                maximum_output_bytes=4,
            )
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 0
        assert os.fstat(descriptor).st_size == 0
    finally:
        os.close(descriptor)


@pytest.mark.parametrize("maximum_output_bytes", [0, True, 1 << 63])
def test_logical_backup_rejects_invalid_output_byte_budget_before_provider(
    tmp_path, monkeypatch, maximum_output_bytes
):
    _path, descriptor = _open_private_output(tmp_path)
    called = False

    def forbidden_run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("provider must not run")

    monkeypatch.setattr(logical_backup.subprocess, "run", forbidden_run)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^invalid PostgreSQL logical backup parameters$",
        ):
            create_postgres_logical_backup(
                "safe_service",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
                maximum_output_bytes=maximum_output_bytes,
            )
        assert called is False
    finally:
        os.close(descriptor)


def test_logical_backup_fails_closed_when_output_pipe_cannot_be_created(
    tmp_path, monkeypatch
):
    _path, descriptor = _open_private_output(tmp_path)
    monkeypatch.setattr(
        logical_backup.os,
        "pipe",
        lambda: (_ for _ in ()).throw(OSError("private pipe detail")),
    )
    monkeypatch.setattr(
        logical_backup.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("provider must not run"),
    )
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup execution failed$",
        ) as caught:
            create_postgres_logical_backup(
                "safe_service",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
        assert "private" not in str(caught.value)
        assert os.fstat(descriptor).st_size == 0
    finally:
        os.close(descriptor)


def test_logical_backup_fails_closed_when_output_pump_cannot_start(
    tmp_path, monkeypatch
):
    _path, descriptor = _open_private_output(tmp_path)

    class StartFailureThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise RuntimeError("private thread detail")

    monkeypatch.setattr(logical_backup.threading, "Thread", StartFailureThread)
    monkeypatch.setattr(
        logical_backup.subprocess,
        "run",
        lambda *_args, **_kwargs: pytest.fail("provider must not run"),
    )
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup execution failed$",
        ) as caught:
            create_postgres_logical_backup(
                "safe_service",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
        assert "private" not in str(caught.value)
        assert os.fstat(descriptor).st_size == 0
    finally:
        os.close(descriptor)


def test_logical_backup_preserves_start_interrupt_and_closes_pipe_fds(
    tmp_path, monkeypatch
):
    _path, descriptor = _open_private_output(tmp_path)
    real_pipe = os.pipe
    pipe_descriptors: list[int] = []

    def recording_pipe():
        read_descriptor, write_descriptor = real_pipe()
        pipe_descriptors.extend((read_descriptor, write_descriptor))
        return read_descriptor, write_descriptor

    class StartInterruptThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(logical_backup.os, "pipe", recording_pipe)
    monkeypatch.setattr(logical_backup.threading, "Thread", StartInterruptThread)
    try:
        with pytest.raises(KeyboardInterrupt):
            create_postgres_logical_backup(
                "safe_service",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
        assert len(pipe_descriptors) == 2
        for pipe_descriptor in pipe_descriptors:
            with pytest.raises(OSError):
                os.fstat(pipe_descriptor)
        assert os.fstat(descriptor).st_size == 0
    finally:
        for pipe_descriptor in pipe_descriptors:
            try:
                os.close(pipe_descriptor)
            except OSError:
                pass
        os.close(descriptor)


def test_logical_backup_normalizes_output_pump_failure(tmp_path, monkeypatch):
    _path, descriptor = _open_private_output(tmp_path)

    def fail_copy(_descriptor, _chunk):
        raise OSError("private write detail")

    def one_byte_run(argv, **kwargs):
        os.write(kwargs["stdout"], b"x")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(logical_backup, "_write_all", fail_copy)
    monkeypatch.setattr(logical_backup.subprocess, "run", one_byte_run)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup execution failed$",
        ) as caught:
            create_postgres_logical_backup(
                "safe_service",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
        assert "private" not in str(caught.value)
        assert os.fstat(descriptor).st_size == 0
    finally:
        os.close(descriptor)


def test_logical_backup_preserves_output_pump_baseexception(tmp_path, monkeypatch):
    _path, descriptor = _open_private_output(tmp_path)

    def interrupt_copy(_descriptor, _chunk):
        raise KeyboardInterrupt

    def one_byte_run(argv, **kwargs):
        os.write(kwargs["stdout"], b"x")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(logical_backup, "_write_all", interrupt_copy)
    monkeypatch.setattr(logical_backup.subprocess, "run", one_byte_run)
    try:
        with pytest.raises(KeyboardInterrupt):
            create_postgres_logical_backup(
                "safe_service",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
        assert os.fstat(descriptor).st_size == 0
    finally:
        os.close(descriptor)


def test_logical_backup_preserves_join_interrupt_and_invalidates_output(
    tmp_path, monkeypatch
):
    _path, descriptor = _open_private_output(tmp_path)

    class JoinInterruptThread:
        def __init__(self, **_kwargs):
            pass

        def start(self):
            pass

        def join(self):
            raise KeyboardInterrupt

    monkeypatch.setattr(logical_backup.threading, "Thread", JoinInterruptThread)
    monkeypatch.setattr(
        logical_backup.subprocess,
        "run",
        lambda argv, **_kwargs: subprocess.CompletedProcess(argv, 0),
    )
    try:
        with pytest.raises(KeyboardInterrupt):
            create_postgres_logical_backup(
                "safe_service",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
        assert os.fstat(descriptor).st_size == 0
    finally:
        os.close(descriptor)


def test_logical_backup_retries_short_output_writes(monkeypatch):
    writes: list[bytes] = []
    results = iter((1, 2))

    def short_write(_descriptor, chunk):
        writes.append(bytes(chunk))
        return next(results)

    monkeypatch.setattr(logical_backup.os, "write", short_write)
    logical_backup._write_all(123, b"abc")
    assert writes == [b"abc", b"bc"]


def test_logical_backup_rejects_zero_length_output_write(monkeypatch):
    monkeypatch.setattr(logical_backup.os, "write", lambda _descriptor, _chunk: 0)
    with pytest.raises(OSError, match="^short logical backup output write$"):
        logical_backup._write_all(123, b"x")


def test_logical_backup_final_size_check_defends_against_internal_bypass(
    tmp_path, monkeypatch
):
    _path, descriptor = _open_private_output(tmp_path)

    def oversized_internal_run(**kwargs):
        os.write(kwargs["output_descriptor"], b"PGDMP")
        return subprocess.CompletedProcess(["pg_dump"], 0)

    monkeypatch.setattr(logical_backup, "_run_pg_dump", oversized_internal_run)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup exceeded output byte budget$",
        ):
            create_postgres_logical_backup(
                "safe_service",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
                maximum_output_bytes=4,
            )
        assert os.fstat(descriptor).st_size == 0
    finally:
        os.close(descriptor)
