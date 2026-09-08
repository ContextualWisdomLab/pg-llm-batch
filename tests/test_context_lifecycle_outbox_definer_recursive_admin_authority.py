# SPDX-License-Identifier: Apache-2.0
"""Regression contract for definer-minted recursive role authority."""

from __future__ import annotations

from typing import Any

from pg_llm_batch.context_lifecycle_outbox import _require_rls_application_role


class _RoleCursor:
    """Capture the lifecycle-outbox admission SQL for authority assertions."""

    def __init__(self) -> None:
        self.sql = ""

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Record normalized SQL without a PostgreSQL dependency."""
        assert params in (None, ())
        self.sql = " ".join(sql.split())

    def fetchone(self) -> tuple[bool, bool, int]:
        """Return the safe verdict and admitted relation identity."""
        return (False, False, 4242)


def test_definer_admin_authority_recurses_across_future_set_and_admin_edges() -> None:
    """A callable owner's administered role must include recursively mintable roles."""
    cursor = _RoleCursor()

    _require_rls_application_role(cursor)

    assert "WITH RECURSIVE definer_delegated_role" in cursor.sql
    assert "pg_catalog.pg_auth_members AS definer_delegated_membership" in cursor.sql
    assert "definer_delegated_membership.member" in cursor.sql
    assert "definer_delegated_membership.roleid" in cursor.sql
    assert (
        "definer_delegated_membership.set_option "
        "OR definer_delegated_membership.admin_option"
        in cursor.sql
    )
