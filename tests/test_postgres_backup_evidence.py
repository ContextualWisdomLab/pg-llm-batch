# SPDX-License-Identifier: Apache-2.0
"""Security and integrity regressions for PostgreSQL backup artifact evidence."""

from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

import pg_llm_batch.postgres_backup_evidence as backup_evidence
from pg_llm_batch.postgres_backup_evidence import (
    PostgresBackupArtifactEvidence,
    PostgresBackupEvidenceError,
    inspect_postgres_backup_artifact,
    postgres_backup_artifact_evidence_was_inspected,
)


def test_inspector_returns_content_free_deterministic_identity(tmp_path: Path) -> None:
    """Hash one regular backup without returning its path or business content."""
    artifact = tmp_path / "tenant-export.dump"
    payload = b"authorized-business-content\x00still-private"
    artifact.write_bytes(payload)

    evidence = inspect_postgres_backup_artifact(str(artifact))

    assert evidence.sha256 == hashlib.sha256(payload).hexdigest()
    assert evidence.size_bytes == len(payload)
    assert evidence.as_dict() == {
        "sha256": hashlib.sha256(payload).hexdigest(),
        "size_bytes": len(payload),
    }
    assert str(artifact) not in repr(evidence)
    assert payload.decode("utf-8", errors="ignore") not in repr(evidence)
    assert "_inspection_mark" not in evidence.as_dict()
    assert postgres_backup_artifact_evidence_was_inspected(evidence) is True
    assert postgres_backup_artifact_evidence_was_inspected(
        PostgresBackupArtifactEvidence(evidence.sha256, evidence.size_bytes)
    ) is False
    assert postgres_backup_artifact_evidence_was_inspected(object()) is False
    assert postgres_backup_artifact_evidence_was_inspected(replace(evidence)) is False


