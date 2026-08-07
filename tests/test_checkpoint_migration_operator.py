# SPDX-License-Identifier: Apache-2.0
"""Contracts for the atomic checkpoint-storage migration operator."""

from __future__ import annotations

from hashlib import sha256
from pathlib import Path

import pytest

from pg_llm_batch import (
    CheckpointSchemaMigration,
    apply_checkpoint_schema_migrations,
    plan_checkpoint_schema_migrations,
)
from pg_llm_batch import checkpoint_migrations
from pg_llm_batch.checkpoint_audit import AUDIT_MIGRATION_PATH
from pg_llm_batch.checkpoint_store import MIGRATION_PATH


class _RecordingCursor:
    """Record SQL calls and optionally fail on one exact migration body."""

    def __init__(self, fail_sql: str | None = None) -> None:
        self.fail_sql = fail_sql
        self.executions: list[tuple[str, object | None]] = []

    def __enter__(self) -> _RecordingCursor:
        """Return this cursor for context-managed production use."""
        return self

    def __exit__(self, *_exc: object) -> None:
        """Leave cursor cleanup to the deterministic fake."""
        return None

    def execute(self, statement: str, parameters: object | None = None) -> None:
        """Record one SQL call and raise for the configured migration body."""
        self.executions.append((statement, parameters))
        if statement == self.fail_sql:
            raise RuntimeError("database migration failed")


class _RecordingConnection:
    """Record transaction ownership without implementing PostgreSQL behavior."""

    def __init__(self, cursor: _RecordingCursor) -> None:
        self.recording_cursor = cursor
        self.commit_calls = 0
        self.exit_exception_type: type[BaseException] | None = None

    def __enter__(self) -> _RecordingConnection:
        """Return this connection for context-managed production use."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        _exc: BaseException | None,
        _traceback: object | None,
    ) -> None:
        """Remember whether the transaction left through an exception."""
        self.exit_exception_type = exc_type
        return None

    def cursor(self) -> _RecordingCursor:
        """Return the one deterministic recording cursor."""
        return self.recording_cursor

    def commit(self) -> None:
        """Count one explicit production commit."""
        self.commit_calls += 1


class _RecordingPsycopg:
    """Expose one deterministic connection through the psycopg seam."""

    def __init__(self, connection: _RecordingConnection) -> None:
        self.connection = connection
        self.connect_calls: list[str] = []

    def connect(self, postgres_dsn: str) -> _RecordingConnection:
        """Record the DSN only inside the test fake and return its connection."""
        self.connect_calls.append(postgres_dsn)
        return self.connection


def _write_migration(path: Path, sql: bytes) -> tuple[str, Path]:
    """Write one private test migration and return its reviewed tuple entry."""
    path.write_bytes(sql)
    return (path.stem, path)


def test_plan_uses_canonical_order_sizes_and_digests() -> None:
    """Planning identifies the exact package SQL bytes in dependency order."""
    plan = plan_checkpoint_schema_migrations()
    assert tuple(item.migration_id for item in plan) == (
        "0007_result_stream_checkpoints",
        "0008_result_checkpoint_audit_events",
    )
    assert all(isinstance(item, CheckpointSchemaMigration) for item in plan)
    assert tuple(item.byte_count for item in plan) == (
        len(MIGRATION_PATH.read_bytes()),
        len(AUDIT_MIGRATION_PATH.read_bytes()),
    )
    assert tuple(item.sha256 for item in plan) == (
        sha256(MIGRATION_PATH.read_bytes()).hexdigest(),
        sha256(AUDIT_MIGRATION_PATH.read_bytes()).hexdigest(),
    )


def test_migration_descriptor_is_immutable_and_json_safe() -> None:
    """Public evidence is immutable and contains only bounded scalar fields."""
    descriptor = CheckpointSchemaMigration(
        migration_id="0007_result_stream_checkpoints",
        byte_count=42,
        sha256="a" * 64,
    )
    assert descriptor.as_dict() == {
        "migration_id": "0007_result_stream_checkpoints",
        "byte_count": 42,
        "sha256": "a" * 64,
    }
    with pytest.raises(Exception):
        descriptor.byte_count = 43  # type: ignore[misc]


@pytest.mark.parametrize(
    ("migration_id", "byte_count", "digest"),
    (
        ("unexpected_migration", 1, "a" * 64),
        ("0007_result_stream_checkpoints", True, "a" * 64),
        ("0007_result_stream_checkpoints", 0, "a" * 64),
        (
            "0007_result_stream_checkpoints",
            checkpoint_migrations.MAX_CHECKPOINT_SCHEMA_MIGRATION_BYTES + 1,
            "a" * 64,
        ),
        ("0007_result_stream_checkpoints", 1, "A" * 64),
        ("0007_result_stream_checkpoints", 1, "g" * 64),
        ("0007_result_stream_checkpoints", 1, "a" * 63),
    ),
)
def test_migration_descriptor_rejects_unbounded_or_ambiguous_values(
    migration_id: object,
    byte_count: object,
    digest: object,
) -> None:
    """Descriptor construction is strict, non-coercive, and closed to new IDs."""
    with pytest.raises(ValueError):
        CheckpointSchemaMigration(
            migration_id=migration_id,  # type: ignore[arg-type]
            byte_count=byte_count,  # type: ignore[arg-type]
            sha256=digest,  # type: ignore[arg-type]
        )


@pytest.mark.parametrize(
    "payload",
    (
        b"",
        b"x" * (1_048_576 + 1),
        b"\xff",
    ),
)
def test_plan_rejects_empty_oversized_or_non_utf8_migrations(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    payload: bytes,
) -> None:
    """Every migration is bounded and decoded before any database operation."""
    first = _write_migration(tmp_path / "first.sql", b"SELECT 1;")
    second = _write_migration(tmp_path / "second.sql", payload)
    monkeypatch.setattr(
        checkpoint_migrations,
        "_CHECKPOINT_SCHEMA_MIGRATION_PATHS",
        (first, second),
    )
    with pytest.raises((RuntimeError, UnicodeDecodeError)):
        plan_checkpoint_schema_migrations()


def test_apply_loads_every_file_before_psycopg_or_database_access(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A missing second migration cannot leave the first migration committed."""
    first = _write_migration(tmp_path / "first.sql", b"SELECT 1;")
    missing = ("second", tmp_path / "missing.sql")
    monkeypatch.setattr(
        checkpoint_migrations,
        "_CHECKPOINT_SCHEMA_MIGRATION_PATHS",
        (first, missing),
    )
    require_calls: list[str] = []
    connect_calls: list[str] = []
    monkeypatch.setattr(
        checkpoint_migrations,
        "_require_psycopg",
        lambda: require_calls.append("required"),
    )
    monkeypatch.setattr(
        checkpoint_migrations,
        "psycopg",
        type(
            "ForbiddenPsycopg",
            (),
            {"connect": staticmethod(lambda dsn: connect_calls.append(dsn))},
        )(),
    )

    with pytest.raises(OSError):
        apply_checkpoint_schema_migrations("postgresql://secret@database")

    assert require_calls == []
    assert connect_calls == []


