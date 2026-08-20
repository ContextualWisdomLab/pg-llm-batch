# SPDX-License-Identifier: Apache-2.0
"""Regress single-field archive metadata mutation during logical restore."""

from __future__ import annotations

import os
import subprocess
from types import SimpleNamespace

import pytest

import pg_llm_batch.postgres_logical_restore as logical_restore
from pg_llm_batch.postgres_logical_restore import (
    PostgresLogicalRestoreError,
    restore_postgres_logical_backup,
)


@pytest.mark.parametrize(
    "metadata_field",
    [
        "st_mode",
        "st_size",
        "st_nlink",
        "st_dev",
        "st_ino",
        "st_mtime_ns",
        "st_ctime_ns",
    ],
)
def test_restore_rejects_single_archive_metadata_mutation(
    tmp_path, monkeypatch, metadata_field
):
    """Reject mutation when exactly one observable archive field changes."""
    archive_path = tmp_path / "backup.dump"
    descriptor = os.open(archive_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    os.write(descriptor, b"PGDMP-archive")
    os.lseek(descriptor, 0, os.SEEK_SET)

    real_fstat = os.fstat
    retained_descriptor = None
    target_calls = 0

    def changing_fstat(target_descriptor):
        nonlocal retained_descriptor, target_calls
        status = real_fstat(target_descriptor)
        if retained_descriptor is None:
            retained_descriptor = target_descriptor
        if target_descriptor != retained_descriptor:
            return status
        target_calls += 1
        if target_calls == 1:
            return status
        values = {
            "st_mode": status.st_mode,
            "st_size": status.st_size,
            "st_nlink": status.st_nlink,
            "st_dev": status.st_dev,
            "st_ino": status.st_ino,
            "st_mtime_ns": status.st_mtime_ns,
            "st_ctime_ns": status.st_ctime_ns,
        }
        values[metadata_field] += 1
        return SimpleNamespace(**values)

    def consume_archive(argv, **kwargs):
        while os.read(kwargs["stdin"], 1024):
            pass
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(logical_restore.os, "fstat", changing_fstat)
    monkeypatch.setattr(logical_restore.subprocess, "run", consume_archive)
    try:
        with pytest.raises(
            PostgresLogicalRestoreError,
            match="^PostgreSQL logical restore archive changed during execution$",
        ):
            restore_postgres_logical_backup(
                "isolated_restore",
                descriptor,
                source_superusers_trusted=True,
                pg_restore_executable="/usr/bin/pg_restore",
            )
    finally:
        os.close(descriptor)
