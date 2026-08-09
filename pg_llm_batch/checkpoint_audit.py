# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Append-only tenant-isolated audit evidence for accepted checkpoint saves."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

from .checkpoint_store import (
    PostgresBatchResultCheckpointStore,
    _validated_batch_id,
    _validated_exact_endpoint_alias,
    validate_checkpoint_consumer_name,
)
from .db import _require_psycopg, _set_transaction_tenant_scope, psycopg, validate_tenant_scope
from .exceptions import ValidationError
from .result_streaming import BatchResultCheckpoint

AUDIT_ACTION_CHECKPOINT_SAVE_ACCEPTED = "checkpoint_save_accepted"
MAX_CHECKPOINT_AUDIT_EVENTS = 1000
DEFAULT_CHECKPOINT_AUDIT_EVENTS = 100
MAX_CHECKPOINT_AUDIT_EVENT_ID = 9_223_372_036_854_775_807
AUDIT_MIGRATION_PATH = (
    Path(__file__).with_name("migrations") / "0008_result_checkpoint_audit_events.sql"
)
_AUDIT_COLUMNS = (
    "checkpoint_audit_event_id, tenant_scope, checkpoint_consumer_name, "
    "endpoint_alias, remote_batch_id, event_action, schema_version, file_kind, "
    "file_id, file_line_number, batch_line_count, record_count, prefix_sha256, "
    "recorded_at"
)


@dataclass(frozen=True, slots=True)
class CheckpointAuditEvent:
    """One immutable accepted-save audit record returned from PostgreSQL."""

    audit_event_id: int
    tenant_scope: str
    consumer_name: str
    endpoint_alias: str
    batch_id: str
    action: str
    schema_version: int
    file_kind: str
    file_id: str
    file_line_number: int
    batch_line_count: int
    record_count: int
    prefix_sha256: str
    recorded_at: datetime

    def __post_init__(self) -> None:
        """Reject malformed public event values rather than exposing corrupt rows."""
        if (
            isinstance(self.audit_event_id, bool)
            or not isinstance(self.audit_event_id, int)
            or self.audit_event_id <= 0
            or self.audit_event_id > MAX_CHECKPOINT_AUDIT_EVENT_ID
        ):
            raise ValueError(
                "audit_event_id must be a positive PostgreSQL BIGINT-compatible integer"
            )
        validate_tenant_scope(self.tenant_scope)
        validate_checkpoint_consumer_name(self.consumer_name)
        _validated_exact_endpoint_alias(self.endpoint_alias)
        _validated_batch_id(self.batch_id)
        if self.action != AUDIT_ACTION_CHECKPOINT_SAVE_ACCEPTED:
            raise ValueError("unsupported checkpoint audit action")
        BatchResultCheckpoint(
            schema_version=self.schema_version,
            batch_id=self.batch_id,
            endpoint_alias=self.endpoint_alias,
            file_kind=self.file_kind,
            file_id=self.file_id,
            file_line_number=self.file_line_number,
            batch_line_count=self.batch_line_count,
            record_count=self.record_count,
            prefix_sha256=self.prefix_sha256,
        )
        if not isinstance(self.recorded_at, datetime) or self.recorded_at.tzinfo is None:
            raise ValueError("recorded_at must be a timezone-aware datetime")


@dataclass(frozen=True, slots=True)
class CheckpointAuditPage:
    """One immutable newest-first bounded audit page and its older-row cursor."""

    events: tuple[CheckpointAuditEvent, ...]
    next_before_audit_event_id: Optional[int]

    def __post_init__(self) -> None:
        """Reject mutable, oversized, unordered, or cursor-inconsistent pages."""
        if not isinstance(self.events, tuple):
            raise ValueError("events must be an immutable tuple")
        if len(self.events) > MAX_CHECKPOINT_AUDIT_EVENTS:
            raise ValueError(
                f"events must contain at most {MAX_CHECKPOINT_AUDIT_EVENTS} records"
            )
        if any(not isinstance(event, CheckpointAuditEvent) for event in self.events):
            raise ValueError("events must contain only CheckpointAuditEvent values")
        if any(
            current.audit_event_id >= previous.audit_event_id
            for previous, current in zip(self.events, self.events[1:])
        ):
            raise ValueError("events must be strictly descending by audit_event_id")
        cursor = validate_checkpoint_audit_cursor(self.next_before_audit_event_id)
        if cursor is not None and (
            not self.events or cursor != self.events[-1].audit_event_id
        ):
            raise ValueError("next_before_audit_event_id must equal the final event id")


