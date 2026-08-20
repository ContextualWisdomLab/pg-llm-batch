# SPDX-License-Identifier: Apache-2.0
"""Non-blocking executable-retention regressions for physical base backup."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import pg_llm_batch.postgres_physical_basebackup as physical_basebackup
from pg_llm_batch.postgres_physical_basebackup import PostgresPhysicalBaseBackupError


_EXECUTABLE_ERROR = "^PostgreSQL physical base-backup executable is unsafe$"


def test_pg_basebackup_fifo_open_is_nonblocking_and_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A FIFO-shaped executable token must not block before regular-file rejection."""
    executable = tmp_path / "pg_basebackup"
    os.mkfifo(executable, 0o700)
    real_open = os.open

    def guarded_open(
        path: str | bytes | os.PathLike[str] | os.PathLike[bytes],
        flags: int,
        mode: int = 0o777,
        *,
        dir_fd: int | None = None,
    ) -> int:
        if os.fspath(path) == str(executable) and flags & os.O_NONBLOCK == 0:
            raise AssertionError("FIFO executable open would block without O_NONBLOCK")
        return real_open(path, flags, mode, dir_fd=dir_fd)

    monkeypatch.setattr(physical_basebackup.os, "open", guarded_open)

    with pytest.raises(PostgresPhysicalBaseBackupError, match=_EXECUTABLE_ERROR):
        retained_descriptor = physical_basebackup._retain_pg_basebackup_executable(
            str(executable)
        )
        os.close(retained_descriptor)
