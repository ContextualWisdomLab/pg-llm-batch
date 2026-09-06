# SPDX-License-Identifier: Apache-2.0
"""Regression contract for final lifecycle-outbox relation authority."""

from __future__ import annotations

from pathlib import Path

import pg_llm_batch.context_lifecycle_outbox as lifecycle_outbox


def test_final_row_admission_reproves_logged_ordinary_public_relation() -> None:
    """Migration 0009 must reject post-0008 relation durability/topology drift."""
    package_path = lifecycle_outbox._ROW_ADMISSION_AUTHORITY_MIGRATION_PATH
    docker_path = (
        Path(__file__).parents[1]
        / "docker"
        / "postgres"
        / "init"
        / "05_context_lifecycle_outbox_row_admission_authority.sql"
    )
    package_sql = Path(package_path).read_text(encoding="utf-8")
    docker_sql = docker_path.read_text(encoding="utf-8")

    assert package_sql == docker_sql
    relation_guard_at = package_sql.index("FROM pg_catalog.pg_class AS admission_relation")
    rls_guard_at = package_sql.index("-- RLS is final row-admission authority")
    assert relation_guard_at < rls_guard_at

    relation_block = package_sql[relation_guard_at:rls_guard_at]
    assert "JOIN pg_catalog.pg_namespace AS admission_namespace" in relation_block
    assert "admission_relation.oid =" in relation_block
    assert "'public.llm_context_lifecycle_outbox'::pg_catalog.regclass" in relation_block
    assert "admission_relation.relkind OPERATOR(pg_catalog.=) 'r'" in relation_block
    assert "admission_relation.relpersistence OPERATOR(pg_catalog.=) 'p'" in relation_block
    assert "admission_namespace.nspname OPERATOR(pg_catalog.=) 'public'" in relation_block
    assert "FROM pg_catalog.pg_inherits AS inheritance_edge" in relation_block
    assert "inheritance_edge.inhrelid =" in relation_block
    assert "inheritance_edge.inhparent =" in relation_block
