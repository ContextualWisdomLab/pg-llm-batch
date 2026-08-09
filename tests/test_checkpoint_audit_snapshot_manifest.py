# SPDX-License-Identifier: Apache-2.0
"""Behavior contracts for bounded checkpoint-audit snapshot manifests."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone, tzinfo
from typing import Any

import pytest

import pg_llm_batch.checkpoint_audit as checkpoint_audit
from pg_llm_batch.checkpoint_audit import (
    MAX_CHECKPOINT_AUDIT_SNAPSHOT_EVENTS,
    CheckpointAuditEvent,
    CheckpointAuditPage,
    CheckpointAuditSnapshotManifest,
    validate_checkpoint_audit_snapshot_max_events,
)
from pg_llm_batch.exceptions import ValidationError


class _UnresolvedTimezone(tzinfo):
    """Carry a tzinfo object that deliberately provides no UTC offset."""

    def utcoffset(self, _value: datetime | None) -> timedelta | None:
        """Return no offset so Python still treats the datetime as naive."""
        return None

    def dst(self, _value: datetime | None) -> timedelta | None:
        """Return no daylight-saving offset for the unresolved timezone."""
        return None

    def tzname(self, _value: datetime | None) -> str:
        """Return a stable display name without implying an actual offset."""
        return "unresolved"


def _event(event_id: int, *, digest_seed: int | None = None) -> CheckpointAuditEvent:
    """Build one valid deterministic audit event for manifest tests."""
    seed = event_id if digest_seed is None else digest_seed
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
        prefix_sha256=f"{seed:064x}",
        recorded_at=datetime(2026, 8, 7, event_id % 24, tzinfo=timezone.utc),
    )


class _InTransactionStatus:
    """Expose the libpq transaction-status name required by snapshot callers."""

    name = "INTRANS"


class _ConnectionInfo:
    """Expose deterministic connection transaction metadata to cursor tests."""

    transaction_status = _InTransactionStatus()


class _Connection:
    """Minimal connection double carrying libpq-style transaction metadata."""

    info = _ConnectionInfo()


class IsolationCursor:
    """Expose one active read-only transaction, isolation row, and captured SQL."""

    def __init__(self, isolation: Any = ("repeatable read",)) -> None:
        self.connection = _Connection()
        self.isolation = isolation
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Capture one normalized SQL statement and parameters."""
        self.calls.append((" ".join(sql.split()), params or ()))

    def fetchone(self) -> Any:
        """Return the configured isolation or read-only transaction evidence."""
        if self.calls and self.calls[-1][0] == "SHOW transaction_read_only":
            return ("on",)
        return self.isolation


def test_snapshot_max_events_is_strict_bounded_integer() -> None:
    """Snapshot limits reject coercion and unreasonable unbounded traversal."""
    assert validate_checkpoint_audit_snapshot_max_events(1) == 1
    assert (
        validate_checkpoint_audit_snapshot_max_events(MAX_CHECKPOINT_AUDIT_SNAPSHOT_EVENTS)
        == MAX_CHECKPOINT_AUDIT_SNAPSHOT_EVENTS
    )
    for value in (
        True,
        0,
        -1,
        MAX_CHECKPOINT_AUDIT_SNAPSHOT_EVENTS + 1,
        1.0,
        "100",
        object(),
    ):
        with pytest.raises(ValidationError):
            validate_checkpoint_audit_snapshot_max_events(value)