def validate_checkpoint_audit_limit(value: Any) -> int:
    """Validate the bounded number of audit rows one public read may return."""
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > MAX_CHECKPOINT_AUDIT_EVENTS
    ):
        raise ValidationError(
            field="limit",
            value=value,
            reason=f"must be an integer from 1 through {MAX_CHECKPOINT_AUDIT_EVENTS}",
        )
    return value


def validate_checkpoint_audit_cursor(value: Any) -> Optional[int]:
    """Validate an optional positive PostgreSQL BIGINT audit-event keyset cursor."""
    if value is None:
        return None
    if (
        isinstance(value, bool)
        or not isinstance(value, int)
        or value < 1
        or value > MAX_CHECKPOINT_AUDIT_EVENT_ID
    ):
        raise ValidationError(
            field="before_audit_event_id",
            value=value,
            reason=(
                "must be a positive integer no greater than PostgreSQL BIGINT maximum"
            ),
        )
    return value


def apply_result_checkpoint_audit_schema(
    postgres_dsn: str,
    migration_path: Optional[str] = None,
) -> None:
    """Apply the idempotent checkpoint accepted-save audit migration."""
    _require_psycopg()
    path = Path(migration_path) if migration_path else AUDIT_MIGRATION_PATH
    sql = path.read_text(encoding="utf-8")
    with psycopg.connect(postgres_dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(sql)
        conn.commit()


def _audit_event_from_row(row: Any) -> CheckpointAuditEvent:
    """Revalidate one database audit row before exposing it publicly."""
    if not isinstance(row, (tuple, list)) or len(row) != 14:
        raise RuntimeError("checkpoint audit row has an invalid shape")
    return CheckpointAuditEvent(
        audit_event_id=row[0],
        tenant_scope=row[1],
        consumer_name=row[2],
        endpoint_alias=row[3],
        batch_id=row[4],
        action=row[5],
        schema_version=row[6],
        file_kind=row[7],
        file_id=row[8],
        file_line_number=row[9],
        batch_line_count=row[10],
        record_count=row[11],
        prefix_sha256=row[12],
        recorded_at=row[13],
    )


def _record_accepted_save(
    cursor: Any,
    tenant_scope: str,
    consumer_name: str,
    checkpoint: BatchResultCheckpoint,
) -> None:
    """Append one successful save-call event inside the caller transaction."""
    cursor.execute(
        "INSERT INTO llm_result_checkpoint_audit_events ("
        "tenant_scope, checkpoint_consumer_name, endpoint_alias, remote_batch_id, "
        "event_action, schema_version, file_kind, file_id, file_line_number, "
        "batch_line_count, record_count, prefix_sha256) VALUES ("
        "%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)",
        (
            tenant_scope,
            consumer_name,
            checkpoint.endpoint_alias,
            checkpoint.batch_id,
            AUDIT_ACTION_CHECKPOINT_SAVE_ACCEPTED,
            checkpoint.schema_version,
            checkpoint.file_kind,
            checkpoint.file_id,
            checkpoint.file_line_number,
            checkpoint.batch_line_count,
            checkpoint.record_count,
            checkpoint.prefix_sha256,
        ),
    )


class AuditedPostgresBatchResultCheckpointStore(PostgresBatchResultCheckpointStore):
    """Persist checkpoints and accepted-save audit rows in one PostgreSQL transaction.

    The audit row records every successful save call, including an idempotent
    repeat. It therefore proves that the package accepted a checkpoint value at
    a database time; it does not claim that every row is a unique state
    transition, that rejected attempts are retained, or that a PostgreSQL owner,
    superuser, or trigger-disabling administrator cannot alter evidence.
    """

    def save(
        self,
        consumer_name: str,
        checkpoint: BatchResultCheckpoint,
        *,
        expected_previous: Optional[BatchResultCheckpoint] = None,
    ) -> BatchResultCheckpoint:
        """Save one checkpoint and its audit event atomically in an owned transaction."""
        _require_psycopg()
        with psycopg.connect(self.postgres_dsn) as conn:
            with conn.cursor() as cur:
                saved = self.save_in_transaction(
                    cur,
                    consumer_name,
                    checkpoint,
                    expected_previous=expected_previous,
                )
            conn.commit()
        return saved

    def save_in_transaction(
        self,
        cursor: Any,
        consumer_name: str,
        checkpoint: BatchResultCheckpoint,
        *,
        expected_previous: Optional[BatchResultCheckpoint] = None,
    ) -> BatchResultCheckpoint:
        """Save and audit through one caller-owned transaction without committing."""
        consumer = validate_checkpoint_consumer_name(consumer_name)
        saved = super().save_in_transaction(
            cursor,
            consumer,
            checkpoint,
            expected_previous=expected_previous,
        )
        _record_accepted_save(cursor, self.tenant_scope, consumer, saved)
        return saved

    def list_audit_events(
        self,
        consumer_name: str,
        batch_id: str,
        endpoint_alias: str,
        *,
        limit: int = DEFAULT_CHECKPOINT_AUDIT_EVENTS,
    ) -> tuple[CheckpointAuditEvent, ...]:
        """Return newest accepted-save events for one tenant-qualified checkpoint key."""
        _require_psycopg()
        with psycopg.connect(self.postgres_dsn) as conn:
            with conn.cursor() as cur:
                return self.list_audit_events_in_transaction(
                    cur,
                    consumer_name,
                    batch_id,
                    endpoint_alias,
                    limit=limit,
                )

    def list_audit_events_in_transaction(
        self,
        cursor: Any,
        consumer_name: str,
        batch_id: str,
        endpoint_alias: str,
        *,
        limit: int = DEFAULT_CHECKPOINT_AUDIT_EVENTS,
    ) -> tuple[CheckpointAuditEvent, ...]:
        """Read a bounded audit page through one caller-owned transaction."""
        consumer = validate_checkpoint_consumer_name(consumer_name)
        remote_batch_id = _validated_batch_id(batch_id)
        alias = _validated_exact_endpoint_alias(endpoint_alias)
        bounded_limit = validate_checkpoint_audit_limit(limit)
        _set_transaction_tenant_scope(cursor, self.tenant_scope)
        cursor.execute(
            f"SELECT {_AUDIT_COLUMNS} "
            "FROM llm_result_checkpoint_audit_events "
            "WHERE tenant_scope = %s "
            "AND checkpoint_consumer_name = %s "
            "AND endpoint_alias = %s "
            "AND remote_batch_id = %s "
            "ORDER BY checkpoint_audit_event_id DESC LIMIT %s",
            (
                self.tenant_scope,
                consumer,
                alias,
                remote_batch_id,
                bounded_limit,
            ),
        )
        rows = cursor.fetchall()
        if not isinstance(rows, (tuple, list)):
            raise RuntimeError("checkpoint audit query returned an invalid row collection")
        events = tuple(_audit_event_from_row(row) for row in rows)
        expected_key = (self.tenant_scope, consumer, alias, remote_batch_id)
        for event in events:
            event_key = (
                event.tenant_scope,
                event.consumer_name,
                event.endpoint_alias,
                event.batch_id,
            )
            if event_key != expected_key:
                raise RuntimeError("checkpoint audit query returned a row outside the requested key")
        return events

    def list_audit_event_page(
        self,
        consumer_name: str,
        batch_id: str,
        endpoint_alias: str,
        *,
        before_audit_event_id: Optional[int] = None,
        limit: int = DEFAULT_CHECKPOINT_AUDIT_EVENTS,
    ) -> CheckpointAuditPage:
        """Return one stable bounded newest-first page for durable audit export."""
        _require_psycopg()
        with psycopg.connect(self.postgres_dsn) as conn:
            with conn.cursor() as cur:
                return self.list_audit_event_page_in_transaction(
                    cur,
                    consumer_name,
                    batch_id,
                    endpoint_alias,
                    before_audit_event_id=before_audit_event_id,
                    limit=limit,
                )

    def list_audit_event_page_in_transaction(
        self,
        cursor: Any,
        consumer_name: str,
        batch_id: str,
        endpoint_alias: str,
        *,
        before_audit_event_id: Optional[int] = None,
        limit: int = DEFAULT_CHECKPOINT_AUDIT_EVENTS,
    ) -> CheckpointAuditPage:
        """Read one keyset page through a caller-owned PostgreSQL transaction.

        The continuation cursor is the final returned audit-event identity. A
        subsequent page uses a strict ``<`` predicate, so rows inserted later
        with larger identities cannot shift already traversed older rows. Hosts
        needing one database snapshot across multiple pages should call this
        method repeatedly inside their own PostgreSQL REPEATABLE READ or stricter
        transaction.
        """
        consumer = validate_checkpoint_consumer_name(consumer_name)
        remote_batch_id = _validated_batch_id(batch_id)
        alias = _validated_exact_endpoint_alias(endpoint_alias)
        bounded_limit = validate_checkpoint_audit_limit(limit)
        before = validate_checkpoint_audit_cursor(before_audit_event_id)
        fetch_size = bounded_limit + 1
        _set_transaction_tenant_scope(cursor, self.tenant_scope)

        query = (
            f"SELECT {_AUDIT_COLUMNS} "
            "FROM llm_result_checkpoint_audit_events "
            "WHERE tenant_scope = %s "
            "AND checkpoint_consumer_name = %s "
            "AND endpoint_alias = %s "
            "AND remote_batch_id = %s "
        )
        params: list[Any] = [
            self.tenant_scope,
            consumer,
            alias,
            remote_batch_id,
        ]
        if before is not None:
            query += "AND checkpoint_audit_event_id < %s "
            params.append(before)
        query += "ORDER BY checkpoint_audit_event_id DESC LIMIT %s"
        params.append(fetch_size)
        cursor.execute(query, tuple(params))

        rows = cursor.fetchall()
        if not isinstance(rows, (tuple, list)):
            raise RuntimeError("checkpoint audit query returned an invalid row collection")
        if len(rows) > fetch_size:
            raise RuntimeError("checkpoint audit query exceeded its bounded query size")

        events = tuple(_audit_event_from_row(row) for row in rows)
        expected_key = (self.tenant_scope, consumer, alias, remote_batch_id)
        for event in events:
            event_key = (
                event.tenant_scope,
                event.consumer_name,
                event.endpoint_alias,
                event.batch_id,
            )
            if event_key != expected_key:
                raise RuntimeError("checkpoint audit query returned a row outside the requested key")
        if before is not None and any(
            event.audit_event_id >= before for event in events
        ):
            raise RuntimeError("checkpoint audit query violated the continuation cursor")
        if any(
            current.audit_event_id >= previous.audit_event_id
            for previous, current in zip(events, events[1:])
        ):
            raise RuntimeError("checkpoint audit query was not strictly descending")

        page_events = events[:bounded_limit]
        next_before = (
            page_events[-1].audit_event_id if len(events) > bounded_limit else None
        )
        return CheckpointAuditPage(
            events=page_events,
            next_before_audit_event_id=next_before,
        )
