# SPDX-License-Identifier: Apache-2.0
"""PostgreSQL BIGINT compatibility tests for public checkpoint-audit identities."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pg_llm_batch.checkpoint_audit import (
    MAX_CHECKPOINT_AUDIT_EVENT_ID,
    CheckpointAuditEvent,
)


def _event(event_id: int) -> CheckpointAuditEvent:
    """Build one otherwise-valid accepted-save event with a selected identity."""
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
        file_line_number=1,
        batch_line_count=1,
        record_count=1,
        prefix_sha256="a" * 64,
        recorded_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
    )


def test_public_audit_event_identity_matches_postgresql_bigint_domain() -> None:
    """Direct event construction cannot represent an identity PostgreSQL cannot store."""
    assert _event(MAX_CHECKPOINT_AUDIT_EVENT_ID).audit_event_id == MAX_CHECKPOINT_AUDIT_EVENT_ID
    with pytest.raises(ValueError, match="PostgreSQL BIGINT"):
        _event(MAX_CHECKPOINT_AUDIT_EVENT_ID + 1)
