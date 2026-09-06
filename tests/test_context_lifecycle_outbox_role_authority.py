# SPDX-License-Identifier: Apache-2.0
"""Regression tests for lifecycle-outbox effective-role RLS authority."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.context_lifecycle_outbox import _require_rls_application_role
from pg_llm_batch.exceptions import ConfigError


class RoleCursor:
    """Expose one deterministic current-role/catalog row to the admission helper."""

    def __init__(self, row: Any) -> None:
        self.row = row
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Record the exact role-authority query without executing PostgreSQL."""
        self.calls.append((" ".join(sql.split()), params or ()))

    def fetchone(self) -> Any:
        """Return the configured effective-role and relation-authority row."""
        return self.row


def test_effective_application_role_requires_separated_forced_rls_authority() -> None:
    """An ordinary non-owner role over enabled+forced RLS is admitted."""
    cursor = RoleCursor((False, False, True, True, False))

    _require_rls_application_role(cursor)

    assert cursor.calls == [
        (
            "SELECT admitted_role.rolsuper, admitted_role.rolbypassrls, "
            "admitted_relation.relrowsecurity, admitted_relation.relforcerowsecurity, "
            "pg_catalog.pg_has_role(CURRENT_USER, admitted_relation.relowner, 'MEMBER') "
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
        (True, False, True, True, False),
        (False, True, True, True, False),
        (False, False, False, True, False),
        (False, False, True, False, False),
        (False, False, True, True, True),
        None,
        (False, False),
        [False, False, True, True, False],
    ),
)
def test_effective_application_role_rejects_rls_bypass_or_schema_authority(
    authority_row: Any,
) -> None:
    """Role bypass, disabled RLS, owner membership, and ambiguity fail closed."""
    cursor = RoleCursor(authority_row)

    with pytest.raises(ConfigError, match="separated forced RLS authority"):
        _require_rls_application_role(cursor)


def test_role_authority_query_uses_effective_current_user_and_live_relation() -> None:
    """Admission must inspect effective role and current outbox RLS ownership."""
    cursor = RoleCursor((False, False, True, True, False))

    _require_rls_application_role(cursor)

    sql, params = cursor.calls[0]
    assert "pg_catalog.pg_roles" in sql
    assert "pg_catalog.pg_class" in sql
    assert "rolsuper" in sql
    assert "rolbypassrls" in sql
    assert "relrowsecurity" in sql
    assert "relforcerowsecurity" in sql
    assert "relowner" in sql
    assert "pg_catalog.pg_has_role" in sql
    assert "pg_catalog.to_regclass" in sql
    assert "CURRENT_USER" in sql
    assert params == ()
