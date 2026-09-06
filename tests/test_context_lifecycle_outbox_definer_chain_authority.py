# SPDX-License-Identifier: Apache-2.0
"""Static contract for transitive callable SECURITY DEFINER authority."""

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


def test_callable_security_definer_authority_closure_is_recursive() -> None:
    """A caller-visible definer must carry nested executable definers into admission."""
    cursor = CapturingCursor()

    _require_rls_application_role(cursor)

    assert "WITH RECURSIVE executable_definer_owner(role_oid) AS" in cursor.sql
    assert "nested_executable_definer" in cursor.sql
    assert "nested_definer_schema" in cursor.sql
    assert (
        "pg_catalog.has_schema_privilege(executable_definer_owner.role_oid, "
        "nested_definer_schema.oid, 'USAGE')"
    ) in cursor.sql
    assert (
        "pg_catalog.has_function_privilege(executable_definer_owner.role_oid, "
        "nested_executable_definer.oid, 'EXECUTE')"
    ) in cursor.sql
    assert (
        "nested_executable_definer.proowner" in cursor.sql
        and "UNION" in cursor.sql
    )
