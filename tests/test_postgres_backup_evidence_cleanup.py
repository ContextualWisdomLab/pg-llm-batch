# SPDX-License-Identifier: Apache-2.0
"""Descriptor-cleanup regressions for PostgreSQL backup artifact evidence."""

from __future__ import annotations

import os
import stat
from pathlib import Path

import pytest

from pg_llm_batch.postgres_backup_evidence import (
    PostgresBackupEvidenceError,
    inspect_postgres_backup_artifact,
)


def _fail_regular_file_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Make only regular-file descriptor closure fail with a sensitive diagnostic."""
    original_close = os.close
    original_fstat = os.fstat

    def failing_close(file_descriptor: int) -> None:
        status = original_fstat(file_descriptor)
        if stat.S_ISREG(status.st_mode):
            raise OSError("secret cleanup diagnostic")
        original_close(file_descriptor)

    monkeypatch.setattr(os, "close", failing_close)


def _fail_first_directory_close(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Close then report failure for only the first directory descriptor cleanup."""
    original_close = os.close
    original_fstat = os.fstat
    failed = False

    def failing_close(file_descriptor: int) -> None:
        nonlocal failed
        status = original_fstat(file_descriptor)
        if not failed and stat.S_ISDIR(status.st_mode):
            failed = True
            original_close(file_descriptor)
            raise OSError("secret parent cleanup diagnostic")
        original_close(file_descriptor)

    monkeypatch.setattr(os, "close", failing_close)


def test_successful_inspection_normalizes_artifact_close_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Use one fixed content-free package error when final descriptor close fails."""
    artifact = tmp_path / "backup.dump"
    artifact.write_bytes(b"backup")
    _fail_regular_file_close(monkeypatch)

    with pytest.raises(PostgresBackupEvidenceError) as raised:
        inspect_postgres_backup_artifact(str(artifact))

    assert str(raised.value) == "PostgreSQL backup artifact descriptor could not be closed"
    assert "secret cleanup diagnostic" not in str(raised.value)
    assert str(artifact) not in str(raised.value)


def test_artifact_close_failure_does_not_mask_existing_read_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve the primary bounded read error when best-effort cleanup also fails."""
    artifact = tmp_path / "backup.dump"
    artifact.write_bytes(b"backup")
    _fail_regular_file_close(monkeypatch)

    def failing_read(file_descriptor: int, count: int) -> bytes:
        del file_descriptor, count
        raise OSError("secret read diagnostic")

    monkeypatch.setattr(os, "read", failing_read)

    with pytest.raises(PostgresBackupEvidenceError) as raised:
        inspect_postgres_backup_artifact(str(artifact))

    assert str(raised.value) == "PostgreSQL backup artifact could not be read"
    assert "secret read diagnostic" not in str(raised.value)
    assert "secret cleanup diagnostic" not in str(raised.value)


def test_parent_descriptor_close_failure_is_content_free(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normalize cleanup failure while traversing a parent directory descriptor."""
    nested = tmp_path / "nested"
    nested.mkdir()
    (nested / "backup.dump").write_bytes(b"backup")
    monkeypatch.chdir(tmp_path)
    _fail_first_directory_close(monkeypatch)

    with pytest.raises(PostgresBackupEvidenceError) as raised:
        inspect_postgres_backup_artifact("nested/backup.dump")

    assert str(raised.value) == "PostgreSQL backup artifact descriptor could not be closed"
    assert "secret parent cleanup diagnostic" not in str(raised.value)


def test_parent_close_failure_does_not_mask_existing_open_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve the primary bounded open error when parent cleanup also reports failure."""
    monkeypatch.chdir(tmp_path)
    _fail_first_directory_close(monkeypatch)

    with pytest.raises(PostgresBackupEvidenceError) as raised:
        inspect_postgres_backup_artifact("missing.dump")

    assert str(raised.value) == "PostgreSQL backup artifact could not be opened"
    assert "secret parent cleanup diagnostic" not in str(raised.value)
