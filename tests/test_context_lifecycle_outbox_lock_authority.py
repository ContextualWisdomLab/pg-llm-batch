# SPDX-License-Identifier: Apache-2.0
"""Verify lifecycle-outbox reads retain admitted relation authority through I/O."""

from __future__ import annotations

from typing import Any

from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore


class RecordingCursor:
    """Record outbox SQL while returning one admitted empty tenant result."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.result: Any = None

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Record one statement and return its deterministic result shape."""
        normalized = " ".join(sql.split())
        parameters = params or ()
        self.calls.append((normalized, parameters))
        if normalized.startswith("SELECT admitted_role.rolsuper"):
            self.result = (False, False, 4242)
        elif normalized.startswith("SELECT pg_catalog.pg_advisory_xact_lock"):
            self.result = (None,)
        elif normalized.startswith("SELECT live_relation.oid"):
            self.result = (True, *(None for _ in range(11)))
        else:
            self.result = None

    def fetchone(self) -> Any:
        """Return the current deterministic row."""
        return self.result


def store() -> PostgresContextLifecycleOutboxStore:
    """Create one package store without opening a database connection."""
    return PostgresContextLifecycleOutboxStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
        tenant_scope_sha256="a" * 64,
    )


def test_read_lock_precedes_live_authority_admission_and_identity_bound_select() -> None:
    """Ordinary reads retain the table lock and OID proof through tenant SELECT."""
    cursor = RecordingCursor()
    assert store().load_in_transaction(cursor, "event-1") is None

    assert len(cursor.calls) == 4
    assert cursor.calls[0][0] == (
        "LOCK TABLE ONLY public.llm_context_lifecycle_outbox IN ACCESS SHARE MODE"
    )
    assert cursor.calls[1][0].startswith("SELECT admitted_role.rolsuper")
    assert cursor.calls[2] == (
        "SELECT pg_catalog.set_config('pg_llm_batch.tenant_scope', %s, true)",
        ("tenant-a",),
    )
    assert cursor.calls[3][0].startswith("SELECT live_relation.oid")
    assert "admitted_outbox.tableoid" in cursor.calls[3][0]
    assert cursor.calls[3][1][:2] == (4242, 4242)
    assert cursor.calls[3][1][-2:] == ("tenant-a", "event-1")


def test_serialized_read_retains_relation_lock_before_advisory_lock() -> None:
    """Serialized reads keep relation authority before event-identity serialization."""
    cursor = RecordingCursor()
    assert store().load_in_transaction(cursor, "event-1", for_update=True) is None

    assert len(cursor.calls) == 5
    assert cursor.calls[0][0].startswith("LOCK TABLE ONLY public.llm_context_lifecycle_outbox")
    assert cursor.calls[1][0].startswith("SELECT admitted_role.rolsuper")
    assert cursor.calls[2][0].startswith("SELECT pg_catalog.set_config")
    assert cursor.calls[3][0].startswith("SELECT pg_catalog.pg_advisory_xact_lock")
    assert cursor.calls[4][0].startswith("SELECT live_relation.oid")
