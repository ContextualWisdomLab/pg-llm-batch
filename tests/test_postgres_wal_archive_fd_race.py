# SPDX-License-Identifier: Apache-2.0
"""Regression for caller archive-directory FD replacement during WAL reception."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from pg_llm_batch import postgres_wal_archive
from pg_llm_batch.postgres_wal_archive import receive_postgres_wal_archive


_WAL_NAME = "000000010000000000000001"


def _open_private_directory(path: Path) -> int:
    """Open one owner-only caller archive directory."""
    path.mkdir(mode=0o700)
    return os.open(path, os.O_RDONLY | os.O_DIRECTORY)


def test_wal_receive_snapshots_archive_fd_before_subprocess_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replacing the caller FD after inspection must not redirect sensitive WAL bytes."""
    original_directory = tmp_path / "original-wal"
    replacement_directory = tmp_path / "replacement-wal"
    original_fd = _open_private_directory(original_directory)
    replacement_fd = _open_private_directory(replacement_directory)

    def replace_caller_fd_then_write(
        args: object, **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        os.dup2(replacement_fd, original_fd)
        pass_fds = kwargs["pass_fds"]
        assert isinstance(pass_fds, tuple) and len(pass_fds) == 1
        target_fd = pass_fds[0]
        wal_fd = os.open(
            _WAL_NAME,
            os.O_WRONLY | os.O_CREAT | os.O_EXCL,
            0o600,
            dir_fd=target_fd,
        )
        try:
            os.write(wal_fd, b"sensitive-wal")
        finally:
            os.close(wal_fd)
        return subprocess.CompletedProcess(args, 0, stdout=b"")

    monkeypatch.setattr(
        postgres_wal_archive.subprocess,
        "run",
        replace_caller_fd_then_write,
    )
    try:
        result = receive_postgres_wal_archive(
            "recovery-source",
            "recovery_slot",
            "0/1000000",
            original_fd,
            pg_receivewal_executable="/usr/bin/pg_receivewal",
        )
    finally:
        os.close(replacement_fd)
        os.close(original_fd)

    assert result.end_lsn == "0/1000000"
    assert (original_directory / _WAL_NAME).read_bytes() == b"sensitive-wal"
    assert not (replacement_directory / _WAL_NAME).exists()
