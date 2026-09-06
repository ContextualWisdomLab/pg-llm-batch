# SPDX-License-Identifier: Apache-2.0
"""Static contract for indirect replication authority through executable definers."""

from __future__ import annotations

from typing import Any

from pg_llm_batch.context_lifecycle_outbox import _require_rls_application_role


class CapturingCursor:
    """Capture the one runtime-admission catalog query without emulating PostgreSQL."""

    def __init__(self) -> None:
        self.sql = ""

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Record the admission SQL; this contract does not execute data statements."""
        assert params is None
        self.sql = " ".join(sql.split())

    def fetchone(self) -> tuple[bool, bool]:
        """Return the safe positive-control verdict expected by package admission."""
        return (False, False)


def test_callable_security_definer_owner_rejects_replication_authority() -> None:
    """A callable definer must not reintroduce PostgreSQL REPLICATION authority."""
    cursor = CapturingCursor()

    _require_rls_application_role(cursor)

    assert "executable_definer.prosecdef" in cursor.sql
    assert "definer_role.rolreplication" in cursor.sql
