# SPDX-License-Identifier: Apache-2.0
"""Focused test support for non-executable logical-backup regressions."""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

import pg_llm_batch.postgres_logical_backup as logical_backup


@pytest.fixture
def install_retained_pg_dump_stub(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Iterator[None]:
    """Provide retained descriptor authority without assuming a runner pg_dump."""
    executable = tmp_path / "logical-backup-test-pg_dump"
    executable.write_bytes(b"test-only retained pg_dump bytes\n")
    executable.chmod(0o500)
    base_descriptor = os.open(executable, os.O_RDONLY)
    real_close = os.close
    real_dup = os.dup

    def retain_test_executable(_pg_dump_executable: str) -> int:
        return real_dup(base_descriptor)

    monkeypatch.setattr(
        logical_backup,
        "_retain_pg_dump_executable",
        retain_test_executable,
    )
    try:
        yield
    finally:
        real_close(base_descriptor)
