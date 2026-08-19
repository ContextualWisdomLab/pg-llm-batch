# SPDX-License-Identifier: Apache-2.0
"""Regression for caller seek races against physical backup output."""

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


def test_physical_backup_child_offset_is_independent_from_caller_seek(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A caller seek after snapshot must not move the child backup stream offset."""
    output_path = tmp_path / "physical-backup.tar"
    output_fd = _open_private_output(output_path)
    payload = b"sensitive-cluster-backup"

    def seek_caller_then_write(
        args: object, **kwargs: object
    ) -> subprocess.CompletedProcess[bytes]:
        os.lseek(output_fd, 4096, os.SEEK_SET)
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
        seek_caller_then_write,
    )
    try:
        result = create_postgres_physical_basebackup(
            "recovery-source",
            output_fd,
            pg_basebackup_executable="/usr/bin/pg_basebackup",
        )
    finally:
        os.close(output_fd)

    assert result.size_bytes == len(payload)
    assert output_path.read_bytes() == payload
