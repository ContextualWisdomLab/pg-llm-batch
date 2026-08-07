# SPDX-License-Identifier: Apache-2.0
"""Compatibility vector for checkpoint-audit snapshot manifest schema version 1."""

from datetime import datetime, timezone
from typing import Any

import pytest

import pg_llm_batch.checkpoint_audit as checkpoint_audit
from pg_llm_batch.checkpoint_audit import CheckpointAuditEvent, CheckpointAuditPage


class _InTransactionStatus:
    """Expose the libpq transaction state required by the snapshot contract."""

    name = "INTRANS"


class _ConnectionInfo:
    """Expose deterministic libpq transaction metadata to the cursor double."""

    transaction_status = _InTransactionStatus()


class _Connection:
    """Minimal connection double carrying transaction metadata."""

    info = _ConnectionInfo()


class IsolationCursor:
    """Expose active stable read-only transaction evidence for one manifest build."""

    connection = _Connection()

    def __init__(self) -> None:
        self.last_sql = ""

    def execute(self, sql: str, _params: tuple[Any, ...] | None = None) -> None:
        """Capture the transaction characteristic queried by the manifest builder."""
        self.last_sql = " ".join(sql.split())

    def fetchone(self) -> tuple[str]:
        """Report stable isolation and read-only transaction characteristics."""
        if self.last_sql == "SHOW transaction_read_only":
            return ("on",)
        return ("repeatable read",)


def test_snapshot_manifest_schema_v1_has_fixed_digest_vector(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Schema version 1 framing cannot drift without changing its compatibility contract."""
    event = CheckpointAuditEvent(
        audit_event_id=9,
        tenant_scope="tenant-a",
        consumer_name="worker-a",
        endpoint_alias="default",
        batch_id="batch-1",
        action="checkpoint_save_accepted",
        schema_version=1,
        file_kind="result",
        file_id="file-1",
        file_line_number=9,
        batch_line_count=9,
        record_count=9,
        prefix_sha256=f"{9:064x}",
        recorded_at=datetime(2026, 8, 7, 9, tzinfo=timezone.utc),
    )

    monkeypatch.setattr(
        checkpoint_audit.AuditedPostgresBatchResultCheckpointStore,
        "list_audit_event_page_in_transaction",
        lambda *_args, **_kwargs: CheckpointAuditPage(
            events=(event,),
            next_before_audit_event_id=None,
        ),
    )
    store = checkpoint_audit.AuditedPostgresBatchResultCheckpointStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
    )

    manifest = store.build_audit_snapshot_manifest_in_transaction(
        IsolationCursor(),
        "worker-a",
        "batch-1",
        "default",
    )

    assert manifest.schema_version == 1
    assert manifest.event_count == 1
    assert manifest.newest_audit_event_id == 9
    assert manifest.oldest_audit_event_id == 9
    assert (
        manifest.snapshot_sha256
        == "2bc17add90c354f1ed53efc3031dff567cfb8cddd6e15f6577a024f48a026b96"
    )
