# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for physical-basebackup output descriptor access authority."""

from __future__ import annotations

import os
import subprocess

import pytest

import pg_llm_batch.postgres_physical_basebackup as physical_basebackup
from pg_llm_batch.postgres_physical_basebackup import (
    PostgresPhysicalBaseBackupError,
    create_postgres_physical_basebackup,
)


@pytest.fixture(autouse=True)
def _retain_hermetic_test_executable(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep descriptor-access tests independent of host PostgreSQL packaging."""

    def retain_test_executable(_path: str) -> int:
        return os.open(os.devnull, os.O_RDONLY)

    monkeypatch.setattr(
        physical_basebackup,
        "_retain_pg_basebackup_executable",
        retain_test_executable,
    )


def test_physical_backup_rejects_read_only_output_descriptor_before_provider(
    tmp_path, monkeypatch
):
    """A read-only descriptor must not be widened into package write authority."""
    path = tmp_path / "read-only-basebackup.tar"
    path.write_bytes(b"")
    path.chmod(0o600)
    descriptor = os.open(path, os.O_RDONLY)
    provider_called = False

    def successful_run(arguments, **kwargs):
        nonlocal provider_called
        provider_called = True
        os.write(kwargs["stdout"], b"physical-basebackup-tar")
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(physical_basebackup.subprocess, "run", successful_run)
    try:
        with pytest.raises(
            PostgresPhysicalBaseBackupError,
            match="^PostgreSQL physical base-backup output descriptor must be writable$",
        ):
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
            )
        assert provider_called is False
        assert path.read_bytes() == b""
    finally:
        os.close(descriptor)
