# SPDX-License-Identifier: Apache-2.0
"""Regression tests for lifecycle-outbox CHECK-constraint catalog authority."""

from __future__ import annotations

from pathlib import Path

import pg_llm_batch.context_lifecycle_outbox as lifecycle_outbox


_CANONICAL_TIMESTAMP_CONSTRAINTS = {
    "ck_llm_context_lifecycle_outbox_valid_time_canonical_v1": (
        "pg-llm-batch:timestamp-check:v1:"
        "sha256=32c3d6803b1c13e584230dcb0652bf8f932ee3ee256109dd25ed7d07e11d0261"
    ),
    "ck_llm_context_lifecycle_outbox_system_time_canonical_v1": (
        "pg-llm-batch:timestamp-check:v1:"
        "sha256=490658f6948499784f4c86d642ff38a680821c50d31ad2627d6af10e02722ede"
    ),
}


def test_timestamp_constraint_name_alone_is_not_canonical_authority() -> None:
    """A same-name invalid or unstamped constraint must be repaired, not trusted."""
    migration = Path(lifecycle_outbox.MIGRATION_PATH).read_text(encoding="utf-8")

    for constraint_name, semantic_stamp in _CANONICAL_TIMESTAMP_CONSTRAINTS.items():
        canonical_guard = (
            "IF NOT EXISTS (\n"
            "        SELECT 1\n"
            "        FROM pg_constraint\n"
            "        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass\n"
            f"          AND conname = '{constraint_name}'\n"
            "          AND contype = 'c'\n"
            "          AND convalidated\n"
            "          AND NOT connoinherit\n"
            "          AND pg_catalog.obj_description(oid, 'pg_constraint') =\n"
            f"              '{semantic_stamp}'\n"
            "    ) THEN"
        )
        guard_at = migration.index(canonical_guard)

        repair_guard = (
            "IF EXISTS (\n"
            "            SELECT 1\n"
            "            FROM pg_constraint\n"
            "            WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass\n"
            f"              AND conname = '{constraint_name}'\n"
            "        ) THEN"
        )
        repair_at = migration.index(repair_guard, guard_at)
        drop_at = migration.index(
            f"DROP CONSTRAINT {constraint_name}",
            repair_at,
        )
        add_at = migration.index(
            f"ADD CONSTRAINT {constraint_name}",
            drop_at,
        )
        comment_at = migration.index(
            f"COMMENT ON CONSTRAINT {constraint_name}",
            add_at,
        )
        stamp_at = migration.index(f"IS '{semantic_stamp}';", comment_at)
        assert guard_at < repair_at < drop_at < add_at < comment_at < stamp_at
