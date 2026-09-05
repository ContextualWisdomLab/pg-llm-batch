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
    drop_at = migration.index(f"DROP INDEX {_INDEX_NAME};", collision_guard_at)
    create_at = migration.index(f"CREATE INDEX {_INDEX_NAME}", drop_at)
    assert guard_at < collision_guard_at < drop_at < create_at
