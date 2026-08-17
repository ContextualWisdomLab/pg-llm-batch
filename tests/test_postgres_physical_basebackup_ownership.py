# SPDX-License-Identifier: Apache-2.0
"""Regression contract for physical backup output ownership."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import NoReturn

import pytest

from pg_llm_batch.postgres_physical_basebackup import (
    PostgresPhysicalBaseBackupError,
    create_postgres_physical_basebackup,
)


def test_output_must_be_owned_by_effective_process_user(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Owner-only mode is insufficient when another OS user owns the backup file."""
    path = tmp_path / "foreign-owner-basebackup.tar"
    descriptor = os.open(path, os.O_RDWR | os.O_CREAT | os.O_EXCL, 0o600)
    actual_owner = os.fstat(descriptor).st_uid
    monkeypatch.setattr(os, "geteuid", lambda: actual_owner + 1)

    def forbidden_subprocess(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("foreign-owned backup output must fail before subprocess execution")

    monkeypatch.setattr(subprocess, "run", forbidden_subprocess)
    try:
        with pytest.raises(
            PostgresPhysicalBaseBackupError,
            match="owned by the effective process user",
        ):
            create_postgres_physical_basebackup(
                "physical_backup_source",
                descriptor,
                pg_basebackup_executable="/usr/bin/pg_basebackup",
            )
    finally:
        os.close(descriptor)
