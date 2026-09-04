# SPDX-License-Identifier: Apache-2.0
"""Completion-authority regressions for bounded PostgreSQL WAL reception."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

import pytest

from pg_llm_batch.postgres_wal_archive import (
    PostgresWalArchiveResult,
    receive_postgres_wal_archive,
)
from tests.wal_archive_test_support import install_retained_pg_receivewal_stub


pytestmark = pytest.mark.usefixtures(install_retained_pg_receivewal_stub.__name__)


def test_clean_receiver_exit_records_request_without_claiming_end_lsn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Exit status zero alone must not assert that the requested end LSN was reached."""
    archive_path = tmp_path / "wal-archive"
    archive_path.mkdir(mode=0o700)
    descriptor = os.open(archive_path, os.O_RDONLY | os.O_DIRECTORY)

    def signal_indistinguishable_exit(
        arguments: list[str],
        **_kwargs: object,
    ) -> subprocess.CompletedProcess[bytes]:
        # PostgreSQL documents handled SIGINT/SIGTERM as exit status zero, the same
        # status observed after --endpos completion. subprocess cannot distinguish
        # those causes once pg_receivewal handles the signal itself.
        return subprocess.CompletedProcess(arguments, 0)

    monkeypatch.setattr(subprocess, "run", signal_indistinguishable_exit)
    try:
        result = receive_postgres_wal_archive(
            "physical_replication_source",
            "pg_llm_batch_archive",
            "16/B374D848",
            descriptor,
            pg_receivewal_executable="/usr/bin/pg_receivewal",
        )
    finally:
        os.close(descriptor)

    assert result == PostgresWalArchiveResult(requested_end_lsn="16/B374D848")
    assert not hasattr(result, "end_lsn")
