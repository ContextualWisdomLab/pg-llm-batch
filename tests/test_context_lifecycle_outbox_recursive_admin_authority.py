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

    def fetchone(self) -> tuple[bool, bool]:
        """Return the exact safe verdict expected by the admission helper."""
        return (False, False)


def test_session_reachable_authority_recurses_across_set_and_admin_edges() -> None:
    """A selectable role's ADMIN edge must recursively widen the future SET closure."""
    cursor = _RoleCursor()

    _require_rls_application_role(cursor)

    assert "pg_catalog.pg_auth_members" in cursor.sql
    assert "admin_option" in cursor.sql
    assert "set_option" in cursor.sql
    assert "WITH RECURSIVE delegated_role" in cursor.sql
    assert "delegated_membership.member" in cursor.sql
    assert "delegated_membership.roleid" in cursor.sql
    assert (
        "delegated_membership.set_option OR delegated_membership.admin_option"
        in cursor.sql
    )
