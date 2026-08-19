# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for physical-basebackup failure invalidation evidence."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import NoReturn

import pytest

import pg_llm_batch.postgres_physical_basebackup as physical_basebackup
from pg_llm_batch.postgres_physical_basebackup import (
    PostgresPhysicalBaseBackupError,
    create_postgres_physical_basebackup,
)


@pytest.fixture(autouse=True)
def _retain_hermetic_test_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep invalidation regressions independent of host PostgreSQL packaging."""

    def retain_test_executable(_path: str) -> int:
        return os.open(os.devnull, os.O_RDONLY)

    monkeypatch.setattr(
        physical_basebackup,
        "_retain_pg_basebackup_executable",
        retain_test_executable,
    )


def _open_private_output(tmp_path: Path) -> tuple[Path, int]:
    """Create one caller-owned private empty output file."""
    path = tmp_path / "basebackup.tar"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    return path, descriptor


def test_failed_command_reports_failed_output_invalidation(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A truncation failure must not be hidden behind the provider command error."""
    path, descriptor = _open_private_output(tmp_path)

    def failed_run(
        arguments: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        output_descriptor = kwargs["stdout"]
        assert type(output_descriptor) is int
        os.write(output_descriptor, b"partial-sensitive-backup")
        return subprocess.CompletedProcess(arguments, 3)

    def failed_truncate(_descriptor: int, _length: int) -> NoReturn:
        raise OSError("secret cleanup path")

    monkeypatch.setattr(subprocess, "run", failed_run)
    monkeypatch.setattr(os, "ftruncate", failed_truncate)
    try:
        with pytest.raises(
            PostgresPhysicalBaseBackupError,
            match="^PostgreSQL physical base-backup output could not be invalidated$",
        ) as caught:
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
            )
        assert "secret" not in str(caught.value)
        assert path.read_bytes() == b"partial-sensitive-backup"
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
        os.write(output_descriptor, b"partial-sensitive-backup")
        raise Cancelled()

    def failed_truncate(_descriptor: int, _length: int) -> NoReturn:
        raise OSError("secret cleanup path")

    monkeypatch.setattr(subprocess, "run", cancelled_run)
    monkeypatch.setattr(os, "ftruncate", failed_truncate)
    try:
        with pytest.raises(Cancelled):
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
            )
    finally:
        os.close(descriptor)
