# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for logical-backup failure invalidation evidence."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import NoReturn

import pytest

from pg_llm_batch.postgres_logical_backup import (
    PostgresLogicalBackupError,
    create_postgres_logical_backup,
)


def _open_private_output(tmp_path: Path) -> tuple[Path, int]:
    """Create one caller-owned private empty logical-backup output file."""
    path = tmp_path / "logical-backup.dump"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    return path, descriptor


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
