# SPDX-License-Identifier: Apache-2.0
"""Behavior contracts for bounded stable checkpoint-audit export pages."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

import pytest

import pg_llm_batch.checkpoint_audit as checkpoint_audit
from pg_llm_batch.checkpoint_audit import (
    MAX_CHECKPOINT_AUDIT_EVENT_ID,
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

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Capture one normalized SQL statement and its parameters."""
        self.calls.append((" ".join(sql.split()), params or ()))

    def fetchall(self) -> Any:
        """Return the configured database rows."""
        return self.rows


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
    assert params == ("tenant-a", "worker-a", "default", "batch-1", 8, 3)


def test_export_page_fails_closed_on_impossible_driver_overrun(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A driver returning more rows than the SQL bound cannot expand page memory silently."""
    cursor = FakeCursor(rows=(_row(9), _row(8), _row(7), _row(6)))
    monkeypatch.setattr(checkpoint_audit, "_set_transaction_tenant_scope", lambda *_: None)
    store = checkpoint_audit.AuditedPostgresBatchResultCheckpointStore("postgresql://unit")

    with pytest.raises(RuntimeError, match="exceeded its bounded query size"):
        store.list_audit_event_page_in_transaction(
            cursor,
            "worker-a",
            "batch-1",
            "default",
            limit=2,
        )
