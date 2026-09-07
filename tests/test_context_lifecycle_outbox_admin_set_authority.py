# SPDX-License-Identifier: Apache-2.0
"""Regression contract for ADMIN-delegated SET authority admission."""

from __future__ import annotations

from typing import Any

from pg_llm_batch.context_lifecycle_outbox import _require_rls_application_role


class _RoleCursor:
    """Capture the single lifecycle-outbox admission query."""

    def __init__(self) -> None:
        self.sql = ""

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Record normalized SQL without executing PostgreSQL."""
        assert params in (None, ())
        self.sql = " ".join(sql.split())

    def fetchone(self) -> tuple[bool, bool]:
        """Return the exact safe verdict so query construction can complete."""
        return (False, False)


def test_admin_delegated_set_role_uses_full_forbidden_authority_envelope() -> None:
    """ADMIN-regrantable SET descendants must not retain destructive or opaque authority."""
    cursor = _RoleCursor()

    _require_rls_application_role(cursor)

    start = cursor.sql.index("JOIN pg_catalog.pg_roles AS delegated_dml_role")
    end = cursor.sql.index(
        "OR EXISTS (WITH RECURSIVE executable_definer_owner",
        start,
    )
    delegated = cursor.sql[start:end]

    for privilege in (
        "'SELECT WITH GRANT OPTION'",
        "'INSERT WITH GRANT OPTION'",
        "'TRUNCATE'",
        "'DELETE'",
        "'UPDATE'",
        "'REFERENCES'",
        "'TRIGGER'",
    ):
        assert privilege in delegated
    assert "delegated_dml_role.rolsuper" in delegated
    assert "delegated_dml_role.rolcreatedb" in delegated
    assert "delegated_dml_role.rolcreaterole" in delegated
    assert "delegated_dml_role.rolreplication" in delegated
    assert "delegated_dml_role.rolbypassrls" in delegated
    assert "WITH RECURSIVE foreign_inheritance_ancestor(relation_oid) AS" in delegated
