# SPDX-License-Identifier: Apache-2.0
"""Regression tests for lifecycle-outbox structural schema admission."""

from __future__ import annotations

from pathlib import Path

import pg_llm_batch.context_lifecycle_outbox as lifecycle_outbox


def test_outbox_migration_fails_closed_on_incompatible_existing_columns() -> None:
    """CREATE IF NOT EXISTS must not silently admit a structurally stale table."""
    migration = Path(lifecycle_outbox.MIGRATION_PATH).read_text(encoding="utf-8")
    create_at = migration.index(
        "CREATE TABLE IF NOT EXISTS public.llm_context_lifecycle_outbox"
    )
    create_end = migration.index("\n    );", create_at)
    guard_at = migration.index(
        "RAISE EXCEPTION 'lifecycle outbox structural schema mismatch';",
        create_end,
    )
    payload_at = migration.index(
        "ck_llm_context_lifecycle_outbox_payload_canonical_v1",
        guard_at,
    )

    assert create_end < guard_at < payload_at
    guard_block = migration[create_end:guard_at]
    for column_name, type_name, has_default in (
        ("context_outbox_uuid", "uuid", True),
        ("tenant_scope", "text", True),
        ("evidence_id", "text", False),
        ("event_type", "text", False),
        ("tenant_scope_sha256", "text", False),
        ("subject_ref_sha256", "text", False),
        ("authority_ref_sha256", "text", False),
        ("origin_ref_sha256", "text", False),
        ("truth_status", "text", False),
        ("valid_time", "text", False),
        ("system_time", "text", False),
        ("provenance_ref_sha256", "text", False),
        ("evidence_ref_sha256", "text", False),
        ("created_at", "timestamptz", True),
    ):
        assert f"('{column_name}', '{type_name}'::regtype, true, {str(has_default).lower()})" in guard_block

    assert "actual.attnotnull IS DISTINCT FROM expected.attnotnull" in guard_block
    assert "actual.atthasdef IS DISTINCT FROM expected.atthasdef" in guard_block
    assert "actual.attgenerated <> ''" in guard_block
    assert "actual.attidentity <> ''" in guard_block


def test_outbox_migration_rejects_noncanonical_column_collation() -> None:
    """Durable text identity must retain the type-default collation authority."""
    migration = Path(lifecycle_outbox.MIGRATION_PATH).read_text(encoding="utf-8")
    guard_at = migration.index(
        "RAISE EXCEPTION 'lifecycle outbox structural schema mismatch';"
    )
    guard_block = migration[:guard_at]

    assert "actual.attcollation IS DISTINCT FROM (" in guard_block
    assert "SELECT typcollation" in guard_block
    assert "FROM pg_type" in guard_block
    assert "WHERE oid = expected.atttypid" in guard_block


def test_outbox_migration_rejects_undeclared_live_columns() -> None:
    """The durable row shape must not silently gain package-undeclared columns."""
    migration = Path(lifecycle_outbox.MIGRATION_PATH).read_text(encoding="utf-8")
    guard_at = migration.index(
        "RAISE EXCEPTION 'lifecycle outbox structural schema mismatch';"
    )
    guard_block = migration[:guard_at]

    assert "SELECT count(*)" in guard_block
    assert "actual.attnum > 0" in guard_block
    assert "NOT actual.attisdropped" in guard_block
    assert ") <> 14 OR EXISTS (" in guard_block


def test_outbox_migration_requires_primary_key_on_context_uuid() -> None:
    """The durable surrogate identifier must retain a concrete nondeferrable PK."""
    migration = Path(lifecycle_outbox.MIGRATION_PATH).read_text(encoding="utf-8")
    guard_at = migration.index(
        "RAISE EXCEPTION 'lifecycle outbox structural schema mismatch';"
    )
    guard_block = migration[:guard_at]

    assert "AND contype = 'p'" in guard_block
    assert "AND convalidated" in guard_block
    assert "AND NOT condeferrable" in guard_block
    assert "attname = 'context_outbox_uuid'" in guard_block


def test_outbox_migration_requires_canonical_runtime_defaults() -> None:
    """Omitted runtime columns must resolve through the reviewed default authority."""
    migration = Path(lifecycle_outbox.MIGRATION_PATH).read_text(encoding="utf-8")
    guard_at = migration.index(
        "RAISE EXCEPTION 'lifecycle outbox structural schema mismatch';"
    )
    guard_block = migration[:guard_at]

    assert "actual.attname = 'context_outbox_uuid'" in guard_block
    assert "pg_catalog.pg_get_expr(defaults.adbin, defaults.adrelid, false) NOT IN (" in guard_block
    assert "'uuid_generate_v4()'," in guard_block
    assert "'public.uuid_generate_v4()'" in guard_block
    assert "actual.attname = 'tenant_scope'" in guard_block
    assert "<> '''standalone''::text'" in guard_block
    assert "actual.attname = 'created_at'" in guard_block
    assert "<> 'now()'" in guard_block
