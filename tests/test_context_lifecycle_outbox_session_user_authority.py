# SPDX-License-Identifier: Apache-2.0
"""Regression contract for authenticated-session lifecycle-outbox authority."""

from __future__ import annotations

from typing import Any

from pg_llm_batch.context_lifecycle_outbox import _require_rls_application_role


class SessionAuthorityCursor:
    """Capture the runtime admission query while returning one safe-looking verdict."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Record one normalized admission query."""
        self.calls.append((" ".join(sql.split()), params or ()))

    def fetchone(self) -> tuple[bool, bool]:
        """Model the current effective role as apparently safe."""
        return (False, False)


def test_role_admission_inspects_authenticated_session_set_role_escape() -> None:
    """Admission must include every unsafe role the login identity can select/administer."""
    cursor = SessionAuthorityCursor()

    _require_rls_application_role(cursor)

    assert len(cursor.calls) == 1
    sql, params = cursor.calls[0]
    assert "SESSION_USER" in sql
    assert "pg_catalog.pg_has_role(SESSION_USER, selectable_role.oid, 'SET')" in sql
    assert (
        "pg_catalog.pg_has_role(SESSION_USER, selectable_role.oid, "
        "'MEMBER WITH ADMIN OPTION')"
    ) in sql
    assert "selectable_role.rolsuper" in sql
    assert "selectable_role.rolbypassrls" in sql
    assert "pg_catalog.has_table_privilege(selectable_role.oid" in sql
    assert "pg_catalog.has_any_column_privilege(selectable_role.oid" in sql
    assert params == ()
