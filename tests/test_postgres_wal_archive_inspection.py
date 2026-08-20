# SPDX-License-Identifier: Apache-2.0
"""Inspection-failure regressions for bounded PostgreSQL WAL reception."""

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
from tests.wal_archive_test_support import install_retained_pg_receivewal_stub


pytestmark = pytest.mark.usefixtures(install_retained_pg_receivewal_stub.__name__)


def test_archive_directory_listing_failure_is_content_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Directory-entry inspection failures disclose no lower-layer diagnostic text."""
    path = tmp_path / "wal-archive"
    path.mkdir(mode=0o700)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)

    def broken_scandir(_descriptor: int) -> NoReturn:
        raise OSError("sensitive archive directory diagnostic")

    def forbidden_run(*_args: object, **_kwargs: object) -> NoReturn:
        raise AssertionError("failed directory inspection must precede pg_receivewal")

    monkeypatch.setattr(os, "scandir", broken_scandir)
    monkeypatch.setattr(subprocess, "run", forbidden_run)
    try:
        with pytest.raises(PostgresWalArchiveError, match="could not be inspected") as caught:
            receive_postgres_wal_archive(
                "physical_replication_source",
                "pg_llm_batch_archive",
                "16/B374D848",
                descriptor,
                pg_receivewal_executable="/usr/bin/pg_receivewal",
            )
        assert "sensitive" not in str(caught.value)
    finally:
        os.close(descriptor)


def test_archive_directory_emptiness_check_does_not_materialize_listing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Empty-directory proof must inspect at most one entry instead of building a list."""
    path = tmp_path / "bounded-empty-wal-archive"
    path.mkdir(mode=0o700)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)

    def forbidden_listdir(_descriptor: int) -> NoReturn:
        raise AssertionError("archive emptiness must not materialize every directory entry")

    monkeypatch.setattr(os, "listdir", forbidden_listdir)
    monkeypatch.setattr(
        subprocess,
        "run",
        lambda arguments, **_kwargs: subprocess.CompletedProcess(arguments, 0),
    )
    try:
        receive_postgres_wal_archive(
            "physical_replication_source",
            "pg_llm_batch_archive",
            "16/B374D848",
            descriptor,
            pg_receivewal_executable="/usr/bin/pg_receivewal",
        )
    finally:
        os.close(descriptor)
