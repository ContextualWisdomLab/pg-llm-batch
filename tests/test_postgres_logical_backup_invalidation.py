# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for logical-backup failure invalidation evidence."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from types import SimpleNamespace
from typing import NoReturn

import pytest

import pg_llm_batch.postgres_logical_backup as logical_backup
from pg_llm_batch.postgres_logical_backup import (
    PostgresLogicalBackupError,
    create_postgres_logical_backup,
)


def _open_private_output(tmp_path: Path) -> tuple[Path, int]:
    """Create one caller-owned private empty logical-backup output file."""
    path = tmp_path / "logical-backup.dump"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    return path, descriptor


def test_logical_backup_rejects_foreign_owned_output_before_subprocess(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An inherited private FD owned by another principal must not receive backup bytes."""
    _path, descriptor = _open_private_output(tmp_path)
    real_fstat = os.fstat
    subprocess_called = False

    def foreign_owned_fstat(target_descriptor: int) -> SimpleNamespace:
        status = real_fstat(target_descriptor)
        return SimpleNamespace(
            st_mode=status.st_mode,
            st_size=status.st_size,
            st_nlink=status.st_nlink,
            st_dev=status.st_dev,
            st_ino=status.st_ino,
            st_uid=os.geteuid() + 1,
        )

    def forbidden_run(*_args: object, **_kwargs: object) -> NoReturn:
        nonlocal subprocess_called
        subprocess_called = True
        raise AssertionError("pg_dump must not run for foreign-owned output")

    monkeypatch.setattr(logical_backup.os, "fstat", foreign_owned_fstat)
    monkeypatch.setattr(logical_backup.subprocess, "run", forbidden_run)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup output must be owned by the effective process user$",
        ):
            create_postgres_logical_backup(
                "logical_backup_source",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
        assert not subprocess_called
    finally:
        os.close(descriptor)


def test_logical_backup_invalidates_output_if_owner_changes_during_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ownership drift on the selected inode must invalidate generated backup bytes."""
    path, descriptor = _open_private_output(tmp_path)
    real_fstat = os.fstat
    fstat_calls = 0

    def owner_drift_fstat(target_descriptor: int) -> os.stat_result | SimpleNamespace:
        nonlocal fstat_calls
        status = real_fstat(target_descriptor)
        fstat_calls += 1
        if fstat_calls == 1:
            return status
        return SimpleNamespace(
            st_mode=status.st_mode,
            st_size=status.st_size,
            st_nlink=status.st_nlink,
            st_dev=status.st_dev,
            st_ino=status.st_ino,
            st_uid=status.st_uid + 1,
        )

    def successful_run(
        arguments: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        output_descriptor = kwargs["stdout"]
        assert type(output_descriptor) is int
        os.write(output_descriptor, b"sensitive-logical-backup")
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(logical_backup.os, "fstat", owner_drift_fstat)
    monkeypatch.setattr(logical_backup.subprocess, "run", successful_run)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup output became unsafe$",
        ):
            create_postgres_logical_backup(
                "logical_backup_source",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
        assert path.read_bytes() == b""
    finally:
        os.close(descriptor)


def test_failed_command_reports_failed_output_invalidation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A truncation failure must not be hidden behind the pg_dump command error."""
    path, descriptor = _open_private_output(tmp_path)

    def failed_run(
        arguments: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        output_descriptor = kwargs["stdout"]
        assert type(output_descriptor) is int
        os.write(output_descriptor, b"partial-sensitive-logical-backup")
        return subprocess.CompletedProcess(arguments, 3)

    def failed_truncate(_descriptor: int, _length: int) -> NoReturn:
        raise OSError("secret cleanup path")

    monkeypatch.setattr(subprocess, "run", failed_run)
    monkeypatch.setattr(os, "ftruncate", failed_truncate)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup output could not be invalidated$",
        ) as caught:
            create_postgres_logical_backup(
                "logical_backup_source",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
        assert "secret" not in str(caught.value)
        assert path.read_bytes() == b"partial-sensitive-logical-backup"
    finally:
        os.close(descriptor)


def test_failed_command_reports_failed_output_rewind(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rewind failure after truncation must remain explicit and content-free."""
    path, descriptor = _open_private_output(tmp_path)
    real_lseek = os.lseek

    def failed_run(
        arguments: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        output_descriptor = kwargs["stdout"]
        assert type(output_descriptor) is int
        os.write(output_descriptor, b"partial-sensitive-logical-backup")
        return subprocess.CompletedProcess(arguments, 3)

    def failed_rewind(target_descriptor: int, offset: int, whence: int) -> int:
        if offset == 0 and whence == os.SEEK_SET:
            raise OSError("secret rewind path")
        return real_lseek(target_descriptor, offset, whence)

    monkeypatch.setattr(subprocess, "run", failed_run)
    monkeypatch.setattr(os, "lseek", failed_rewind)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup output could not be invalidated$",
        ) as caught:
            create_postgres_logical_backup(
                "logical_backup_source",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
        assert "secret" not in str(caught.value)
        assert path.read_bytes() == b""
    finally:
        os.close(descriptor)


def test_cleanup_failure_preserves_process_control_signal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cleanup failure must not replace cancellation-like BaseException authority."""
    _path, descriptor = _open_private_output(tmp_path)

    class Cancelled(BaseException):
        """Represent a cancellation-like process-control signal."""

    def cancelled_run(_arguments: list[str], **kwargs: object) -> NoReturn:
        output_descriptor = kwargs["stdout"]
        assert type(output_descriptor) is int
        os.write(output_descriptor, b"partial-sensitive-logical-backup")
        raise Cancelled()

    def failed_truncate(_descriptor: int, _length: int) -> NoReturn:
        raise OSError("secret cleanup path")

    monkeypatch.setattr(subprocess, "run", cancelled_run)
    monkeypatch.setattr(os, "ftruncate", failed_truncate)
    try:
        with pytest.raises(Cancelled):
            create_postgres_logical_backup(
                "logical_backup_source",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
    finally:
        os.close(descriptor)
