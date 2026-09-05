# SPDX-License-Identifier: Apache-2.0
"""Regression tests for lifecycle-outbox migration-file authority."""

import os
from pathlib import Path
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


def test_explicit_migration_fails_closed_without_secure_open_flags(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A runtime without no-follow and nonblocking open support cannot admit a path."""
    _deny_database(monkeypatch)
    migration = tmp_path / "migration.sql"
    migration.write_text("SELECT 1;", encoding="utf-8")
    monkeypatch.setattr(lifecycle_outbox, "_SECURE_MIGRATION_FLAGS_AVAILABLE", False)

    with pytest.raises(ConfigError, match="migration file"):
        apply_context_lifecycle_outbox_schema("postgresql://unit", str(migration))


def test_explicit_migration_rejects_empty_file_before_database(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """An empty migration cannot become executable SQL authority."""
    _deny_database(monkeypatch)
    migration = tmp_path / "empty.sql"
    migration.write_bytes(b"")

    with pytest.raises(ConfigError, match="migration file"):
        apply_context_lifecycle_outbox_schema("postgresql://unit", str(migration))


@pytest.mark.skipif(not hasattr(os, "mkfifo"), reason="requires POSIX FIFO support")
def test_explicit_migration_rejects_fifo_without_blocking_for_writer(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A FIFO token must be opened nonblocking and rejected as non-regular authority."""
    _deny_database(monkeypatch)
    migration = tmp_path / "migration.sql"
    os.mkfifo(migration)

    with pytest.raises(ConfigError, match="migration file"):
        apply_context_lifecycle_outbox_schema("postgresql://unit", str(migration))


def test_explicit_migration_normalizes_initial_fstat_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Descriptor-inspection failure must stay inside the content-free error boundary."""
    _deny_database(monkeypatch)
    migration = tmp_path / "migration.sql"
    migration.write_text("SELECT 1;", encoding="utf-8")
    monkeypatch.setattr(lifecycle_outbox.os, "fstat", lambda _fd: (_ for _ in ()).throw(OSError("stat")))

    with pytest.raises(ConfigError, match="migration file"):
        apply_context_lifecycle_outbox_schema("postgresql://unit", str(migration))


def test_explicit_migration_normalizes_read_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Descriptor-read failure must stay inside the content-free error boundary."""
    _deny_database(monkeypatch)
    migration = tmp_path / "migration.sql"
    migration.write_text("SELECT 1;", encoding="utf-8")
    monkeypatch.setattr(lifecycle_outbox.os, "read", lambda _fd, _size: (_ for _ in ()).throw(OSError("read")))

    with pytest.raises(ConfigError, match="migration file"):
        apply_context_lifecycle_outbox_schema("postgresql://unit", str(migration))


def test_explicit_migration_rejects_short_descriptor_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A short read relative to retained size evidence must fail closed."""
    _deny_database(monkeypatch)
    migration = tmp_path / "migration.sql"
    migration.write_text("SELECT 1;", encoding="utf-8")
    reads = iter((b"SEL", b""))
    monkeypatch.setattr(lifecycle_outbox.os, "read", lambda _fd, _size: next(reads))

    with pytest.raises(ConfigError, match="migration file"):
        apply_context_lifecycle_outbox_schema("postgresql://unit", str(migration))


def test_explicit_migration_rejects_growth_past_byte_budget_during_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Concurrent growth cannot bypass the byte budget after initial metadata review."""
    _deny_database(monkeypatch)
    migration = tmp_path / "migration.sql"
    migration.write_bytes(b"S")
    original_read = lifecycle_outbox.os.read
    first_read = True

    def grow_then_read(descriptor: int, size: int) -> bytes:
        nonlocal first_read
        if first_read:
            first_read = False
            with migration.open("ab") as stream:
                stream.write(b"x" * (1024 * 1024))
        return original_read(descriptor, size)

    monkeypatch.setattr(lifecycle_outbox.os, "read", grow_then_read)

    with pytest.raises(ConfigError, match="migration file"):
        apply_context_lifecycle_outbox_schema("postgresql://unit", str(migration))


def test_explicit_migration_rejects_metadata_change_after_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Observed in-place mutation across the retained read cannot become SQL authority."""
    _deny_database(monkeypatch)
    migration = tmp_path / "migration.sql"
    migration.write_text("SELECT 1;", encoding="utf-8")
    original_fstat = lifecycle_outbox.os.fstat
    calls = 0

    def changed_second_fstat(descriptor: int):
        nonlocal calls
        calls += 1
        status = original_fstat(descriptor)
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

    monkeypatch.setattr(lifecycle_outbox.os, "fstat", changed_second_fstat)

    with pytest.raises(ConfigError, match="migration file"):
        apply_context_lifecycle_outbox_schema("postgresql://unit", str(migration))


def test_explicit_migration_normalizes_final_fstat_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Final descriptor-inspection failure cannot expose host diagnostics."""
    _deny_database(monkeypatch)
    migration = tmp_path / "migration.sql"
    migration.write_text("SELECT 1;", encoding="utf-8")
    original_fstat = lifecycle_outbox.os.fstat
    calls = 0

    def fail_second_fstat(descriptor: int):
        nonlocal calls
        calls += 1
        if calls == 1:
            return original_fstat(descriptor)
        raise OSError("final-stat")

    monkeypatch.setattr(lifecycle_outbox.os, "fstat", fail_second_fstat)

    with pytest.raises(ConfigError, match="migration file"):
        apply_context_lifecycle_outbox_schema("postgresql://unit", str(migration))


def test_explicit_migration_normalizes_close_failure_after_valid_read(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Failure to release retained file authority must fail before database access."""
    _deny_database(monkeypatch)
    migration = tmp_path / "migration.sql"
    migration.write_text("SELECT 1;", encoding="utf-8")
    original_close = lifecycle_outbox.os.close

    def close_then_fail(descriptor: int) -> None:
        original_close(descriptor)
        raise OSError("close")

    monkeypatch.setattr(lifecycle_outbox.os, "close", close_then_fail)

    with pytest.raises(ConfigError, match="migration file"):
        apply_context_lifecycle_outbox_schema("postgresql://unit", str(migration))


def test_primary_migration_error_survives_secondary_close_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Cleanup failure must not replace the already-established migration rejection."""
    _deny_database(monkeypatch)
    migration = tmp_path / "oversized.sql"
    migration.write_bytes(b"x" * (1024 * 1024 + 1))
    original_close = lifecycle_outbox.os.close

    def close_then_fail(descriptor: int) -> None:
        original_close(descriptor)
        raise OSError("close")

    monkeypatch.setattr(lifecycle_outbox.os, "close", close_then_fail)

    with pytest.raises(ConfigError, match="migration file"):
        apply_context_lifecycle_outbox_schema("postgresql://unit", str(migration))
