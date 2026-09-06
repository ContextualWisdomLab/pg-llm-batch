# SPDX-License-Identifier: Apache-2.0
"""Regression tests for lifecycle-outbox effective-role RLS authority."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.context_lifecycle_outbox import _require_rls_application_role
from pg_llm_batch.exceptions import ConfigError


class RoleCursor:
    """Expose one deterministic current-role catalog row to the admission helper."""

    def __init__(self, row: Any) -> None:
        self.row = row
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Record the exact role-authority query without executing PostgreSQL."""
        self.calls.append((" ".join(sql.split()), params or ()))

    def fetchone(self) -> Any:
        """Return the configured effective-role authority row."""
        return self.row


def test_effective_application_role_requires_normal_rls_subject() -> None:
    """A NOSUPERUSER NOBYPASSRLS effective role is admitted."""
    cursor = RoleCursor((False, False))

    _require_rls_application_role(cursor)

    assert cursor.calls == [
        (
            "SELECT admitted_role.rolsuper, admitted_role.rolbypassrls "
            "FROM pg_catalog.pg_roles AS admitted_role "
            "WHERE admitted_role.rolname OPERATOR(pg_catalog.=) CURRENT_USER",
            (),
        )
    ]


@pytest.mark.parametrize(
    "role_row",
    (
        (True, False),
        (False, True),
        (True, True),
        None,
        (False,),
        [False, False],
    ),
)
def test_effective_application_role_rejects_rls_bypass_authority(role_row: Any) -> None:
    """Superuser, BYPASSRLS, and ambiguous catalog identities fail closed."""
    cursor = RoleCursor(role_row)

    with pytest.raises(ConfigError, match="NOSUPERUSER NOBYPASSRLS"):
        _require_rls_application_role(cursor)


def test_role_authority_query_uses_effective_current_user() -> None:
    """Admission must inspect the transaction's effective role, not DSN text."""
    cursor = RoleCursor((False, False))

    _require_rls_application_role(cursor)

    sql, params = cursor.calls[0]
    assert "pg_catalog.pg_roles" in sql
    assert "rolsuper" in sql
    assert "rolbypassrls" in sql
    assert "CURRENT_USER" in sql
    assert params == ()
