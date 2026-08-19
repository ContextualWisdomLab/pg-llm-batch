# SPDX-License-Identifier: Apache-2.0
"""Privilege-bit regressions for retained PostgreSQL base-backup executables."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

import pg_llm_batch.postgres_physical_basebackup as physical_basebackup
from pg_llm_batch.postgres_physical_basebackup import PostgresPhysicalBaseBackupError


_EXECUTABLE_ERROR = "^PostgreSQL physical base-backup executable is unsafe$"


def _root_owned_executable_status(
    monkeypatch: pytest.MonkeyPatch,
    executable: Path,
) -> None:
    """Report the selected executable inode as root-owned without changing its mode."""
    real_fstat = os.fstat
    expected = os.stat(executable)
    expected_identity = (expected.st_dev, expected.st_ino)

    def root_owned(file_descriptor: int) -> os.stat_result:
        observed = real_fstat(file_descriptor)
        if (observed.st_dev, observed.st_ino) != expected_identity:
            return observed
        fields = list(observed)
        fields[4] = 0
        return os.stat_result(fields)

    monkeypatch.setattr(physical_basebackup.os, "fstat", root_owned)


@pytest.mark.parametrize("privilege_bit", [stat.S_ISUID, stat.S_ISGID])
def test_setid_pg_basebackup_is_rejected_before_retention(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    privilege_bit: int,
) -> None:
    """A set-user-ID or set-group-ID executable must never gain child authority."""
    executable = tmp_path / "pg_basebackup"
    executable.write_text("#!/bin/sh\nexit 0\n", encoding="utf-8")
    executable.chmod(0o750 | privilege_bit)
    _root_owned_executable_status(monkeypatch, executable)

    with pytest.raises(PostgresPhysicalBaseBackupError, match=_EXECUTABLE_ERROR):
        retained_descriptor = physical_basebackup._retain_pg_basebackup_executable(
            str(executable)
        )
        os.close(retained_descriptor)
