# SPDX-License-Identifier: Apache-2.0
"""Path-authority regressions for PostgreSQL backup artifact inspection."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from pg_llm_batch.postgres_backup_evidence import (
    PostgresBackupEvidenceError,
    inspect_postgres_backup_artifact,
)


def test_inspector_rejects_symlinked_parent_component(tmp_path: Path) -> None:
    """Reject parent-directory redirects instead of protecting only the final name."""
    outside = tmp_path / "outside"
    outside.mkdir()
    (outside / "backup.dump").write_bytes(b"backup")
    linked = tmp_path / "linked"
    linked.symlink_to(outside, target_is_directory=True)

    with pytest.raises(PostgresBackupEvidenceError, match="could not be opened"):
        inspect_postgres_backup_artifact(str(linked / "backup.dump"))


def test_inspector_rejects_parent_traversal_before_artifact_open(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject parent traversal rather than silently hashing outside the selected tree."""
    outside = tmp_path / "backup.dump"
    outside.write_bytes(b"backup")
    working = tmp_path / "working"
    working.mkdir()
    monkeypatch.chdir(working)

    with pytest.raises(PostgresBackupEvidenceError, match="invalid backup artifact path"):
        inspect_postgres_backup_artifact("../backup.dump")


def test_inspector_rejects_root_without_final_artifact() -> None:
    """Require one final filename instead of accepting the filesystem root."""
    with pytest.raises(PostgresBackupEvidenceError, match="invalid backup artifact path"):
        inspect_postgres_backup_artifact("/")


def test_inspector_accepts_relative_path_without_parent_redirect(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Preserve ordinary relative operator paths under the pinned working directory."""
    payload = b"relative-backup"
    (tmp_path / "backup.dump").write_bytes(payload)
    monkeypatch.chdir(tmp_path)

    evidence = inspect_postgres_backup_artifact("./backup.dump")

    assert evidence.sha256 == hashlib.sha256(payload).hexdigest()
    assert evidence.size_bytes == len(payload)
