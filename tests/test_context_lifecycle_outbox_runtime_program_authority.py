# SPDX-License-Identifier: Apache-2.0
"""Regression tests for live lifecycle-outbox table-program admission."""

from __future__ import annotations

from typing import Any

from pg_llm_batch.context_lifecycle_outbox import _require_rls_application_role


class ProgramAuthorityCursor:
    """Capture the live runtime-admission query for structural verification."""

    def __init__(self) -> None:
        self.sql = ""

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Record normalized SQL while preserving the cursor protocol."""
        assert params is None
        self.sql = " ".join(sql.split())

    def fetchone(self) -> tuple[bool, bool]:
        """Return the safe verdict so only query structure is under test."""
        return (False, False)


def test_runtime_admission_reproves_attached_table_program_authority() -> None:
    """A migration receipt must not authorize later trigger or rewrite-rule drift."""
    cursor = ProgramAuthorityCursor()

    _require_rls_application_role(cursor)

    assert "FROM pg_catalog.pg_trigger AS live_outbox_trigger" in cursor.sql
    assert "live_outbox_trigger.tgrelid OPERATOR(pg_catalog.=) admitted_relation.oid" in cursor.sql
    assert "NOT live_outbox_trigger.tgisinternal" in cursor.sql
    assert "FROM pg_catalog.pg_rewrite AS live_outbox_rule" in cursor.sql
    assert "live_outbox_rule.ev_class OPERATOR(pg_catalog.=) admitted_relation.oid" in cursor.sql
