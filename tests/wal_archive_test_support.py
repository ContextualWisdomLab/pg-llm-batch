# SPDX-License-Identifier: Apache-2.0
"""Focused retained-authority support for non-capacity WAL archive tests."""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest

import pg_llm_batch.postgres_wal_archive as wal_archive


@pytest.fixture
def install_retained_pg_receivewal_stub(
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Alias test authority while dedicated tests exercise production trust boundaries."""
    retained_authority: dict[str, int] = {}
    real_retain_archive_directory = wal_archive._retain_archive_directory
    real_close = os.close

    def retain_archive_directory(archive_directory_descriptor: int) -> int:
        private_descriptor = real_retain_archive_directory(
            archive_directory_descriptor
        )
        retained_authority["archive"] = private_descriptor
        return private_descriptor

    def retain_test_executable(_pg_receivewal_executable: str) -> int:
        return retained_authority["archive"]

    def accept_bounded_test_filesystem(
        _archive_directory_descriptor: int,
        maximum_archive_bytes: int,
    ) -> int:
        return maximum_archive_bytes

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
    monkeypatch.setattr(
        wal_archive,
        "_inspect_archive_filesystem_budget",
        accept_bounded_test_filesystem,
    )
    try:
        yield
    finally:
        private_descriptor = retained_authority.get("archive")
        if private_descriptor is not None:
            try:
                real_close(private_descriptor)
            except OSError:
                pass
