# SPDX-License-Identifier: Apache-2.0
"""Regression tests for lifecycle-outbox migration convergence."""

from __future__ import annotations

from pathlib import Path

import pg_llm_batch.context_lifecycle_outbox as lifecycle_outbox


_TIMESTAMP_CONSTRAINTS = (
    (
        "ck_llm_context_lifecycle_outbox_valid_time",
        "ck_llm_context_lifecycle_outbox_valid_time_canonical_v1",
    ),
    (
        "ck_llm_context_lifecycle_outbox_system_time",
        "ck_llm_context_lifecycle_outbox_system_time_canonical_v1",
    ),
)


def test_outbox_migration_reapplies_timestamp_identity_constraints_once() -> None:
    """Migration 0008 must converge stale checks without relocking every reapply."""
    migration = Path(lifecycle_outbox.MIGRATION_PATH).read_text(encoding="utf-8")
    create_start = migration.index(
        "CREATE TABLE IF NOT EXISTS llm_context_lifecycle_outbox"
    )
    create_end = migration.index("\n    );", create_start)
    create_block = migration[create_start:create_end]

    for legacy_constraint, canonical_constraint in _TIMESTAMP_CONSTRAINTS:
        assert legacy_constraint not in create_block
        assert canonical_constraint not in create_block

        add_guard = (
            "IF NOT EXISTS (\n"
            "        SELECT 1\n"
            "        FROM pg_constraint\n"
            "        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass\n"
            f"          AND conname = '{canonical_constraint}'\n"
            "    ) THEN"
        )
        add_at = migration.index(add_guard, create_end)
        constraint_at = migration.index(
            f"ADD CONSTRAINT {canonical_constraint}", add_at
        )
        assert add_at < constraint_at

        drop_guard = (
            "IF EXISTS (\n"
            "        SELECT 1\n"
            "        FROM pg_constraint\n"
            "        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass\n"
            f"          AND conname = '{legacy_constraint}'\n"
            "    ) THEN"
        )
        drop_at = migration.index(drop_guard, constraint_at)
        drop_constraint_at = migration.index(
            f"DROP CONSTRAINT {legacy_constraint}", drop_at
        )
        assert constraint_at < drop_at < drop_constraint_at

    assert migration.count("valid_time !~ '[.]000000Z$'") == 1
    assert migration.count("system_time !~ '[.]000000Z$'") == 1
    assert migration.count("AT TIME ZONE 'UTC'") == 2
