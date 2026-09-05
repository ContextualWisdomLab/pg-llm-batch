# SPDX-License-Identifier: Apache-2.0
"""Regression tests for lifecycle-outbox migration mode authority."""

import os
from pathlib import Path
import stat
from types import SimpleNamespace

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
    """Install a database boundary proving mode admission precedes PostgreSQL I/O."""
    monkeypatch.setattr(lifecycle_outbox, "_require_psycopg", lambda: None)
    monkeypatch.setattr(lifecycle_outbox, "psycopg", _DatabaseMustNotOpen())


def _with_mode(status: os.stat_result, mode: int) -> SimpleNamespace:
    """Return stable descriptor metadata with only the selected mode changed."""
    return SimpleNamespace(
        st_dev=status.st_dev,
        st_ino=status.st_ino,
        st_mode=mode,
        st_size=status.st_size,
        st_mtime_ns=status.st_mtime_ns,
        st_ctime_ns=status.st_ctime_ns,
    )


def test_explicit_migration_rejects_group_writable_file_before_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Reviewed SQL cannot remain executable authority while another group may write it."""
    _deny_database(monkeypatch)
    migration = tmp_path / "migration.sql"
    migration.write_text("SELECT 1;", encoding="utf-8")
    original_fstat = lifecycle_outbox.os.fstat

    def group_writable(descriptor: int) -> SimpleNamespace:
        status = original_fstat(descriptor)
        return _with_mode(status, status.st_mode | stat.S_IWGRP)

    monkeypatch.setattr(lifecycle_outbox.os, "fstat", group_writable)

    with pytest.raises(ConfigError, match="migration file"):
        apply_context_lifecycle_outbox_schema("postgresql://unit", str(migration))


def test_explicit_migration_rejects_permission_widening_during_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A retained migration must fail if its write authority widens during validation."""
    _deny_database(monkeypatch)
    migration = tmp_path / "migration.sql"
    migration.write_text("SELECT 1;", encoding="utf-8")
    original_fstat = lifecycle_outbox.os.fstat
    calls = 0

    def widen_second_fstat(descriptor: int):
        nonlocal calls
        calls += 1
        status = original_fstat(descriptor)
        if calls == 1:
            return status
        return _with_mode(status, status.st_mode | stat.S_IWOTH)

    monkeypatch.setattr(lifecycle_outbox.os, "fstat", widen_second_fstat)

    with pytest.raises(ConfigError, match="migration file"):
        apply_context_lifecycle_outbox_schema("postgresql://unit", str(migration))
