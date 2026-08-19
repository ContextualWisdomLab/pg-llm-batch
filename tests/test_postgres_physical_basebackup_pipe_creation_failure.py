# SPDX-License-Identifier: Apache-2.0
"""Regression for physical base-backup pipe creation failure."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

import pg_llm_batch.postgres_physical_basebackup as physical_basebackup
from pg_llm_batch.postgres_physical_basebackup import PostgresPhysicalBaseBackupError


def _open_output(tmp_path: Path) -> tuple[Path, int]:
    """Create one private regular file suitable for the pipe-creation boundary."""
    path = tmp_path / "pipe-creation.tar"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    return path, descriptor


def test_pipe_creation_failure_invalidates_output_without_provider_execution(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A pipe allocation failure must invalidate bytes and expose no OS diagnostic."""
    path, output_descriptor = _open_output(tmp_path)
    os.write(output_descriptor, b"partial-sensitive-backup")

    def fail_pipe() -> tuple[int, int]:
        raise OSError("private pipe creation diagnostic")

    monkeypatch.setattr(physical_basebackup.os, "pipe", fail_pipe)
    try:
        with pytest.raises(
            PostgresPhysicalBaseBackupError,
            match="^PostgreSQL physical base-backup execution failed$",
        ) as caught:
            physical_basebackup._run_pg_basebackup(
                service_name="physical_backup_source",
                output_descriptor=output_descriptor,
                cleanup_descriptor=output_descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
                executable_descriptor=0,
                timeout_seconds=30,
                connect_timeout_seconds=5,
                maximum_output_bytes=1024,
            )
        assert "private pipe creation diagnostic" not in str(caught.value)
        assert path.read_bytes() == b""
        assert os.lseek(output_descriptor, 0, os.SEEK_CUR) == 0
    finally:
        os.close(output_descriptor)
