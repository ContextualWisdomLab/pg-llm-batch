# SPDX-License-Identifier: Apache-2.0
"""Regression tests for lifecycle-outbox operational-index convergence."""

from __future__ import annotations

from pathlib import Path

import pg_llm_batch.context_lifecycle_outbox as lifecycle_outbox


_INDEX_NAME = "idx_llm_context_lifecycle_outbox_tenant_created"


def test_outbox_migration_does_not_trust_operational_index_name_alone() -> None:
    """A same-name wrong or invalid index must be repaired rather than accepted."""
    migration = Path(lifecycle_outbox.MIGRATION_PATH).read_text(encoding="utf-8")

    assert f"CREATE INDEX IF NOT EXISTS {_INDEX_NAME}" not in migration
    guard = (
        "IF NOT EXISTS (\n"
        "        SELECT 1\n"
        "        FROM pg_index AS operational_index\n"
        "        JOIN pg_class AS index_relation\n"
        "          ON index_relation.oid = operational_index.indexrelid\n"
        "        JOIN pg_am AS index_method\n"
        "          ON index_method.oid = index_relation.relam\n"
        "        WHERE operational_index.indrelid =\n"
        "              'llm_context_lifecycle_outbox'::regclass\n"
        f"          AND index_relation.relname = '{_INDEX_NAME}'\n"
        "          AND index_relation.relnamespace = 'public'::regnamespace\n"
        "          AND index_method.amname = 'btree'\n"
        "          AND operational_index.indisvalid\n"
        "          AND operational_index.indisready\n"
        "          AND operational_index.indislive\n"
        "          AND NOT operational_index.indisunique\n"
        "          AND operational_index.indnkeyatts = 2\n"
        "          AND operational_index.indnatts = 2\n"
        "          AND operational_index.indexprs IS NULL\n"
        "          AND operational_index.indpred IS NULL\n"
        "          AND operational_index.indkey[0] = (\n"
        "              SELECT attnum\n"
        "              FROM pg_attribute\n"
        "              WHERE attrelid = 'llm_context_lifecycle_outbox'::regclass\n"
        "                AND attname = 'tenant_scope'\n"
        "                AND NOT attisdropped\n"
        "          )\n"
        "          AND operational_index.indkey[1] = (\n"
        "              SELECT attnum\n"
        "              FROM pg_attribute\n"
        "              WHERE attrelid = 'llm_context_lifecycle_outbox'::regclass\n"
        "                AND attname = 'created_at'\n"
        "                AND NOT attisdropped\n"
        "          )\n"
        "    ) THEN"
    )
    guard_at = migration.index(guard)
    collision_guard_at = migration.index(
        "IF pg_catalog.to_regclass(\n"
        f"            'public.{_INDEX_NAME}'\n"
        "        ) IS NOT NULL THEN",
        guard_at,
    )
    collision_raise_at = migration.index(
        "RAISE EXCEPTION 'lifecycle outbox operational index name collision'",
        collision_guard_at,
    )
    drop_at = migration.index(f"DROP INDEX public.{_INDEX_NAME};", collision_raise_at)
    create_at = migration.index(f"CREATE INDEX {_INDEX_NAME}", drop_at)
    assert guard_at < collision_guard_at < collision_raise_at < drop_at < create_at


def test_outbox_operational_index_binds_key_semantics_not_only_column_numbers() -> None:
    """Index collation, opclass, and B-tree options are part of canonical identity."""
    migration = Path(lifecycle_outbox.MIGRATION_PATH).read_text(encoding="utf-8")
    guard_at = migration.index(
        "IF NOT EXISTS (\n"
        "        SELECT 1\n"
        "        FROM pg_index AS operational_index"
    )
    guard_end = migration.index(") THEN", guard_at)
    guard = migration[guard_at:guard_end]

    assert "operational_index.indcollation[0] = (" in guard
    assert "attname = 'tenant_scope'" in guard
    assert "operational_index.indcollation[1] = 0" in guard
    assert "operational_index.indclass[0] = (" in guard
    assert "opcdefault" in guard
    assert "opcintype = 'text'::regtype" in guard
    assert "operational_index.indclass[1] = (" in guard
    assert "opcintype = 'timestamptz'::regtype" in guard
    assert "operational_index.indoption[0] = 0" in guard
    assert "operational_index.indoption[1] = 0" in guard


def test_outbox_operational_index_is_post_verified_after_repair() -> None:
    """Post-repair verification must repeat the exact admission predicate."""
    migration = Path(lifecycle_outbox.MIGRATION_PATH).read_text(encoding="utf-8")
    guard_prefix = (
        "IF NOT EXISTS (\n"
        "        SELECT 1\n"
        "        FROM pg_index AS operational_index"
    )
    admission_at = migration.index(guard_prefix)
    admission_end = migration.index("    ) THEN", admission_at) + len("    ) THEN")
    create_at = migration.index(f"CREATE INDEX {_INDEX_NAME}", admission_end)
    verification_at = migration.index(guard_prefix, create_at + 1)
    verification_end = migration.index("    ) THEN", verification_at) + len("    ) THEN")
    raise_at = migration.index(
        "RAISE EXCEPTION 'lifecycle outbox operational index failed canonical verification'",
        verification_end,
    )

    assert create_at < verification_at < verification_end < raise_at
    assert migration[admission_at:admission_end] == migration[
        verification_at:verification_end
    ]
