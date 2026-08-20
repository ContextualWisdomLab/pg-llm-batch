# SPDX-License-Identifier: Apache-2.0
"""Regression tests for finite logical-backup output byte authority."""

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


def test_logical_backup_invalidates_output_when_provider_exceeds_byte_budget(
    tmp_path, monkeypatch
):
    path = tmp_path / "backup.dump"
    descriptor = os.open(path, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)

    def oversized_run(argv, **kwargs):
        os.write(kwargs["stdout"], b"PGDMP")
        return subprocess.CompletedProcess(argv, 0)

    monkeypatch.setattr(logical_backup.subprocess, "run", oversized_run)
    try:
        with pytest.raises(
            PostgresLogicalBackupError,
            match="^PostgreSQL logical backup exceeded output byte budget$",
        ):
            create_postgres_logical_backup(
                "safe_service",
                descriptor,
                pg_dump_executable="/usr/bin/pg_dump",
                maximum_output_bytes=4,
            )
        assert os.lseek(descriptor, 0, os.SEEK_CUR) == 0
        assert os.fstat(descriptor).st_size == 0
    finally:
        os.close(descriptor)
