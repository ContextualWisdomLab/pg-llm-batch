# SPDX-License-Identifier: Apache-2.0
"""Static contract for role delegation through callable security definers."""

from __future__ import annotations

from typing import Any

from pg_llm_batch.context_lifecycle_outbox import _require_rls_application_role


class CapturingCursor:
    """Capture the single live runtime-admission catalog query."""

    def __init__(self) -> None:
        self.sql = ""

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Record normalized admission SQL without emulating PostgreSQL catalogs."""
        assert params is None
        self.sql = " ".join(sql.split())

    def fetchone(self) -> tuple[bool, bool]:
        """Return the safe admission verdict used by the static query contract."""
        return (False, False)


def test_callable_security_definer_owner_rejects_admin_delegation_authority() -> None:
    """A callable definer must not redistribute an administered authority closure."""
    cursor = CapturingCursor()

    _require_rls_application_role(cursor)

    assert "WITH RECURSIVE definer_delegated_role(role_oid) AS" in cursor.sql
    assert "definer_admin_role" in cursor.sql
    assert (
        "pg_catalog.pg_has_role(definer_role.oid, definer_admin_role.oid, "
        "'MEMBER WITH ADMIN OPTION')"
    ) in cursor.sql
    assert "definer_delegated_membership.member" in cursor.sql
    assert "definer_delegated_membership.roleid" in cursor.sql
    assert (
        "definer_delegated_membership.set_option OR "
        "definer_delegated_membership.admin_option"
    ) in cursor.sql
    assert "definer_delegated_role_details.rolsuper" in cursor.sql
    assert "definer_delegated_role_details.rolcreatedb" in cursor.sql
    assert "definer_delegated_role_details.rolcreaterole" in cursor.sql
    assert "definer_delegated_role_details.rolreplication" in cursor.sql
    assert "definer_delegated_role_details.rolbypassrls" in cursor.sql
    assert (
        "pg_catalog.has_any_column_privilege(definer_delegated_role_details.oid"
        in cursor.sql
    )
    assert (
        "pg_catalog.has_table_privilege(definer_delegated_role_details.oid"
        in cursor.sql
    )