def test_snapshot_manifest_is_immutable_and_revalidates_public_fields() -> None:
    """Direct construction cannot advertise malformed snapshot evidence."""
    manifest = CheckpointAuditSnapshotManifest(
        schema_version=1,
        tenant_scope="tenant-a",
        consumer_name="worker-a",
        endpoint_alias="default",
        batch_id="batch-1",
        event_count=2,
        newest_audit_event_id=9,
        oldest_audit_event_id=8,
        snapshot_sha256="a" * 64,
    )
    assert manifest.event_count == 2
    assert manifest.newest_audit_event_id == 9
    assert manifest.oldest_audit_event_id == 8

    invalid = (
        {"schema_version": 2},
        {"schema_version": 1.0},
        {"event_count": True},
        {"event_count": -1},
        {"event_count": 0, "newest_audit_event_id": 1, "oldest_audit_event_id": 1},
        {"event_count": 1, "newest_audit_event_id": None, "oldest_audit_event_id": None},
        {"event_count": 1, "newest_audit_event_id": 9, "oldest_audit_event_id": 8},
        {"event_count": 2, "newest_audit_event_id": 8, "oldest_audit_event_id": 9},
        {"event_count": 2, "newest_audit_event_id": 9, "oldest_audit_event_id": 9},
        {"snapshot_sha256": "A" * 64},
        {"snapshot_sha256": "a" * 63},
        {"snapshot_sha256": "g" * 64},
    )
    baseline: dict[str, Any] = {
        "schema_version": 1,
        "tenant_scope": "tenant-a",
        "consumer_name": "worker-a",
        "endpoint_alias": "default",
        "batch_id": "batch-1",
        "event_count": 2,
        "newest_audit_event_id": 9,
        "oldest_audit_event_id": 8,
        "snapshot_sha256": "a" * 64,
    }
    for override in invalid:
        with pytest.raises(ValueError):
            CheckpointAuditSnapshotManifest(**(baseline | override))


def test_audit_event_rejects_tzinfo_without_a_utc_offset() -> None:
    """A tzinfo object alone must not satisfy deterministic timestamp evidence."""
    unresolved = datetime(2026, 8, 9, 10, 30, tzinfo=_UnresolvedTimezone())

    with pytest.raises(ValueError, match="timezone-aware"):
        CheckpointAuditEvent(
            audit_event_id=1,
            tenant_scope="tenant-a",
            consumer_name="worker-a",
            endpoint_alias="default",
            batch_id="batch-1",
            action="checkpoint_save_accepted",
            schema_version=1,
            file_kind="result",
            file_id="file-1",
            file_line_number=1,
            batch_line_count=1,
            record_count=1,
            prefix_sha256="a" * 64,
            recorded_at=unresolved,
        )


