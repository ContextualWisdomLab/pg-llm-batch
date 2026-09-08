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

    def fetchone(self) -> tuple[bool, bool, int]:
        """Return the ordinary-role verdict and admitted relation identity."""
        return (False, False, 4242)


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

    assert "foreign_inheritance_ancestor(relation_oid)" in cursor.sql
    assert "JOIN pg_catalog.pg_inherits AS foreign_inheritance_edge" in cursor.sql
    assert (
        "foreign_inheritance_ancestor.relation_oid OPERATOR(pg_catalog.=) "
        "materialized_source.source_oid"
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
    assert (
        "foreign_inheritance_edge.inhrelid OPERATOR(pg_catalog.=) "
        "foreign_inheritance_ancestor.relation_oid"
        in cursor.sql
    )
    assert "foreign_inheritance_edge.inhparent" in cursor.sql
    assert (
        "foreign_inheritance_ancestor.relation_oid OPERATOR(pg_catalog.=) "
        "exposed_relation.oid"
        in cursor.sql
    )


def test_role_authority_query_follows_traditional_foreign_inheritance() -> None:
    """Inherited parent access must close the same opaque foreign-data authority."""
    cursor = ForeignTableAuthorityCursor()

    _require_rls_application_role(cursor)

    assert (
        "exposed_relation.relkind::pg_catalog.text OPERATOR(pg_catalog.=) 'r'"
        in cursor.sql
    )
    assert (
        "nested_relation.relkind::pg_catalog.text OPERATOR(pg_catalog.=) 'r'"
        in cursor.sql
    )


def test_security_definer_owner_foreign_authority_is_fail_closed() -> None:
    """Callable definer owners must not retain an opaque foreign-data read path."""
    cursor = ForeignTableAuthorityCursor()

    _require_rls_application_role(cursor)

    assert (
        "pg_catalog.has_schema_privilege(definer_role.oid, "
        "exposed_relation_schema.oid, 'USAGE')"
        in cursor.sql
    )
    assert (
        "pg_catalog.has_table_privilege(definer_role.oid, "
        "exposed_relation.oid, 'SELECT')"
        in cursor.sql
    )


def test_security_definer_admin_delegation_foreign_authority_is_fail_closed() -> None:
    """Definer ADMIN OPTION must not mint a selectable opaque foreign-data path."""
    cursor = ForeignTableAuthorityCursor()

    _require_rls_application_role(cursor)

    assert (
        "pg_catalog.has_schema_privilege(definer_delegated_role_details.oid, "
        "exposed_relation_schema.oid, 'USAGE')"
        in cursor.sql
    )
    assert (
        "pg_catalog.has_table_privilege(definer_delegated_role_details.oid, "
        "exposed_relation.oid, 'SELECT')"
        in cursor.sql
    )
