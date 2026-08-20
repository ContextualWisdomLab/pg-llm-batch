# SPDX-License-Identifier: Apache-2.0
"""Focused retained-executable support for non-authority WAL archive tests."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

import pg_llm_batch.postgres_wal_archive as wal_archive


@pytest.fixture
def install_retained_pg_receivewal_stub(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Provide retained tool authority without assuming a runner pg_receivewal."""
    executable = tmp_path / "wal-archive-test-pg_receivewal"
    executable.write_bytes(b"test-only retained pg_receivewal bytes\n")
    executable.chmod(0o500)
    base_descriptor = os.open(executable, os.O_RDONLY)
    real_close = os.close
    real_dup = os.dup

    def retain_test_executable(_pg_receivewal_executable: str) -> int:
        return real_dup(base_descriptor)

    monkeypatch.setattr(
        wal_archive,
        "_retain_pg_receivewal_executable",
        retain_test_executable,
    )
    try:
        yield
    finally:
        real_close(base_descriptor)
