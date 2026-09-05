# SPDX-License-Identifier: Apache-2.0
"""Relation-topology guards for the durable lifecycle outbox."""

from __future__ import annotations

from typing import Any

from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore


class RecordingCursor:
    """Capture SQL without providing any durable row."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def execute(self, sql: str, _params: tuple[Any, ...] | None = None) -> None:
        """Record one normalized SQL statement."""
        self.calls.append(" ".join(sql.split()))

    def fetchone(self) -> None:
        """Represent an absent durable event."""
        return None


def test_load_uses_only_canonical_outbox_relation() -> None:
    """Runtime reads must never recurse into PostgreSQL inheritance children."""
    store = PostgresContextLifecycleOutboxStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
        tenant_scope_sha256="a" * 64,
    )
    cursor = RecordingCursor()

    assert store.load_in_transaction(cursor, "event-1") is None

    relation_reads = [sql for sql in cursor.calls if "llm_context_lifecycle_outbox" in sql]
    assert relation_reads == [
        "SELECT evidence_id, event_type, tenant_scope_sha256, subject_ref_sha256, "
        "authority_ref_sha256, origin_ref_sha256, truth_status, valid_time, system_time, "
        "provenance_ref_sha256, evidence_ref_sha256 FROM ONLY "
        "public.llm_context_lifecycle_outbox WHERE tenant_scope = %s AND evidence_id = %s"
    ]
