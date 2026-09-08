# SPDX-License-Identifier: Apache-2.0
"""Regression contract for final lifecycle-outbox column authority."""

from __future__ import annotations

from pathlib import Path

import pg_llm_batch.context_lifecycle_outbox as lifecycle_outbox


def test_final_row_admission_reproves_complete_column_catalog_identity() -> None:
    """Migration 0009 must reject post-0008 column-shape drift, not trust history."""
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
    assert "AS expected(attname, atttypid, attnotnull, atthasdef)" in package_sql
    for column_name in (
        "context_outbox_uuid",
        "tenant_scope",
        "evidence_id",
        "event_type",
        "tenant_scope_sha256",
        "subject_ref_sha256",
        "authority_ref_sha256",
        "origin_ref_sha256",
        "truth_status",
        "valid_time",
        "system_time",
        "provenance_ref_sha256",
        "evidence_ref_sha256",
        "created_at",
    ):
        assert f"('{column_name}'," in package_sql
    assert "actual.attcollation IS DISTINCT FROM" in package_sql
    assert "actual.attnotnull IS DISTINCT FROM expected.attnotnull" in package_sql
    assert "actual.atthasdef IS DISTINCT FROM expected.atthasdef" in package_sql
    assert "actual.attgenerated OPERATOR(pg_catalog.<>) ''" in package_sql
    assert "actual.attidentity OPERATOR(pg_catalog.<>) ''" in package_sql
    assert "pg_catalog.count(*)" in package_sql
    assert "OPERATOR(pg_catalog.<>) 14" in package_sql
    assert "dropped_column.attisdropped" in package_sql
