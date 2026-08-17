# SPDX-License-Identifier: Apache-2.0
"""Regress fail-closed initial seek handling for PostgreSQL logical restore."""

from __future__ import annotations

import os

import pytest

import pg_llm_batch.postgres_logical_restore as logical_restore
from pg_llm_batch.postgres_logical_restore import (
    PostgresLogicalRestoreError,
    restore_postgres_logical_backup,
)


def test_restore_normalizes_initial_seek_failure(tmp_path, monkeypatch):
    """Reject an unseekable archive without leaking detail or starting pg_restore."""
    archive_path = tmp_path / "backup.dump"
    descriptor = os.open(archive_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    os.write(descriptor, b"PGDMP-archive")
    os.lseek(descriptor, 0, os.SEEK_SET)
    real_lseek = os.lseek
    called = False

    def failing_lseek(target_descriptor, offset, whence):
        if target_descriptor == descriptor:
            raise OSError("secret initial seek detail")
        return real_lseek(target_descriptor, offset, whence)

    def forbidden_run(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("subprocess must not run")

    monkeypatch.setattr(logical_restore.os, "lseek", failing_lseek)
    monkeypatch.setattr(logical_restore.subprocess, "run", forbidden_run)
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match=r"^PostgreSQL logical restore archive could not be inspected$",
        ) as caught:
            restore_postgres_logical_backup(
                "safe_service",
                descriptor,
                source_superusers_trusted=True,
                pg_restore_executable="/usr/bin/pg_restore",
            )
        assert "secret" not in str(caught.value)
        assert called is False
    finally:
        os.close(descriptor)
