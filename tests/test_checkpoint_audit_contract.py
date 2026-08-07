# SPDX-License-Identifier: Apache-2.0
"""Contract tests for tenant-isolated checkpoint audit evidence."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from pg_llm_batch.checkpoint_audit import (
    MAX_CHECKPOINT_AUDIT_EVENTS,
    CheckpointAuditEvent,
    validate_checkpoint_audit_limit,
)
from pg_llm_batch.exceptions import ValidationError


def test_audit_limit_is_strict_bounded_and_noncoercive() -> None:
    """Audit reads accept only an integer within the fixed operator bound."""
    assert validate_checkpoint_audit_limit(1) == 1
    assert validate_checkpoint_audit_limit(MAX_CHECKPOINT_AUDIT_EVENTS) == 1000
    for value in (0, -1, 1001, True, 1.5, "10", None):
        with pytest.raises(ValidationError):
            validate_checkpoint_audit_limit(value)


def test_audit_event_is_immutable_and_validates_action() -> None:
    """Public audit records are immutable and expose only the bounded contract."""
    event = CheckpointAuditEvent(
        audit_event_id=7,
        tenant_scope="tenant-a",
        consumer_name="worker-a",
        endpoint_alias="default",
        batch_id="batch-1",
        action="checkpoint_save_accepted",
        schema_version=1,
        file_kind="result",
        file_id="file-1",
        file_line_number=2,
        batch_line_count=2,
        record_count=1,
        prefix_sha256="a" * 64,
        recorded_at=datetime(2026, 8, 7, tzinfo=timezone.utc),
    )
    assert event.action == "checkpoint_save_accepted"
    with pytest.raises(Exception):
        event.action = "changed"  # type: ignore[misc]


def test_audit_migration_is_append_only_tenant_isolated_and_descriptive() -> None:
    """Migration text must provide forced RLS and mutation-resistant audit rows."""
    root = Path(__file__).resolve().parents[1]
    package = root / "pg_llm_batch/migrations/0008_result_checkpoint_audit_events.sql"
    container = root / "docker/postgres/init/04_result_checkpoint_audit_events.sql"
    assert package.read_bytes() == container.read_bytes()
    sql = package.read_text(encoding="utf-8")
    required = (
        "CREATE TABLE IF NOT EXISTS llm_result_checkpoint_audit_events",
        "checkpoint_audit_event_id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY",
        "recorded_at TIMESTAMPTZ NOT NULL DEFAULT clock_timestamp()",
        "ALTER TABLE llm_result_checkpoint_audit_events ENABLE ROW LEVEL SECURITY",
        "ALTER TABLE llm_result_checkpoint_audit_events FORCE ROW LEVEL SECURITY",
        "CREATE POLICY plc_llm_result_checkpoint_audit_events_tenant_scope",
        "CREATE FUNCTION reject_checkpoint_audit_mutation()",
        "CREATE TRIGGER checkpoint_audit_row_immutability",
        "BEFORE UPDATE OR DELETE",
        "CREATE TRIGGER checkpoint_audit_truncate_immutability",
        "BEFORE TRUNCATE",
    )
    for phrase in required:
        assert phrase in sql
    assert "recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW()" not in sql


def test_checkpoint_audit_rollback_refuses_nonempty_evidence() -> None:
    """Rollback must fail closed rather than erase accepted-save evidence."""
    root = Path(__file__).resolve().parents[1]
    rollback = root / "pg_llm_batch/migrations/rollback/0008_result_checkpoint_audit_events.sql"
    sql = " ".join(rollback.read_text(encoding="utf-8").split())
    assert "IF EXISTS ( SELECT 1 FROM llm_result_checkpoint_audit_events LIMIT 1 )" in sql
    assert "refusing to drop non-empty llm_result_checkpoint_audit_events" in sql.lower()
    assert "DROP TABLE IF EXISTS llm_result_checkpoint_audit_events" in sql


def test_postgres_image_installs_audit_migration_after_checkpoint_schema() -> None:
    """Fresh bundled databases execute audit schema after checkpoint persistence."""
    root = Path(__file__).resolve().parents[1]
    dockerfile = (root / "docker/postgres/Dockerfile").read_text(encoding="utf-8")
    checkpoint_copy = (
        "COPY init/03_result_stream_checkpoints.sql "
        "/docker-entrypoint-initdb.d/04_result_stream_checkpoints.sql"
    )
    audit_copy = (
        "COPY init/04_result_checkpoint_audit_events.sql "
        "/docker-entrypoint-initdb.d/05_result_checkpoint_audit_events.sql"
    )
    assert checkpoint_copy in dockerfile
    assert audit_copy in dockerfile
    assert dockerfile.index(checkpoint_copy) < dockerfile.index(audit_copy)
