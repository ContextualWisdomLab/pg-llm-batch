# SPDX-License-Identifier: Apache-2.0
"""Regression tests for lifecycle-outbox migration-file authority."""

from pathlib import Path

import pytest

import pg_llm_batch.context_lifecycle_outbox as lifecycle_outbox
from pg_llm_batch.context_lifecycle_outbox import apply_context_lifecycle_outbox_schema
from pg_llm_batch.exceptions import ConfigError


class _DatabaseMustNotOpen:
    """Reject database access before migration-file authority is admitted."""

    def connect(self, _dsn: str) -> None:
        """Fail if unsafe migration bytes reach the database boundary."""
        raise AssertionError("database opened before migration file validation")


def _deny_database(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install a database boundary that proves file validation happens first."""
    monkeypatch.setattr(lifecycle_outbox, "_require_psycopg", lambda: None)
    monkeypatch.setattr(lifecycle_outbox, "psycopg", _DatabaseMustNotOpen())


def test_explicit_migration_rejects_oversized_file_before_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Operator-selected migration SQL must have a finite package-owned byte budget."""
    _deny_database(monkeypatch)
    migration = tmp_path / "oversized.sql"
    migration.write_bytes(b"SELECT 1;\n" + b"-" * (1024 * 1024))

    with pytest.raises(ConfigError, match="migration file"):
        apply_context_lifecycle_outbox_schema("postgresql://unit", str(migration))


def test_explicit_migration_rejects_final_symlink_before_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A selected path must not redirect migration authority through a final symlink."""
    _deny_database(monkeypatch)
    target = tmp_path / "reviewed.sql"
    target.write_text("SELECT 1;", encoding="utf-8")
    migration = tmp_path / "selected.sql"
    migration.symlink_to(target)

    with pytest.raises(ConfigError, match="migration file"):
        apply_context_lifecycle_outbox_schema("postgresql://unit", str(migration))


def test_explicit_migration_invalid_utf8_uses_content_free_config_error(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Invalid SQL bytes must not escape the package's fixed migration error boundary."""
    _deny_database(monkeypatch)
    migration = tmp_path / "invalid.sql"
    migration.write_bytes(b"SELECT '\xff';")

    with pytest.raises(ConfigError, match="migration file"):
        apply_context_lifecycle_outbox_schema("postgresql://unit", str(migration))
