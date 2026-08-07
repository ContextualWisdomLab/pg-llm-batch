# SPDX-License-Identifier: Apache-2.0
"""Behavior contracts for bounded stable checkpoint-audit export pages."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

import pg_llm_batch.checkpoint_audit as checkpoint_audit
from pg_llm_batch.checkpoint_audit import (
    MAX_CHECKPOINT_AUDIT_EVENT_ID,
    MAX_CHECKPOINT_AUDIT_EVENTS,
    CheckpointAuditEvent,
    CheckpointAuditPage,
    validate_checkpoint_audit_cursor,
)
from pg_llm_batch.exceptions import ValidationError


def _event(event_id: int) -> CheckpointAuditEvent:
    """Build one valid audit event with a selectable monotonically increasing identity."""
    return CheckpointAuditEvent(
        audit_event_id=event_id,
        tenant_scope="tenant-a",
        consumer_name="worker-a",
        endpoint_alias="default",
        batch_id="batch-1",
        action="checkpoint_save_accepted",
        schema_version=1,
        file_kind="result",
        file_id="file-1",
        file_line_number=event_id,
        batch_line_count=event_id,
        record_count=event_id,
        prefix_sha256=f"{event_id:064x}",
        recorded_at=datetime(2026, 8, 7, event_id % 24, tzinfo=timezone.utc),
    )


def _row(event_id: int) -> tuple[Any, ...]:
    """Return one database-shaped row matching :func:`_event`."""
    event = _event(event_id)
    return (
        event.audit_event_id,
        event.tenant_scope,
        event.consumer_name,
        event.endpoint_alias,
        event.batch_id,
        event.action,
        event.schema_version,
        event.file_kind,
        event.file_id,
        event.file_line_number,
        event.batch_line_count,
        event.record_count,
        event.prefix_sha256,
        event.recorded_at,
    )


class FakeCursor:
    """Capture audit-page SQL and return deterministic rows."""

    def __init__(self, rows: Any) -> None:
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
        """Return the configured database rows."""
        return self.rows


class FakeConnection:
    """Expose one cursor without inventing a commit boundary for audit reads."""

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
        """Record an unexpected explicit package commit if production attempts one."""
        self.commits += 1


class FakePsycopg:
    """Return one deterministic connection and record requested DSNs."""

    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection
        self.dsns: list[str] = []

    def connect(self, dsn: str) -> FakeConnection:
        """Record one DSN and return the configured connection."""
        self.dsns.append(dsn)
        return self.connection


def test_audit_cursor_is_strict_positive_postgres_bigint_or_none() -> None:
    """Export cursors reject coercion and values PostgreSQL cannot represent."""
    assert validate_checkpoint_audit_cursor(None) is None
    assert validate_checkpoint_audit_cursor(1) == 1
    assert (
        validate_checkpoint_audit_cursor(MAX_CHECKPOINT_AUDIT_EVENT_ID)
        == 9_223_372_036_854_775_807
    )
    for value in (True, 0, -1, 9_223_372_036_854_775_808, 1.0, "7", object()):
        with pytest.raises(ValidationError):
            validate_checkpoint_audit_cursor(value)


def test_audit_page_is_immutable_descending_and_cursor_bound() -> None:
    """A public page cannot advertise an invalid continuation boundary."""
    first = _event(9)
    second = _event(8)
    page = CheckpointAuditPage(events=(first, second), next_before_audit_event_id=8)
    assert page.events == (first, second)
    assert page.next_before_audit_event_id == 8

    invalid_pages = (
        ((second, first), None),
        ((first, first), None),
        ((first, second), 7),
        ((), 1),
    )
    for events, cursor in invalid_pages:
        with pytest.raises(ValueError):
            CheckpointAuditPage(events=events, next_before_audit_event_id=cursor)


def test_audit_page_rejects_mutable_wrong_type_and_oversized_event_collections() -> None:
    """Direct page construction cannot bypass tuple, type, or public-size contracts."""
    with pytest.raises(ValueError, match="tuple"):
        CheckpointAuditPage(events=[_event(1)], next_before_audit_event_id=None)  # type: ignore[arg-type]
    with pytest.raises(ValueError, match="CheckpointAuditEvent"):
        CheckpointAuditPage(events=(object(),), next_before_audit_event_id=None)  # type: ignore[arg-type]
    oversized = tuple(_event(index + 1) for index in range(MAX_CHECKPOINT_AUDIT_EVENTS + 1))
    with pytest.raises(ValueError, match="at most"):
        CheckpointAuditPage(events=oversized, next_before_audit_event_id=None)


def test_first_export_page_uses_one_bounded_lookahead_row(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A first page returns at most the requested rows and one stable next cursor."""
    cursor = FakeCursor(rows=(_row(9), _row(8), _row(7)))
    scopes: list[str] = []
    monkeypatch.setattr(
        checkpoint_audit,
        "_set_transaction_tenant_scope",
        lambda _cursor, tenant: scopes.append(tenant),
    )
    store = checkpoint_audit.AuditedPostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )

    page = store.list_audit_event_page_in_transaction(
        cursor,
        "worker-a",
        "batch-1",
        "default",
        limit=2,
    )

    assert tuple(event.audit_event_id for event in page.events) == (9, 8)
    assert page.next_before_audit_event_id == 8
    assert scopes == ["tenant-a"]
    query, params = cursor.calls[-1]
    assert "checkpoint_audit_event_id < %s" not in query
    assert "ORDER BY checkpoint_audit_event_id DESC LIMIT %s" in query
    assert "OFFSET" not in query
    assert params == ("tenant-a", "worker-a", "default", "batch-1", 3)


