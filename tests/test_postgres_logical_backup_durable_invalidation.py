# SPDX-License-Identifier: Apache-2.0
"""Regression tests for durable logical-backup failure invalidation."""

from __future__ import annotations

import os
import subprocess

import pytest

import pg_llm_batch.postgres_logical_backup as logical_backup
from pg_llm_batch.postgres_logical_backup import (
    PostgresLogicalBackupError,
    create_postgres_logical_backup,
)
from tests.logical_backup_test_support import install_retained_pg_dump_stub


pytestmark = pytest.mark.usefixtures(install_retained_pg_dump_stub.__name__)


def test_logical_backup_fsyncs_successful_failure_invalidation(tmp_path, monkeypatch):
    path = tmp_path / "backup.dump"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    fsync_calls: list[int] = []

    def failed_run(argv, **kwargs):
        os.write(kwargs["stdout"], b"partial-sensitive-backup")
        return subprocess.CompletedProcess(argv, 2)

    def record_fsync(target_descriptor):
        fsync_calls.append(target_descriptor)

    monkeypatch.setattr(logical_backup.subprocess, "run", failed_run)
    monkeypatch.setattr(logical_backup.os, "fsync", record_fsync)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup command failed$",
        ):
            create_postgres_logical_backup(
                "safe_service",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
        assert path.read_bytes() == b""
        assert len(fsync_calls) == 1
    finally:
        os.close(descriptor)


def test_logical_backup_reports_failure_invalidation_fsync_error(tmp_path, monkeypatch):
    path = tmp_path / "backup.dump"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)

    def failed_run(argv, **kwargs):
        os.write(kwargs["stdout"], b"partial-sensitive-backup")
        return subprocess.CompletedProcess(argv, 2)

    monkeypatch.setattr(logical_backup.subprocess, "run", failed_run)
    monkeypatch.setattr(
        logical_backup.os,
        "fsync",
        lambda _descriptor: (_ for _ in ()).throw(OSError("private sync detail")),
    )
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup output could not be invalidated$",
        ) as caught:
            create_postgres_logical_backup(
                "safe_service",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
        assert "private" not in str(caught.value)
        assert path.read_bytes() == b""
    finally:
        os.close(descriptor)
