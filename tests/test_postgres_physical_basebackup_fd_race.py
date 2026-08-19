# SPDX-License-Identifier: Apache-2.0
"""Regression for caller output-descriptor replacement during physical backup."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from pg_llm_batch import postgres_physical_basebackup
from pg_llm_batch.postgres_physical_basebackup import create_postgres_physical_basebackup


def _open_private_output(path: Path) -> int:
    """Open one empty owner-only caller output file."""
    return os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)


def test_physical_backup_snapshots_output_fd_before_subprocess_write(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Replacing the caller FD after inspection must not redirect sensitive bytes."""
    original_path = tmp_path / "original-backup.tar"
    replacement_path = tmp_path / "replacement-backup.tar"
    original_fd = _open_private_output(original_path)
    replacement_fd = _open_private_output(replacement_path)
    payload = b"sensitive-cluster-backup"

    def replace_caller_fd_then_write(
        args: object, **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        os.dup2(replacement_fd, original_fd)
        stdout = kwargs["stdout"]
        assert type(stdout) is int
        os.write(stdout, payload)
        return subprocess.CompletedProcess(args, 0, stdout=b"")

    monkeypatch.setattr(
        postgres_physical_basebackup,
        "_retain_pg_basebackup_executable",
        lambda _path: os.open(os.devnull, os.O_RDONLY),
    )
    monkeypatch.setattr(
        postgres_physical_basebackup.subprocess,
        "run",
        replace_caller_fd_then_write,
    )
    try:
        result = create_postgres_physical_basebackup(
            "recovery-source",
            original_fd,
            pg_basebackup_executable="/usr/bin/pg_basebackup",
        )
    finally:
        os.close(replacement_fd)
        os.close(original_fd)

    assert result.size_bytes == len(payload)
    assert original_path.read_bytes() == payload
    assert replacement_path.read_bytes() == b""