def test_next_export_page_is_keyset_bound_and_ignores_newer_concurrent_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A continuation cursor advances toward older rows without OFFSET drift."""
    cursor = FakeCursor(rows=(_row(7), _row(6)))
    monkeypatch.setattr(checkpoint_audit, "_set_transaction_tenant_scope", lambda *_: None)
    store = checkpoint_audit.AuditedPostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )

    page = store.list_audit_event_page_in_transaction(
        cursor,
        "worker-a",
        "batch-1",
        "default",
        before_audit_event_id=8,
        limit=2,
    )

    assert tuple(event.audit_event_id for event in page.events) == (7, 6)
    assert page.next_before_audit_event_id is None
    query, params = cursor.calls[-1]
    assert "checkpoint_audit_event_id < %s" in query
    assert "OFFSET" not in query
    assert params == ("tenant-a", "worker-a", "default", "batch-1", 8, 3)


def test_continuation_page_revalidates_returned_identity_against_cursor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A faulty adapter cannot return an event at or newer than the strict cursor."""
    monkeypatch.setattr(checkpoint_audit, "_set_transaction_tenant_scope", lambda *_: None)
    store = checkpoint_audit.AuditedPostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )

    with pytest.raises(RuntimeError, match="violated the continuation cursor"):
        store.list_audit_event_page_in_transaction(
            FakeCursor(rows=(_row(8), _row(7))),
            "worker-a",
            "batch-1",
            "default",
            before_audit_event_id=8,
            limit=2,
        )


def test_export_page_revalidates_database_key_and_descending_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Corrupt or cross-key database rows cannot become trusted export evidence."""
    monkeypatch.setattr(checkpoint_audit, "_set_transaction_tenant_scope", lambda *_: None)
    store = checkpoint_audit.AuditedPostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )

    wrong_key = list(_row(9))
    wrong_key[1] = "tenant-b"
    with pytest.raises(RuntimeError, match="outside the requested key"):
        store.list_audit_event_page_in_transaction(
            FakeCursor(rows=(tuple(wrong_key),)),
            "worker-a",
            "batch-1",
            "default",
        )

    with pytest.raises(RuntimeError, match="strictly descending"):
        store.list_audit_event_page_in_transaction(
            FakeCursor(rows=(_row(8), _row(9))),
            "worker-a",
            "batch-1",
            "default",
        )


def test_export_page_fails_closed_on_invalid_collection_or_driver_overrun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected driver output cannot bypass bounded export pagination."""
    monkeypatch.setattr(checkpoint_audit, "_set_transaction_tenant_scope", lambda *_: None)
    store = checkpoint_audit.AuditedPostgresBatchResultCheckpointStore("postgresql://unit")

    with pytest.raises(RuntimeError, match="invalid row collection"):
        store.list_audit_event_page_in_transaction(
            FakeCursor(rows=object()),
            "worker-a",
            "batch-1",
            "default",
            limit=2,
        )

    with pytest.raises(RuntimeError, match="exceeded its bounded query size"):
        store.list_audit_event_page_in_transaction(
            FakeCursor(rows=(_row(9), _row(8), _row(7), _row(6))),
            "worker-a",
            "batch-1",
            "default",
            limit=2,
        )


def test_owned_export_page_uses_one_connection_without_explicit_commit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The package-owned read delegates through one connection without calling commit()."""
    cursor = FakeCursor(rows=(_row(3),))
    connection = FakeConnection(cursor)
    fake_psycopg = FakePsycopg(connection)
    monkeypatch.setattr(checkpoint_audit, "psycopg", fake_psycopg)
    monkeypatch.setattr(checkpoint_audit, "_require_psycopg", lambda: None)
    monkeypatch.setattr(checkpoint_audit, "_set_transaction_tenant_scope", lambda *_: None)
    store = checkpoint_audit.AuditedPostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )

    page = store.list_audit_event_page(
        "worker-a",
        "batch-1",
        "default",
        before_audit_event_id=4,
        limit=2,
    )

    assert tuple(event.audit_event_id for event in page.events) == (3,)
    assert page.next_before_audit_event_id is None
    assert fake_psycopg.dsns == ["postgresql://unit"]
    assert connection.commits == 0
