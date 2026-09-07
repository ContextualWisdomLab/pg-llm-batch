# SPDX-License-Identifier: Apache-2.0
"""Regression contract for lifecycle-outbox foreign-table authority admission."""

from __future__ import annotations

from typing import Any

from pg_llm_batch.context_lifecycle_outbox import _require_rls_application_role


class ForeignTableAuthorityCursor:
    """Capture the single live role/relation admission catalog query."""

    def __init__(self) -> None:
        self.sql = ""

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Record normalized SQL without replacing the hosted PostgreSQL specimen."""
        assert params is None
        self.sql = " ".join(sql.split())

    def fetchone(self) -> tuple[bool, bool]:
        """Return the ordinary-role verdict so only query shape is under test."""
        return (False, False)


def test_role_authority_query_fail_closes_reachable_foreign_tables() -> None:
    """Direct or view-hidden foreign data must not be treated as local forced-RLS data."""
    cursor = ForeignTableAuthorityCursor()

    _require_rls_application_role(cursor)

    assert (
        "exposed_relation.relkind::pg_catalog.text OPERATOR(pg_catalog.=) 'f'"
        in cursor.sql
    )
    assert (
        "nested_relation.relkind::pg_catalog.text OPERATOR(pg_catalog.=) 'f'"
        in cursor.sql
    )


def test_materialized_provenance_fail_closes_foreign_sources() -> None:
    """Copied remote rows remain opaque authority after the foreign read has finished."""
    cursor = ForeignTableAuthorityCursor()

    _require_rls_application_role(cursor)

    assert "JOIN pg_catalog.pg_class AS materialized_source_relation_guard" in cursor.sql
    assert (
        "materialized_source_relation_guard.oid OPERATOR(pg_catalog.=) "
        "materialized_source.source_oid"
    ) in cursor.sql
    assert (
        "materialized_source_relation_guard.relkind::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'f'"
        in cursor.sql
    )


def test_role_authority_query_follows_partitioned_foreign_descendants() -> None:
    """Parent-only SELECT must not hide a foreign partition from runtime admission."""
    cursor = ForeignTableAuthorityCursor()

    _require_rls_application_role(cursor)

    assert (
        "exposed_relation.relkind::pg_catalog.text OPERATOR(pg_catalog.=) 'p'"
        in cursor.sql
    )
    assert "JOIN pg_catalog.pg_inherits AS reachable_partition_edge" in cursor.sql
    assert (
        "reachable_partition_edge.inhparent OPERATOR(pg_catalog.=) "
        "reachable_partition.relation_oid"
        in cursor.sql
    )
    assert (
        "reachable_partition_child.relkind::pg_catalog.text "
        "OPERATOR(pg_catalog.=) 'f'"
        in cursor.sql
    )
