# SPDX-License-Identifier: Apache-2.0
"""Regression tests for lifecycle-outbox migration convergence."""

from __future__ import annotations

from pathlib import Path

import pg_llm_batch.context_lifecycle_outbox as lifecycle_outbox


_TIMESTAMP_CONSTRAINTS = (
    "ck_llm_context_lifecycle_outbox_valid_time",
    "ck_llm_context_lifecycle_outbox_system_time",
)


def test_outbox_migration_reapplies_timestamp_identity_constraints() -> None:
    """Reapplying migration 0008 must tighten an already-created outbox table."""
    migration = Path(lifecycle_outbox.MIGRATION_PATH).read_text(encoding="utf-8")
    create_start = migration.index(
        "CREATE TABLE IF NOT EXISTS llm_context_lifecycle_outbox"
    )
    create_end = migration.index("\n    );", create_start)
    create_block = migration[create_start:create_end]

    for constraint in _TIMESTAMP_CONSTRAINTS:
        assert constraint not in create_block
        drop_clause = f"DROP CONSTRAINT IF EXISTS {constraint}"
        add_clause = f"ADD CONSTRAINT {constraint}"
        drop_at = migration.index(drop_clause, create_end)
        add_at = migration.index(add_clause, drop_at)
        assert create_end < drop_at < add_at

    assert migration.count("valid_time !~ '[.]000000Z$'") == 1
    assert migration.count("system_time !~ '[.]000000Z$'") == 1
    assert migration.count("AT TIME ZONE 'UTC'") == 2
