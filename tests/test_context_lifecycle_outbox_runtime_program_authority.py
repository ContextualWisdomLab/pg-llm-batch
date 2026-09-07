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


def test_runtime_admission_reproves_attached_index_program_authority() -> None:
    """Post-migration index expressions, predicates, or custom opclasses must fail closed."""
    cursor = ProgramAuthorityCursor()

    _require_rls_application_role(cursor)

    assert "FROM pg_catalog.pg_index AS live_outbox_index" in cursor.sql
    assert "live_outbox_index.indrelid OPERATOR(pg_catalog.=) admitted_relation.oid" in cursor.sql
    assert "live_outbox_index.indexprs IS NOT NULL" in cursor.sql
    assert "live_outbox_index.indpred IS NOT NULL" in cursor.sql
    assert "FROM pg_catalog.pg_opclass AS live_outbox_opclass" in cursor.sql
    assert "live_outbox_opclass.opcnamespace OPERATOR(pg_catalog.=) 'pg_catalog'::pg_catalog.regnamespace" in cursor.sql
    assert "live_outbox_opclass.opcdefault" in cursor.sql
    assert "live_outbox_opclass.opcintype OPERATOR(pg_catalog.=) live_outbox_attribute.atttypid" in cursor.sql
    assert "live_outbox_index.indisunique" in cursor.sql
    assert "live_outbox_constraint.conindid OPERATOR(pg_catalog.=) live_outbox_index.indexrelid" in cursor.sql


def test_runtime_admission_reproves_attached_constraint_authority() -> None:
    """Post-migration CHECK/FK/PK/UNIQUE/EXCLUDE drift must fail closed."""
    cursor = ProgramAuthorityCursor()

    _require_rls_application_role(cursor)

    assert "FROM pg_catalog.pg_constraint AS live_outbox_constraint_authority" in cursor.sql
    assert (
        "live_outbox_constraint_authority.conrelid OPERATOR(pg_catalog.=) admitted_relation.oid"
        in cursor.sql
    )
    assert "live_outbox_constraint_authority.contype::pg_catalog.text" in cursor.sql
    assert "ck_llm_context_lifecycle_outbox_payload_canonical_v1" in cursor.sql
    assert "ck_llm_context_lifecycle_outbox_valid_time_canonical_v1" in cursor.sql
    assert "ck_llm_context_lifecycle_outbox_system_time_canonical_v1" in cursor.sql
    assert "uq_llm_context_lifecycle_outbox_tenant_evidence" in cursor.sql
