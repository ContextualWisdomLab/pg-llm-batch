# SPDX-License-Identifier: Apache-2.0
"""Regression contract for lifecycle-outbox PostgreSQL MAINTAIN authority."""

from __future__ import annotations

from typing import Any

from pg_llm_batch.context_lifecycle_outbox import _require_rls_application_role


class MaintainAuthorityCursor:
    """Capture the runtime role-admission query with one safe synthetic verdict."""

    def __init__(self) -> None:
        self.sql = ""

    def execute(self, sql: str, params: tuple[Any, ...] | None = None) -> None:
        """Retain the normalized admission query for structural assertions."""
        assert params is None
        self.sql = " ".join(sql.split())

    def fetchone(self) -> tuple[bool, bool]:
        """Return the exact admitted verdict shape expected by the boundary."""
        return (False, False)


def test_role_admission_rejects_maintain_across_executable_authority_closure() -> None:
    """Every relation-authority principal must treat MAINTAIN as non-runtime authority."""
    cursor = MaintainAuthorityCursor()

    _require_rls_application_role(cursor)

    sql = cursor.sql
    assert (
        "pg_catalog.has_table_privilege(selectable_role.oid, "
        "admitted_relation.oid, 'MAINTAIN')"
    ) in sql
    assert (
        "pg_catalog.has_table_privilege(delegated_dml_role.oid, "
        "admitted_relation.oid, 'MAINTAIN')"
    ) in sql
    assert (
        "pg_catalog.has_table_privilege(definer_role.oid, "
        "admitted_relation.oid, 'MAINTAIN')"
    ) in sql
    assert (
        "pg_catalog.has_table_privilege(definer_admin_role.oid, "
        "admitted_relation.oid, 'MAINTAIN')"
    ) in sql
    assert (
        "pg_catalog.has_table_privilege(definer_admin_set_role.oid, "
        "admitted_relation.oid, 'MAINTAIN')"
    ) in sql


def test_maintain_probe_is_guarded_for_supported_postgresql_16() -> None:
    """PostgreSQL 16 must never execute a privilege name introduced in PostgreSQL 17."""
    cursor = MaintainAuthorityCursor()

    _require_rls_application_role(cursor)

    sql = cursor.sql
    version_gate = (
        "CASE WHEN pg_catalog.current_setting('server_version_num')::pg_catalog.int4 "
        "OPERATOR(pg_catalog.>=) 170000 THEN pg_catalog.has_table_privilege("
    )
    assert sql.count("'MAINTAIN'") == 6
    assert sql.count(version_gate) == 6
    assert sql.count("ELSE false END") >= 6
