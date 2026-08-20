# SPDX-License-Identifier: Apache-2.0
"""Focused retained-executable support for non-authority WAL archive tests."""

from __future__ import annotations

from collections.abc import Iterator

import pytest

import pg_llm_batch.postgres_wal_archive as wal_archive


@pytest.fixture
def install_retained_pg_receivewal_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Alias retained test authority without assuming a runner pg_receivewal."""
    retained_authority: dict[str, int] = {}
    real_retain_archive_directory = wal_archive._retain_archive_directory

    def retain_archive_directory(archive_directory_descriptor: int) -> int:
        private_descriptor = real_retain_archive_directory(
            archive_directory_descriptor
        )
        retained_authority["archive"] = private_descriptor
        return private_descriptor

    def retain_test_executable(_pg_receivewal_executable: str) -> int:
        return retained_authority["archive"]

    monkeypatch.setattr(
        wal_archive,
        "_retain_archive_directory",
        retain_archive_directory,
    )
    monkeypatch.setattr(
        wal_archive,
        "_retain_pg_receivewal_executable",
        retain_test_executable,
    )
    yield
