# SPDX-License-Identifier: Apache-2.0
"""Relation-topology guards for the durable lifecycle outbox."""

from __future__ import annotations

from typing import Any

from pg_llm_batch.context_lifecycle_outbox import PostgresContextLifecycleOutboxStore


class RecordingCursor:
    """Capture SQL while emulating admitted role authority and no durable row."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.result: Any = None

    def execute(self, sql: str, _params: tuple[Any, ...] | None = None) -> None:
        """Record one normalized SQL statement and its bounded result shape."""
        normalized = " ".join(sql.split())
        self.calls.append(normalized)
        if normalized.startswith("SELECT admitted_role.rolsuper"):
            self.result = (False, False, 4242)
        elif normalized.startswith("SELECT live_relation.oid"):
            self.result = (True, *(None for _ in range(11)))
        else:
            self.result = None

    def fetchone(self) -> Any:
        """Return the result from the preceding statement."""
        return self.result


def test_load_uses_only_canonical_outbox_relation() -> None:
    """Runtime reads must never recurse into PostgreSQL inheritance children."""
    store = PostgresContextLifecycleOutboxStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
        tenant_scope_sha256="a" * 64,
    )
    cursor = RecordingCursor()

    assert store.load_in_transaction(cursor, "event-1") is None

    relation_reads = [
        sql
        for sql in cursor.calls
        if "ONLY public.llm_context_lifecycle_outbox" in sql
    ]
    assert len(relation_reads) == 2
    assert relation_reads[0] == (
        "LOCK TABLE ONLY public.llm_context_lifecycle_outbox IN ACCESS SHARE MODE"
    )
    assert "LEFT JOIN ONLY public.llm_context_lifecycle_outbox AS admitted_outbox" in relation_reads[1]
    assert "admitted_outbox.tableoid OPERATOR(pg_catalog.=) %s::pg_catalog.oid" in relation_reads[1]


def test_runtime_admission_reproves_canonical_relation_storage_authority() -> None:
    """Every I/O must re-prove logged heap storage and no inheritance topology."""
    store = PostgresContextLifecycleOutboxStore(
        "postgresql://unit",
        tenant_scope="tenant-a",
        tenant_scope_sha256="a" * 64,
    )
    cursor = RecordingCursor()

    assert store.load_in_transaction(cursor, "event-1") is None

    admission_sql = next(
        sql
        for sql in cursor.calls
        if sql.startswith("SELECT admitted_role.rolsuper")
    )
    assert (
        "admitted_relation.relkind::pg_catalog.text OPERATOR(pg_catalog.<>) 'r'"
        in admission_sql
    )
    assert (
        "admitted_relation.relpersistence::pg_catalog.text OPERATOR(pg_catalog.<>) 'p'"
        in admission_sql
    )
    assert "JOIN pg_catalog.pg_namespace AS admitted_namespace" in admission_sql
    assert (
        "admitted_namespace.nspname OPERATOR(pg_catalog.<>) 'public'" in admission_sql
    )
    assert "JOIN pg_catalog.pg_am AS admitted_table_access_method" in admission_sql
    assert (
        "admitted_table_access_method.amname OPERATOR(pg_catalog.<>) 'heap'"
        in admission_sql
    )
    assert (
        "admitted_table_access_method.amtype::pg_catalog.text OPERATOR(pg_catalog.<>) 't'"
        in admission_sql
    )
    assert "FROM pg_catalog.pg_inherits AS live_outbox_inheritance" in admission_sql
