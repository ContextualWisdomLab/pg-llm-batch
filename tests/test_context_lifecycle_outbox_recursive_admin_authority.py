# SPDX-License-Identifier: Apache-2.0
"""Regression contract for transitive SET/ADMIN role-authority admission."""

from __future__ import annotations

from typing import Any

from pg_llm_batch.context_lifecycle_outbox import _require_rls_application_role


class _RoleCursor:
    """Capture the lifecycle-outbox admission query without executing PostgreSQL."""

    def __init__(self) -> None:
        self.sql = ""

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Record normalized SQL for structural security assertions."""
        assert params in (None, ())
        self.sql = " ".join(sql.split())

    def fetchone(self) -> tuple[bool, bool, int]:
        """Return the exact safe verdict and admitted relation identity."""
        return (False, False, 4242)


def test_session_reachable_authority_recurses_across_set_and_admin_edges() -> None:
    """Only an ADMIN-bearing path may widen ordinary SET authority into future grants."""
    cursor = _RoleCursor()

    _require_rls_application_role(cursor)

    assert "pg_catalog.pg_auth_members" in cursor.sql
    assert "admin_option" in cursor.sql
    assert "set_option" in cursor.sql
    assert "WITH RECURSIVE delegated_role(role_oid, admin_seen)" in cursor.sql
    assert "delegated_membership.member" in cursor.sql
    assert "delegated_membership.roleid" in cursor.sql
    assert (
        "delegated_role.admin_seen OR delegated_membership.admin_option"
        in cursor.sql
    )
    assert (
        "delegated_membership.set_option OR delegated_membership.admin_option"
        in cursor.sql
    )
    assert "AND delegated_role.admin_seen AND" in cursor.sql
