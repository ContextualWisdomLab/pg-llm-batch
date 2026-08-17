# SPDX-License-Identifier: Apache-2.0
"""Inspection-failure regressions for bounded PostgreSQL WAL reception."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pg_llm_batch.postgres_wal_archive import (
    PostgresWalArchiveError,
    receive_postgres_wal_archive,
)


def test_archive_directory_listing_failure_is_content_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Directory-entry inspection failures disclose no lower-layer diagnostic text."""
    path = tmp_path / "wal-archive"
    path.mkdir(mode=0o700)
    descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)

    def broken_listdir(_descriptor: int) -> list[str]:
        raise OSError("sensitive archive directory diagnostic")

    monkeypatch.setattr(os, "listdir", broken_listdir)
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
