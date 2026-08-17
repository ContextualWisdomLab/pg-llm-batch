# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for physical backup output ownership."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import NoReturn

import pytest

from pg_llm_batch.postgres_physical_basebackup import (
    PostgresPhysicalBaseBackupError,
    create_postgres_physical_basebackup,
)


def test_output_must_be_owned_by_effective_process_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Owner-only mode is insufficient when another OS user owns the backup file."""
    path = tmp_path / "foreign-owner-basebackup.tar"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    actual_owner = os.fstat(descriptor).st_uid
    monkeypatch.setattr(os, "geteuid", lambda: actual_owner + 1)

    def forbidden_subprocess(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("foreign-owned backup output must fail before subprocess execution")

    monkeypatch.setattr(subprocess, "run", forbidden_subprocess)
    try:
        with pytest.raises(
            PostgresPhysicalBaseBackupError,
            match="owned by the effective process user",
        ):
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
            )
    finally:
        os.close(descriptor)


def test_output_owner_must_not_change_during_backup(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ownership drift on the same inode invalidates otherwise successful backup bytes."""
    path = tmp_path / "ownership-drift-basebackup.tar"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    real_fstat = os.fstat
    inspected_status = real_fstat(descriptor)
    fstat_calls = 0

    def drifting_fstat(fd: int) -> os.stat_result:
        nonlocal fstat_calls
        status = real_fstat(fd)
        if fd != descriptor:
            return status
        fstat_calls += 1
        if fstat_calls == 1:
            return status
        fields = list(status)
        fields[4] = inspected_status.st_uid + 1
        return os.stat_result(fields)

    def successful_run(
        arguments: list[str],
        **kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        output_descriptor = kwargs["stdout"]
        assert type(output_descriptor) is int
        os.write(output_descriptor, b"sensitive-physical-backup")
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(os, "fstat", drifting_fstat)
    monkeypatch.setattr(subprocess, "run", successful_run)
    try:
        with pytest.raises(
            PostgresPhysicalBaseBackupError,
            match="became unsafe",
        ):
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
            )
        assert path.read_bytes() == b""
    finally:
        os.close(descriptor)