def test_apply_uses_one_lock_exact_order_and_one_commit(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """One owned transaction serializes and commits both migrations together."""
    first_sql = "SELECT 'first';"
    second_sql = "SELECT 'second';"
    monkeypatch.setattr(
        checkpoint_migrations,
        "_CHECKPOINT_SCHEMA_MIGRATION_PATHS",
        (
            _write_migration(tmp_path / "first.sql", first_sql.encode()),
            _write_migration(tmp_path / "second.sql", second_sql.encode()),
        ),
    )
    cursor = _RecordingCursor()
    connection = _RecordingConnection(cursor)
    provider = _RecordingPsycopg(connection)
    require_calls: list[str] = []
    monkeypatch.setattr(checkpoint_migrations, "psycopg", provider)
    monkeypatch.setattr(
        checkpoint_migrations,
        "_require_psycopg",
        lambda: require_calls.append("required"),
    )

    applied = apply_checkpoint_schema_migrations("postgresql://operator")

    assert require_calls == ["required"]
    assert provider.connect_calls == ["postgresql://operator"]
    assert cursor.executions == [
        (
            "SELECT pg_advisory_xact_lock(%s, %s)",
            (
                checkpoint_migrations.CHECKPOINT_SCHEMA_MIGRATION_LOCK_NAMESPACE,
                checkpoint_migrations.CHECKPOINT_SCHEMA_MIGRATION_LOCK_OPERATION,
            ),
        ),
        (first_sql, None),
        (second_sql, None),
    ]
    assert connection.commit_calls == 1
    assert connection.exit_exception_type is None
    assert tuple(item.migration_id for item in applied) == ("first", "second")


def test_apply_propagates_second_failure_without_commit_or_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A second-statement failure exits the owned transaction before commit."""
    first_sql = "SELECT 'first';"
    second_sql = "SELECT 'second';"
    monkeypatch.setattr(
        checkpoint_migrations,
        "_CHECKPOINT_SCHEMA_MIGRATION_PATHS",
        (
            _write_migration(tmp_path / "first.sql", first_sql.encode()),
            _write_migration(tmp_path / "second.sql", second_sql.encode()),
        ),
    )
    cursor = _RecordingCursor(fail_sql=second_sql)
    connection = _RecordingConnection(cursor)
    monkeypatch.setattr(
        checkpoint_migrations,
        "psycopg",
        _RecordingPsycopg(connection),
    )
    monkeypatch.setattr(checkpoint_migrations, "_require_psycopg", lambda: None)

    with pytest.raises(RuntimeError, match="database migration failed"):
        apply_checkpoint_schema_migrations("postgresql://operator")

    assert cursor.executions[-2:] == [(first_sql, None), (second_sql, None)]
    assert connection.commit_calls == 0
    assert connection.exit_exception_type is RuntimeError
