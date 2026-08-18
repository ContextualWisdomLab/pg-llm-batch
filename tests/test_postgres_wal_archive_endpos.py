# SPDX-License-Identifier: Apache-2.0
"""Regression contract for a finite PostgreSQL WAL receive end position."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import NoReturn

import pytest

from pg_llm_batch.postgres_wal_archive import (
    PostgresWalArchiveError,
    receive_postgres_wal_archive,
)


def test_zero_lsn_is_rejected_before_pg_receivewal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """PostgreSQL's InvalidXLogRecPtr sentinel cannot disable the finite stop boundary."""
    archive_path = tmp_path / "wal-archive-zero-lsn"
    archive_path.mkdir(mode=0o700)
    descriptor = os.open(archive_path, os.O_RDONLY | os.O_DIRECTORY)

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("0/0 must fail before pg_receivewal executes")

    monkeypatch.setattr(subprocess, "run", forbidden)
    try:
        with pytest.raises(
            PostgresWalArchiveError,
            match="^invalid PostgreSQL WAL archive parameters$",
        ):
            receive_postgres_wal_archive(
                "physical_replication_source",
                "pg_llm_batch_archive",
                "0/0",
                descriptor,
                pg_receivewal_executable="/usr/bin/pg_receivewal",
            )
    finally:
        os.close(descriptor)
