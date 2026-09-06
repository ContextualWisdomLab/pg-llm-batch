# SPDX-License-Identifier: Apache-2.0
"""Regression tests for lifecycle-outbox PostgreSQL role authority."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.context_lifecycle_outbox import _require_rls_application_role
from pg_llm_batch.exceptions import ConfigError


class RoleCursor:
    """Expose one deterministic effective/session role-admission verdict."""

    def __init__(self, row: Any) -> None:
        self.row = row
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Record the exact role-authority query without executing PostgreSQL."""
        self.calls.append((" ".join(sql.split()), params or ()))

    def fetchone(self) -> Any:
        """Return the configured combined role/relation authority verdict."""
        return self.row


def test_application_role_requires_separated_forced_rls_authority() -> None:
    """A safe effective/login role closure is admitted through one catalog query."""
    cursor = RoleCursor((False, False))

    _require_rls_application_role(cursor)

    assert len(cursor.calls) == 1
    sql, params = cursor.calls[0]
    assert "FROM pg_catalog.pg_class AS admitted_relation" in sql
    assert "NOT admitted_relation.relrowsecurity" in sql
    assert "NOT admitted_relation.relforcerowsecurity" in sql
    assert sql.count("FROM pg_catalog.pg_roles AS selectable_role") == 2
    assert "CURRENT_USER" in sql
    assert "SESSION_USER" in sql
    assert params == ()


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
def test_application_role_rejects_rls_bypass_or_schema_authority(
    authority_row: Any,
) -> None:
    """Any combined unsafe verdict other than exact false/false fails closed."""
    cursor = RoleCursor(authority_row)

    with pytest.raises(ConfigError, match="separated forced RLS authority"):
        _require_rls_application_role(cursor)


def test_role_authority_query_covers_effective_and_authenticated_role_closure() -> None:
    """Admission must inspect role-selection/admin escape from the authenticated login."""
    cursor = RoleCursor((False, False))

    _require_rls_application_role(cursor)

    sql, params = cursor.calls[0]
    assert "pg_catalog.pg_roles" in sql
    assert "pg_catalog.pg_class" in sql
    assert "selectable_role.rolsuper" in sql
    assert "selectable_role.rolbypassrls" in sql
    assert "selectable_role.oid OPERATOR(pg_catalog.=) admitted_relation.relowner" in sql
    assert "pg_catalog.pg_has_role" in sql
    assert "SESSION_USER, selectable_role.oid, 'SET'" in sql
    assert "SESSION_USER, selectable_role.oid, 'MEMBER WITH ADMIN OPTION'" in sql
    assert "selectable_role.oid, admitted_relation.relowner, 'USAGE'" in sql
    assert "selectable_role.oid, admitted_relation.relowner, 'SET'" in sql
    assert (
        "selectable_role.oid, admitted_relation.relowner, "
        "'MEMBER WITH ADMIN OPTION'"
    ) in sql
    assert "pg_catalog.has_table_privilege" in sql
    assert "pg_catalog.has_any_column_privilege" in sql
    assert "'TRUNCATE'" in sql
    assert "'DELETE'" in sql
    assert "'UPDATE'" in sql
    assert "'REFERENCES'" in sql
    assert "'TRIGGER'" in sql
    assert "pg_catalog.to_regclass" in sql
    assert "CURRENT_USER" in sql
    assert "SESSION_USER" in sql
    assert params == ()
