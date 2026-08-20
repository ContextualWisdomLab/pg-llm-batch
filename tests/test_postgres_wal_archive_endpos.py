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


@pytest.mark.parametrize("zero_lsn", ("0/0", "00000000/00000000"))
def test_zero_lsn_is_rejected_before_pg_receivewal(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    zero_lsn: str,
) -> None:
    """Every textual zero LSN must fail before the finite receive process executes."""
    archive_path = tmp_path / "wal-archive-zero-lsn"
    archive_path.mkdir(mode=0o700)
    descriptor = os.open(archive_path, os.O_RDONLY | os.O_DIRECTORY)

    def forbidden(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("zero LSN must fail before pg_receivewal executes")

    monkeypatch.setattr(subprocess, "run", forbidden)
    try:
        with pytest.raises(
            PostgresWalArchiveError,
            match="^invalid PostgreSQL WAL archive parameters$",
        ):
            receive_postgres_wal_archive(
                "physical_replication_source",
                "pg_llm_batch_archive",
                zero_lsn,
                descriptor,
                pg_receivewal_executable="/usr/bin/pg_receivewal",
            )
    finally:
        os.close(descriptor)
