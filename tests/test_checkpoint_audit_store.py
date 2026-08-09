# SPDX-License-Identifier: Apache-2.0
"""Behavior tests for accepted-save checkpoint audit persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

import pg_llm_batch.checkpoint_audit as checkpoint_audit
from pg_llm_batch.checkpoint_audit import (
    AUDIT_ACTION_CHECKPOINT_SAVE_ACCEPTED,
    AuditedPostgresBatchResultCheckpointStore,
    CheckpointAuditEvent,
    _audit_event_from_row,
    apply_result_checkpoint_audit_schema,
)
from pg_llm_batch.checkpoint_store import (
    CheckpointConflictError,
    PostgresBatchResultCheckpointStore,
)
from pg_llm_batch.result_streaming import BatchResultCheckpoint


def checkpoint() -> BatchResultCheckpoint:
    """Build one valid checkpoint for audit-store behavior tests."""
    return BatchResultCheckpoint(
        schema_version=1,
        batch_id="batch-1",
        endpoint_alias="default",
        file_kind="result",
        file_id="file-1",
        file_line_number=2,
        batch_line_count=2,
        record_count=1,
        prefix_sha256="a" * 64,
    )


def audit_row(*, tenant: str = "tenant-a") -> tuple[Any, ...]:
    """Build one valid database-shaped accepted-save audit row."""
    return (
        7,
        tenant,
        "worker-a",
        "default",
        "batch-1",
        AUDIT_ACTION_CHECKPOINT_SAVE_ACCEPTED,
        1,
        "result",
        "file-1",
        2,
        2,
        1,
        "a" * 64,
        datetime(2026, 8, 7, tzinfo=timezone.utc),
    )


class FakeCursor:
    """Capture SQL and expose deterministic row collections."""

    def __init__(self, rows: Any = ()) -> None:
        self.rows = rows
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def __enter__(self) -> "FakeCursor":
        """Enter the fake cursor context."""
        return self

    def __exit__(self, *_exc: Any) -> None:
        """Exit the fake cursor context."""
        return None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Capture one normalized SQL statement and its parameters."""
        self.calls.append((" ".join(sql.split()), params or ()))

    def fetchall(self) -> Any:
        """Return the configured row collection."""
        return self.rows


class FakeConnection:
    """Expose one cursor and count explicit commits."""

    def __init__(self, cursor: FakeCursor) -> None:
        self.fake_cursor = cursor
        self.commits = 0

    def __enter__(self) -> "FakeConnection":
        """Enter the fake connection context."""
        return self

    def __exit__(self, *_exc: Any) -> None:
        """Exit the fake connection context."""
        return None

    def cursor(self) -> FakeCursor:
        """Return the deterministic fake cursor."""
        return self.fake_cursor

    def commit(self) -> None:
        """Record one package-owned transaction commit."""
        self.commits += 1


class FakePsycopg:
    """Return one deterministic connection and record DSNs."""

    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.dsns: list[str] = []

    def connect(self, dsn: str) -> FakeConnection:
        """Record the DSN and return the configured connection."""
        self.dsns.append(dsn)
        return self.connection


def test_event_rejects_invalid_identity_action_and_timestamp() -> None:
    """Malformed database evidence fails closed before becoming public state."""
    valid = list(audit_row())
    for event_id in (True, 0, -1, "7"):
        candidate = valid.copy()
        candidate[0] = event_id
        with pytest.raises(ValueError):
            _audit_event_from_row(candidate)
    candidate = valid.copy()
    candidate[5] = "checkpoint_changed"
    with pytest.raises(ValueError, match="unsupported"):
        _audit_event_from_row(candidate)
    for timestamp in ("2026-08-07", datetime(2026, 8, 7)):
        candidate = valid.copy()
        candidate[13] = timestamp
        with pytest.raises(ValueError, match="timezone-aware"):
            _audit_event_from_row(candidate)