def test_snapshot_manifest_requires_repeatable_read_or_serializable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A moving READ COMMITTED view cannot be mislabeled as one database snapshot."""
    store = checkpoint_audit.AuditedPostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )
    called = False

    def unexpected_page(*_args: Any, **_kwargs: Any) -> CheckpointAuditPage:
        nonlocal called
        called = True
        return CheckpointAuditPage(events=(), next_before_audit_event_id=None)

    monkeypatch.setattr(
        checkpoint_audit.AuditedPostgresBatchResultCheckpointStore,
        "list_audit_event_page_in_transaction",
        unexpected_page,
    )

    with pytest.raises(RuntimeError, match="REPEATABLE READ or SERIALIZABLE"):
        store.build_audit_snapshot_manifest_in_transaction(
            IsolationCursor(("read committed",)),
            "worker-a",
            "batch-1",
            "default",
        )
    assert called is False

    for malformed in (None, (), ("repeatable read", "extra"), (1,), ["repeatable read"]):
        with pytest.raises(RuntimeError, match="transaction isolation"):
            store.build_audit_snapshot_manifest_in_transaction(
                IsolationCursor(malformed),
                "worker-a",
                "batch-1",
                "default",
            )


def test_snapshot_manifest_streams_bounded_pages_and_is_deterministic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """One snapshot hash traverses keyset pages without materializing the full audit trail."""
    store = checkpoint_audit.AuditedPostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )
    pages = [
        CheckpointAuditPage(events=(_event(9), _event(8)), next_before_audit_event_id=8),
        CheckpointAuditPage(events=(_event(7),), next_before_audit_event_id=None),
    ]
    calls: list[tuple[int | None, int]] = []

    def page(
        _store: Any,
        _cursor: Any,
        consumer_name: str,
        batch_id: str,
        endpoint_alias: str,
        *,
        before_audit_event_id: int | None = None,
        limit: int,
    ) -> CheckpointAuditPage:
        assert (consumer_name, batch_id, endpoint_alias) == (
            "worker-a",
            "batch-1",
            "default",
        )
        calls.append((before_audit_event_id, limit))
        return pages[len(calls) - 1]

    monkeypatch.setattr(
        checkpoint_audit.AuditedPostgresBatchResultCheckpointStore,
        "list_audit_event_page_in_transaction",
        page,
    )

    first = store.build_audit_snapshot_manifest_in_transaction(
        IsolationCursor(),
        "worker-a",
        "batch-1",
        "default",
        max_events=3,
        page_size=2,
    )
    calls.clear()
    second = store.build_audit_snapshot_manifest_in_transaction(
        IsolationCursor(("serializable",)),
        "worker-a",
        "batch-1",
        "default",
        max_events=3,
        page_size=2,
    )

    assert first == second
    assert first.event_count == 3
    assert first.newest_audit_event_id == 9
    assert first.oldest_audit_event_id == 7
    assert len(first.snapshot_sha256) == 64
    assert first.snapshot_sha256 == first.snapshot_sha256.lower()
    assert calls == [(None, 2), (8, 1)]


def test_snapshot_manifest_digest_changes_when_retained_event_changes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Any validated retained-field mutation changes deterministic snapshot identity."""
    store = checkpoint_audit.AuditedPostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )
    current = [_event(9)]

    def page(*_args: Any, **_kwargs: Any) -> CheckpointAuditPage:
        return CheckpointAuditPage(events=(current[0],), next_before_audit_event_id=None)

    monkeypatch.setattr(
        checkpoint_audit.AuditedPostgresBatchResultCheckpointStore,
        "list_audit_event_page_in_transaction",
        page,
    )
    original = store.build_audit_snapshot_manifest_in_transaction(
        IsolationCursor(), "worker-a", "batch-1", "default"
    )
    current[0] = _event(9, digest_seed=10)
    changed = store.build_audit_snapshot_manifest_in_transaction(
        IsolationCursor(), "worker-a", "batch-1", "default"
    )
    assert original.snapshot_sha256 != changed.snapshot_sha256


def test_snapshot_manifest_fails_closed_when_snapshot_exceeds_max_events(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A continuation beyond the caller budget fails before silently truncating evidence."""
    store = checkpoint_audit.AuditedPostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )

    def page(*_args: Any, **_kwargs: Any) -> CheckpointAuditPage:
        return CheckpointAuditPage(
            events=(_event(9), _event(8)),
            next_before_audit_event_id=8,
        )

    monkeypatch.setattr(
        checkpoint_audit.AuditedPostgresBatchResultCheckpointStore,
        "list_audit_event_page_in_transaction",
        page,
    )
    with pytest.raises(RuntimeError, match="exceeds max_events"):
        store.build_audit_snapshot_manifest_in_transaction(
            IsolationCursor(),
            "worker-a",
            "batch-1",
            "default",
            max_events=2,
            page_size=2,
        )


def test_empty_snapshot_manifest_has_no_identity_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An empty stable snapshot remains explicit rather than inventing event identities."""
    store = checkpoint_audit.AuditedPostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )
    monkeypatch.setattr(
        checkpoint_audit.AuditedPostgresBatchResultCheckpointStore,
        "list_audit_event_page_in_transaction",
        lambda *_args, **_kwargs: CheckpointAuditPage(
            events=(), next_before_audit_event_id=None
        ),
    )
    manifest = store.build_audit_snapshot_manifest_in_transaction(
        IsolationCursor(), "worker-a", "batch-1", "default"
    )
    assert manifest.event_count == 0
    assert manifest.newest_audit_event_id is None
    assert manifest.oldest_audit_event_id is None
    assert len(manifest.snapshot_sha256) == 64
