# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for logical-backup output descriptor access authority."""

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


def test_logical_backup_rejects_read_only_output_descriptor_before_provider(
    tmp_path, monkeypatch
):
    """A read-only descriptor must not be widened into package write authority."""
    path = tmp_path / "read-only-output.dump"
    path.write_bytes(b"")
    path.chmod(0o600)
    descriptor = os.open(path, os.O_RDONLY)
    provider_called = False

    def successful_run(argv, **kwargs):
        nonlocal provider_called
        provider_called = True
        os.write(kwargs["stdout"], b"PGDMP")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(logical_backup.subprocess, "run", successful_run)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup output descriptor must be writable$",
        ):
            create_postgres_logical_backup(
                "safe_service",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
            )
        assert provider_called is False
        assert path.read_bytes() == b""
    finally:
        os.close(descriptor)