@pytest.mark.parametrize("invalid_path", ["", "x" * 4097, Path("backup.dump")])
def test_inspector_rejects_untrusted_path_shapes_before_open(
    invalid_path: object,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Require a bounded exact built-in string before filesystem authority."""
    opened = False

    def forbidden_open(*args: object, **kwargs: object) -> int:
        nonlocal opened
        del args, kwargs
        opened = True
        raise AssertionError("filesystem access must not occur")

    monkeypatch.setattr(os, "open", forbidden_open)

    with pytest.raises(PostgresBackupEvidenceError, match="invalid backup artifact path"):
        inspect_postgres_backup_artifact(invalid_path)  # type: ignore[arg-type]

    assert opened is False


def test_inspector_fails_closed_without_no_follow_support(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Refuse evidence generation when secure descriptor flags are unavailable."""
    artifact = tmp_path / "backup.dump"
    artifact.write_bytes(b"backup")
    monkeypatch.setattr(backup_evidence, "_SECURE_FILE_FLAGS_AVAILABLE", False)

    with pytest.raises(PostgresBackupEvidenceError, match="secure backup artifact inspection"):
        inspect_postgres_backup_artifact(str(artifact))


def test_inspector_reports_open_failure_without_reflecting_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normalize operating-system diagnostics without exposing the rejected path."""
    secret_path = "/tmp/password=do-not-log.dump"

    def failing_open(*args: object, **kwargs: object) -> int:
        del args, kwargs
        raise OSError(f"synthetic failure for {secret_path}")

    monkeypatch.setattr(os, "open", failing_open)

    with pytest.raises(PostgresBackupEvidenceError) as raised:
        inspect_postgres_backup_artifact(secret_path)

    assert str(raised.value) == "PostgreSQL backup artifact could not be opened"
    assert secret_path not in str(raised.value)


def test_inspector_reports_initial_stat_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Fail closed when metadata cannot be read from the pinned descriptor."""
    artifact = tmp_path / "backup.dump"
    artifact.write_bytes(b"backup")

    def failing_fstat(file_descriptor: int) -> os.stat_result:
        del file_descriptor
        raise OSError("sensitive stat diagnostic")

    monkeypatch.setattr(os, "fstat", failing_fstat)

    with pytest.raises(PostgresBackupEvidenceError, match="could not be inspected"):
        inspect_postgres_backup_artifact(str(artifact))


def test_inspector_rejects_non_regular_artifact(tmp_path: Path) -> None:
    """Reject directories and other non-regular filesystem objects."""
    directory = tmp_path / "backup-directory"
    directory.mkdir()

    with pytest.raises(PostgresBackupEvidenceError, match="regular file"):
        inspect_postgres_backup_artifact(str(directory))


def test_inspector_rejects_empty_artifact(tmp_path: Path) -> None:
    """Reject empty files because they cannot be accepted as backup evidence."""
    artifact = tmp_path / "empty.dump"
    artifact.touch()

    with pytest.raises(PostgresBackupEvidenceError, match="positive bounded size"):
        inspect_postgres_backup_artifact(str(artifact))


def test_inspector_rejects_artifact_larger_than_postgres_bigint(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep evidence size compatible with a signed PostgreSQL bigint boundary."""
    artifact = tmp_path / "backup.dump"
    artifact.write_bytes(b"backup")
    original_fstat = os.fstat

    def oversized_fstat(file_descriptor: int):  # type: ignore[no-untyped-def]
        status = original_fstat(file_descriptor)
        return SimpleNamespace(
            st_dev=status.st_dev,
            st_ino=status.st_ino,
            st_mode=status.st_mode,
            st_size=(1 << 63),
            st_mtime_ns=status.st_mtime_ns,
            st_ctime_ns=status.st_ctime_ns,
        )

    monkeypatch.setattr(os, "fstat", oversized_fstat)

    with pytest.raises(PostgresBackupEvidenceError, match="positive bounded size"):
        inspect_postgres_backup_artifact(str(artifact))


def test_inspector_rejects_symlink(tmp_path: Path) -> None:
    """Never follow a final-path symlink when producing integrity evidence."""
    target = tmp_path / "target.dump"
    target.write_bytes(b"backup")
    linked = tmp_path / "linked.dump"
    linked.symlink_to(target)

    with pytest.raises(PostgresBackupEvidenceError, match="could not be opened"):
        inspect_postgres_backup_artifact(str(linked))


def test_inspector_reports_streaming_read_failure(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Normalize descriptor read failures without lower-layer diagnostics."""
    artifact = tmp_path / "backup.dump"
    artifact.write_bytes(b"backup")

    def failing_read(file_descriptor: int, count: int) -> bytes:
        del file_descriptor, count
        raise OSError("sensitive read diagnostic")

    monkeypatch.setattr(os, "read", failing_read)

    with pytest.raises(PostgresBackupEvidenceError, match="could not be read"):
        inspect_postgres_backup_artifact(str(artifact))


def test_inspector_rejects_short_stream_against_initial_size(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject incomplete bytes even if descriptor metadata appears unchanged."""
    artifact = tmp_path / "backup.dump"
    artifact.write_bytes(b"backup")
    calls = 0

    def short_read(file_descriptor: int, count: int) -> bytes:
        nonlocal calls
        del file_descriptor, count
        calls += 1
        return b"x" if calls == 1 else b""

    monkeypatch.setattr(os, "read", short_read)

    with pytest.raises(PostgresBackupEvidenceError, match="changed during inspection"):
        inspect_postgres_backup_artifact(str(artifact))


def test_inspector_rejects_identity_change_during_hashing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject same-length artifacts whose pinned inode metadata changes mid-read."""
    artifact = tmp_path / "backup.dump"
    payload = b"backup"
    artifact.write_bytes(payload)
    original_fstat = os.fstat
    calls = 0

    def changing_fstat(file_descriptor: int):  # type: ignore[no-untyped-def]
        nonlocal calls
        status = original_fstat(file_descriptor)
        calls += 1
        if calls == 1:
            return status
        return SimpleNamespace(
            st_dev=status.st_dev,
            st_ino=status.st_ino,
            st_mode=status.st_mode,
            st_size=status.st_size,
            st_mtime_ns=status.st_mtime_ns + 1,
            st_ctime_ns=status.st_ctime_ns,
        )

    monkeypatch.setattr(os, "fstat", changing_fstat)

    with pytest.raises(PostgresBackupEvidenceError, match="changed during inspection"):
        inspect_postgres_backup_artifact(str(artifact))
