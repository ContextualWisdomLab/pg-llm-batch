# SPDX-License-Identifier: Apache-2.0
"""Regression tests for logical-backup output-descriptor identity."""

from __future__ import annotations

import os
import subprocess

import pytest

import pg_llm_batch.postgres_logical_backup as logical_backup
from pg_llm_batch.postgres_logical_backup import (
    PostgresLogicalBackupError,
    create_postgres_logical_backup,
)


def test_logical_backup_rejects_output_descriptor_substitution(
    tmp_path, monkeypatch
):
    """Reject same-number descriptor replacement without destroying replacement data."""
    original_path = tmp_path / "original.dump"
    replacement_path = tmp_path / "replacement.dump"
    descriptor = os.open(original_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    replacement_descriptor = os.open(
        replacement_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600
    )

    def substitute_output(argv, **kwargs):
        os.dup2(replacement_descriptor, kwargs["stdout"])
        os.write(kwargs["stdout"], b"PGDMP-replacement")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(logical_backup.subprocess, "run", substitute_output)
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
        assert os.read(descriptor, 1024) == b"PGDMP-replacement"
    finally:
        os.close(replacement_descriptor)
        os.close(descriptor)


def test_logical_backup_failure_does_not_invalidate_substituted_descriptor(
    tmp_path, monkeypatch
):
    """Preserve an unrelated replacement file when pg_dump fails after substitution."""
    original_path = tmp_path / "original-failure.dump"
    replacement_path = tmp_path / "replacement-failure.dump"
    descriptor = os.open(original_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    replacement_descriptor = os.open(
        replacement_path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600
    )

    def substitute_then_fail(argv, **kwargs):
        os.dup2(replacement_descriptor, kwargs["stdout"])
        os.write(kwargs["stdout"], b"operator-owned-replacement")
        return subprocess.CompletedProcess(argv, 1)

    monkeypatch.setattr(logical_backup.subprocess, "run", substitute_then_fail)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match=r"^PostgreSQL logical backup command failed$",
        ):
            create_postgres_logical_backup(
                "safe_service",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )

        os.lseek(descriptor, 0, os.SEEK_SET)
        assert os.read(descriptor, 1024) == b"operator-owned-replacement"
    finally:
        os.close(replacement_descriptor)
        os.close(descriptor)
