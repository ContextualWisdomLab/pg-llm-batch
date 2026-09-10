# SPDX-License-Identifier: Apache-2.0
"""Regression tests for logical-backup validation edge paths."""

from __future__ import annotations

import os
import subprocess
from types import SimpleNamespace

import pytest

import pg_llm_batch.postgres_logical_backup as logical_backup
from pg_llm_batch.postgres_logical_backup import (
    PostgresLogicalBackupError,
    create_postgres_logical_backup,
)
from tests.logical_backup_test_support import install_retained_pg_dump_stub


pytestmark = pytest.mark.usefixtures(install_retained_pg_dump_stub.__name__)


def _open_private_output(tmp_path):
    path = tmp_path / "validation-edge.dump"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    return path, descriptor


def test_logical_backup_normalizes_retained_output_inspection_failure(
    tmp_path, monkeypatch
):
    """Keep retained-file inspection failures bounded and content-free."""
    _path, descriptor = _open_private_output(tmp_path)
    subprocess_called = False

    def fail_fstat(_descriptor):
        raise OSError("secret retained-output metadata failure")

    def forbidden_run(*_args, **_kwargs):
        nonlocal subprocess_called
        subprocess_called = True
        raise AssertionError("subprocess must not run")

    monkeypatch.setattr(logical_backup.os, "fstat", fail_fstat)
    monkeypatch.setattr(logical_backup.subprocess, "run", forbidden_run)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match=r"^PostgreSQL logical backup output could not be inspected$",
        ) as caught:
            create_postgres_logical_backup(
                "safe_service",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
        assert "secret" not in str(caught.value)
        assert subprocess_called is False
    finally:
        os.close(descriptor)


def test_logical_backup_rejects_final_output_identity_drift(tmp_path, monkeypatch):
    """Invalidate output when final device/inode identity differs from inspection."""
    _path, descriptor = _open_private_output(tmp_path)
    real_fstat = os.fstat
    fstat_calls = 0

    def drift_final_identity(target_descriptor):
        nonlocal fstat_calls
        status = real_fstat(target_descriptor)
        fstat_calls += 1
        if fstat_calls == 1:
            return status
        return SimpleNamespace(
            st_mode=status.st_mode,
            st_nlink=status.st_nlink,
            st_size=status.st_size,
            st_dev=status.st_dev,
            st_ino=status.st_ino + 1,
            st_uid=status.st_uid,
        )

    def write_successfully(argv, **kwargs):
        os.write(kwargs["stdout"], b"PGDMP-safe")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(logical_backup.os, "fstat", drift_final_identity)
    monkeypatch.setattr(logical_backup.subprocess, "run", write_successfully)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match=r"^PostgreSQL logical backup output changed during execution$",
        ):
            create_postgres_logical_backup(
                "safe_service",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
        os.lseek(descriptor, 0, os.SEEK_SET)
        assert os.read(descriptor, 1024) == b""
    finally:
        os.close(descriptor)
