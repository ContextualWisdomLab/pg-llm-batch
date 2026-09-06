# SPDX-License-Identifier: Apache-2.0
"""Regression tests for lifecycle-outbox effective-role RLS authority."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.context_lifecycle_outbox import _require_rls_application_role
from pg_llm_batch.exceptions import ConfigError


class RoleCursor:
    """Expose one deterministic effective-role admission row to the helper."""

    def __init__(self, row: Any) -> None:
        self.row = row
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Record the exact role-authority query without executing PostgreSQL."""
        self.calls.append((" ".join(sql.split()), params or ()))

    def fetchone(self) -> Any:
        """Return the configured combined role/relation authority verdict."""
        return self.row


def test_effective_application_role_requires_separated_forced_rls_authority() -> None:
    """An ordinary non-owner role without destructive table authority is admitted."""
    cursor = RoleCursor((False, False))

    _require_rls_application_role(cursor)

    assert cursor.calls == [
        (
            "SELECT admitted_role.rolsuper "
            "OR NOT admitted_relation.relrowsecurity "
            "OR NOT admitted_relation.relforcerowsecurity "
            "OR admitted_role.oid OPERATOR(pg_catalog.=) admitted_relation.relowner "
            "OR pg_catalog.pg_has_role("
            "CURRENT_USER, admitted_relation.relowner, 'USAGE') "
            "OR pg_catalog.pg_has_role("
            "CURRENT_USER, admitted_relation.relowner, 'SET') "
            "OR pg_catalog.pg_has_role("
            "CURRENT_USER, admitted_relation.relowner, 'MEMBER WITH ADMIN OPTION') "
            "OR pg_catalog.has_table_privilege("
            "CURRENT_USER, admitted_relation.oid, 'TRUNCATE') "
            "OR pg_catalog.has_table_privilege("
            "CURRENT_USER, admitted_relation.oid, 'DELETE') "
            "OR pg_catalog.has_any_column_privilege("
            "CURRENT_USER, admitted_relation.oid, 'UPDATE') "
            "OR pg_catalog.has_any_column_privilege("
            "CURRENT_USER, admitted_relation.oid, 'REFERENCES') "
            "OR pg_catalog.has_table_privilege("
            "CURRENT_USER, admitted_relation.oid, 'TRIGGER'), "
            "admitted_role.rolbypassrls "
            "FROM pg_catalog.pg_roles AS admitted_role "
            "JOIN pg_catalog.pg_class AS admitted_relation "
            "ON admitted_relation.oid OPERATOR(pg_catalog.=) "
            "pg_catalog.to_regclass('public.llm_context_lifecycle_outbox') "
            "WHERE admitted_role.rolname OPERATOR(pg_catalog.=) CURRENT_USER",
            (),
        )
    ]


@pytest.mark.parametrize(
    "authority_row",
    (
        (True, False),
        (False, True),
        (True, True),
        None,
        (False,),
        [False, False],
    ),
)
def test_effective_application_role_rejects_rls_bypass_or_schema_authority(
    authority_row: Any,
) -> None:
    """Any combined bypass/schema-authority verdict other than false/false fails."""
    cursor = RoleCursor(authority_row)

    with pytest.raises(ConfigError, match="separated forced RLS authority"):
        _require_rls_application_role(cursor)


def test_role_authority_query_uses_effective_current_user_and_live_relation() -> None:
    """Admission must inspect effective role and current outbox RLS ownership."""
    cursor = RoleCursor((False, False))

    _require_rls_application_role(cursor)

    sql, params = cursor.calls[0]
    assert "pg_catalog.pg_roles" in sql
    assert "pg_catalog.pg_class" in sql
    assert "rolsuper" in sql
    assert "rolbypassrls" in sql
    assert "NOT admitted_relation.relrowsecurity" in sql
    assert "NOT admitted_relation.relforcerowsecurity" in sql
    assert "admitted_role.oid OPERATOR(pg_catalog.=) admitted_relation.relowner" in sql
    assert "pg_catalog.pg_has_role" in sql
    assert "'USAGE'" in sql
    assert "'SET'" in sql
    assert "'MEMBER WITH ADMIN OPTION'" in sql
    assert "pg_catalog.has_table_privilege" in sql
    assert "pg_catalog.has_any_column_privilege" in sql
    assert "'TRUNCATE'" in sql
    assert "'DELETE'" in sql
    assert "'UPDATE'" in sql
    assert "'REFERENCES'" in sql
    assert "'TRIGGER'" in sql
    assert "pg_catalog.to_regclass" in sql
    assert "CURRENT_USER" in sql
    assert params == ()
