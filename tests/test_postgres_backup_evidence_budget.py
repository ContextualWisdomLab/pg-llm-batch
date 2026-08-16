# SPDX-License-Identifier: Apache-2.0
"""Work-budget regressions for PostgreSQL backup artifact evidence."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pg_llm_batch.postgres_backup_evidence import (
    PostgresBackupEvidenceError,
    inspect_postgres_backup_artifact,
)


class _HostileInt(int):
    """Represent a caller-owned integer subtype that must not gain authority."""


@pytest.mark.parametrize(
    "invalid_budget",
    [0, -1, True, _HostileInt(4), (1 << 63), "4"],
)
def test_inspector_rejects_invalid_work_budget_before_open(
    invalid_budget: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require an exact positive signed-integer work budget before filesystem access."""
    opened = False

    def forbidden_open(*args: object, **kwargs: object) -> int:
        nonlocal opened
        del args, kwargs
        opened = True
        raise AssertionError("filesystem access must not occur")

    monkeypatch.setattr(os, "open", forbidden_open)

    with pytest.raises(PostgresBackupEvidenceError, match="invalid backup artifact size budget"):
        inspect_postgres_backup_artifact(
            "/tmp/backup.dump",
            maximum_size_bytes=invalid_budget,  # type: ignore[arg-type]
        )

    assert opened is False


def test_inspector_rejects_initial_size_above_explicit_budget_before_read(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject an already-oversized backup before any hashing work is performed."""
    artifact = tmp_path / "backup.dump"
    artifact.write_bytes(b"backup")
    read_started = False

    def forbidden_read(file_descriptor: int, count: int) -> bytes:
        nonlocal read_started
        del file_descriptor, count
        read_started = True
        raise AssertionError("oversized artifacts must not be read")

    monkeypatch.setattr(os, "read", forbidden_read)

    with pytest.raises(PostgresBackupEvidenceError, match="positive bounded size"):
        inspect_postgres_backup_artifact(str(artifact), maximum_size_bytes=4)

    assert read_started is False


def test_inspector_caps_each_stream_read_at_remaining_budget(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reach final metadata validation without reading beyond the declared byte budget."""
    artifact = tmp_path / "growing.dump"
    artifact.write_bytes(b"x")
    remaining_budget = 4
    requested_counts: list[int] = []
    original_fstat = os.fstat
    fstat_calls = 0

    def bounded_growth_read(file_descriptor: int, count: int) -> bytes:
        nonlocal remaining_budget
        del file_descriptor
        assert 0 < count <= remaining_budget
        requested_counts.append(count)
        chunk = b"abcd"[:count]
        remaining_budget -= len(chunk)
        return chunk

    def tracking_fstat(file_descriptor: int) -> os.stat_result:
        nonlocal fstat_calls
        fstat_calls += 1
        return original_fstat(file_descriptor)

    monkeypatch.setattr(os, "read", bounded_growth_read)
    monkeypatch.setattr(os, "fstat", tracking_fstat)

    with pytest.raises(PostgresBackupEvidenceError, match="changed during inspection"):
        inspect_postgres_backup_artifact(str(artifact), maximum_size_bytes=4)

    assert requested_counts == [4]
    assert remaining_budget == 0
    assert fstat_calls == 2


def test_inspector_accepts_explicit_budget_covering_artifact(tmp_path: Path) -> None:
    """Allow operators to raise the work budget explicitly for a known backup size."""
    artifact = tmp_path / "backup.dump"
    artifact.write_bytes(b"backup")

    evidence = inspect_postgres_backup_artifact(str(artifact), maximum_size_bytes=6)

    assert evidence.size_bytes == 6
