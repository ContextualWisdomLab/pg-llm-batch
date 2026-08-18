# SPDX-License-Identifier: Apache-2.0
"""Trusted-executable regressions for PostgreSQL physical base backup."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import NoReturn

import pytest

import pg_llm_batch.postgres_physical_basebackup as physical_basebackup
from pg_llm_batch.postgres_physical_basebackup import PostgresPhysicalBaseBackupError


_EXECUTABLE_ERROR = "^PostgreSQL physical base-backup executable is unsafe$"


def _open_private_output(tmp_path: Path) -> int:
    """Return one process-owned owner-only empty backup output descriptor."""
    return os.open(
        tmp_path / "basebackup.tar",
        os.O_RDWR | os.O_CREAT | os.O_EXCL,
        0o600,
    )


def _write_executable(tmp_path: Path, mode: int) -> Path:
    """Create one local executable named exactly like the PostgreSQL utility."""
    executable = tmp_path / "pg_basebackup"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(mode)
    return executable


def _forbidden_subprocess(*_args: object, **_kwargs: object) -> NoReturn:
    """Fail if untrusted executable authority reaches child-process execution."""
    raise AssertionError("unsafe pg_basebackup must fail before subprocess execution")


def _foreign_owner(status: os.stat_result) -> os.stat_result:
    """Return equivalent metadata whose executable owner is another principal."""
    fields = list(status)
    effective_user_id = os.geteuid()
    fields[4] = (
        effective_user_id + 1
        if effective_user_id < 2**31 - 1
        else effective_user_id - 1
    )
    return os.stat_result(fields)


def test_group_writable_pg_basebackup_is_rejected_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mutable executable must not gain physical-backup process authority."""
    output_descriptor = _open_private_output(tmp_path)
    executable = _write_executable(tmp_path, 0o770)
    monkeypatch.setattr(subprocess, "run", _forbidden_subprocess)
    try:
        with pytest.raises(PostgresPhysicalBaseBackupError, match=_EXECUTABLE_ERROR):
            physical_basebackup.create_postgres_physical_basebackup(
                "physical_backup_source",
                output_descriptor,
                pg_basebackup_executable=str(executable),
            )
    finally:
        os.close(output_descriptor)


def test_foreign_owned_pg_basebackup_is_rejected_before_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A foreign owner must not retain chmod or rewrite authority to the executable."""
    output_descriptor = _open_private_output(tmp_path)
    executable = _write_executable(tmp_path, 0o750)
    real_fstat = os.fstat
    executable_status = os.stat(executable)
    executable_identity = (executable_status.st_dev, executable_status.st_ino)

    def foreign_executable_owner(file_descriptor: int) -> os.stat_result:
        observed = real_fstat(file_descriptor)
        if (observed.st_dev, observed.st_ino) == executable_identity:
            return _foreign_owner(observed)
        return observed

    monkeypatch.setattr(physical_basebackup.os, "fstat", foreign_executable_owner)
    monkeypatch.setattr(subprocess, "run", _forbidden_subprocess)
    try:
        with pytest.raises(PostgresPhysicalBaseBackupError, match=_EXECUTABLE_ERROR):
            physical_basebackup.create_postgres_physical_basebackup(
                "physical_backup_source",
                output_descriptor,
                pg_basebackup_executable=str(executable),
            )
    finally:
        os.close(output_descriptor)