def test_event_row_shape_and_checkpoint_fields_are_revalidated() -> None:
    """Unexpected row containers, shapes, tenants, and checkpoint values fail closed."""
    for row in (None, object(), (1, 2), [1, 2]):
        with pytest.raises(RuntimeError, match="invalid shape"):
            _audit_event_from_row(row)
    candidate = list(audit_row())
    candidate[1] = " bad"
    with pytest.raises(Exception):
        _audit_event_from_row(candidate)
    candidate = list(audit_row())
    candidate[12] = "not-a-digest"
    with pytest.raises(Exception):
        _audit_event_from_row(candidate)


def test_apply_schema_uses_default_and_explicit_migration_paths(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Schema application reads one selected script and commits exactly once."""
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    fake_psycopg = FakePsycopg(connection)
    monkeypatch.setattr(checkpoint_audit, "psycopg", fake_psycopg)
    monkeypatch.setattr(checkpoint_audit, "_require_psycopg", lambda: None)

    apply_result_checkpoint_audit_schema("postgresql://unit")
    assert cursor.calls[-1][0].startswith("-- SPDX-License-Identifier")
    assert connection.commits == 1

    custom = tmp_path / "audit.sql"
    custom.write_text("SELECT 42;", encoding="utf-8")
    apply_result_checkpoint_audit_schema(
        "postgresql://unit",
        migration_path=str(custom),
    )
    assert cursor.calls[-1] == ("SELECT 42;", ())
    assert connection.commits == 2
    assert fake_psycopg.dsns == ["postgresql://unit", "postgresql://unit"]


def test_save_in_transaction_appends_one_event_after_accepted_save(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A successful delegated save appends exact accepted checkpoint evidence."""
    saved = checkpoint()
    delegated: list[tuple[Any, ...]] = []

    def fake_save(
        self: PostgresBatchResultCheckpointStore,
        cursor: Any,
        consumer_name: str,
        candidate: BatchResultCheckpoint,
        *,
        expected_previous: BatchResultCheckpoint | None = None,
    ) -> BatchResultCheckpoint:
        """Capture one superclass save call and return its checkpoint unchanged."""
        delegated.append((self, cursor, consumer_name, candidate, expected_previous))
        return candidate

    monkeypatch.setattr(PostgresBatchResultCheckpointStore, "save_in_transaction", fake_save)
    cursor = FakeCursor()
    store = AuditedPostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )

    assert store.save_in_transaction(cursor, "worker-a", saved) is saved
    assert delegated[0][2:] == ("worker-a", saved, None)
    insert = cursor.calls[-1]
    assert insert[0].startswith("INSERT INTO llm_result_checkpoint_audit_events")
    assert insert[1] == (
        "tenant-a",
        "worker-a",
        "default",
        "batch-1",
        AUDIT_ACTION_CHECKPOINT_SAVE_ACCEPTED,
        1,
        "result",
        "file-1",
        2,
        2,
        1,
        "a" * 64,
    )


def test_rejected_save_does_not_append_audit_event(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Logical checkpoint conflicts remain authoritative and create no success evidence."""

    def fake_conflict(*_args: Any, **_kwargs: Any) -> BatchResultCheckpoint:
        """Raise the same bounded conflict exposed by the durable store."""
        raise CheckpointConflictError("worker-a", "batch-1", "expected_previous_stale")

    monkeypatch.setattr(
        PostgresBatchResultCheckpointStore,
        "save_in_transaction",
        fake_conflict,
    )
    cursor = FakeCursor()
    store = AuditedPostgresBatchResultCheckpointStore("postgresql://unit")
    with pytest.raises(CheckpointConflictError):
        store.save_in_transaction(cursor, "worker-a", checkpoint())
    assert cursor.calls == []


def test_owned_save_commits_checkpoint_and_audit_together(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Package-owned save commits only after the accepted-save event is appended."""
    cursor = FakeCursor()
    connection = FakeConnection(cursor)
    fake_psycopg = FakePsycopg(connection)
    monkeypatch.setattr(checkpoint_audit, "psycopg", fake_psycopg)
    monkeypatch.setattr(checkpoint_audit, "_require_psycopg", lambda: None)
    monkeypatch.setattr(
        PostgresBatchResultCheckpointStore,
        "save_in_transaction",
        lambda _self, _cursor, _consumer, candidate, **_kwargs: candidate,
    )
    store = AuditedPostgresBatchResultCheckpointStore("postgresql://unit")

    saved = checkpoint()
    assert store.save("worker-a", saved) is saved
    assert connection.commits == 1
    assert fake_psycopg.dsns == ["postgresql://unit"]
    assert cursor.calls[-1][0].startswith("INSERT INTO llm_result_checkpoint_audit_events")


def test_list_in_transaction_is_tenant_qualified_bounded_and_newest_first(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit reads bind trusted tenancy and one fixed compound checkpoint key."""
    cursor = FakeCursor(rows=(audit_row(),))
    scopes: list[str] = []
    monkeypatch.setattr(
        checkpoint_audit,
        "_set_transaction_tenant_scope",
        lambda _cursor, tenant: scopes.append(tenant),
    )
    store = AuditedPostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )

    events = store.list_audit_events_in_transaction(
        cursor,
        "worker-a",
        "batch-1",
        "default",
        limit=7,
    )
    assert len(events) == 1
    assert isinstance(events[0], CheckpointAuditEvent)
    assert scopes == ["tenant-a"]
    query, params = cursor.calls[-1]
    assert "ORDER BY checkpoint_audit_event_id DESC LIMIT %s" in query
    assert params == ("tenant-a", "worker-a", "default", "batch-1", 7)


def test_list_rejects_rows_outside_the_requested_compound_key(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Database or adapter corruption must not expose evidence for another key."""
    monkeypatch.setattr(checkpoint_audit, "_set_transaction_tenant_scope", lambda *_: None)
    store = AuditedPostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )

    for index, wrong_value in (
        (1, "tenant-b"),
        (2, "worker-b"),
        (3, "secondary"),
        (4, "batch-2"),
    ):
        row = list(audit_row())
        row[index] = wrong_value
        cursor = FakeCursor(rows=(tuple(row),))
        with pytest.raises(RuntimeError, match="outside the requested key"):
            store.list_audit_events_in_transaction(
                cursor,
                "worker-a",
                "batch-1",
                "default",
            )


def test_owned_list_uses_connection_without_committing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Package-owned audit reads do not create an application commit boundary."""
    cursor = FakeCursor(rows=[audit_row()])
    connection = FakeConnection(cursor)
    fake_psycopg = FakePsycopg(connection)
    monkeypatch.setattr(checkpoint_audit, "psycopg", fake_psycopg)
    monkeypatch.setattr(checkpoint_audit, "_require_psycopg", lambda: None)
    monkeypatch.setattr(checkpoint_audit, "_set_transaction_tenant_scope", lambda *_: None)
    store = AuditedPostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )

    events = store.list_audit_events("worker-a", "batch-1", "default")
    assert events[0].audit_event_id == 7
    assert connection.commits == 0
    assert fake_psycopg.dsns == ["postgresql://unit"]


def test_list_rejects_invalid_database_row_collection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A non-sequence fetch result cannot masquerade as bounded audit evidence."""
    cursor = FakeCursor(rows=object())
    monkeypatch.setattr(checkpoint_audit, "_set_transaction_tenant_scope", lambda *_: None)
    store = AuditedPostgresBatchResultCheckpointStore("postgresql://unit")
    with pytest.raises(RuntimeError, match="invalid row collection"):
        store.list_audit_events_in_transaction(
            cursor,
            "worker-a",
            "batch-1",
            "default",
        )
