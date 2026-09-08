# SPDX-License-Identifier: Apache-2.0
"""Regression tests for lifecycle-outbox idempotency-key convergence."""

from __future__ import annotations

from pathlib import Path

import pg_llm_batch.context_lifecycle_outbox as lifecycle_outbox


_CANONICAL_UNIQUE_CONSTRAINT = "uq_llm_context_lifecycle_outbox_tenant_evidence"


def _canonical_guard() -> str:
    """Return the exact catalog predicate for the runtime replay arbiter."""
    return (
        "IF NOT EXISTS (\n"
        "        SELECT 1\n"
        "        FROM pg_constraint\n"
        "        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass\n"
        f"          AND conname = '{_CANONICAL_UNIQUE_CONSTRAINT}'\n"
        "          AND contype = 'u'\n"
        "          AND convalidated\n"
        "          AND NOT condeferrable\n"
        "          AND conkey = ARRAY[\n"
        "              (SELECT attnum::smallint FROM pg_attribute\n"
        "               WHERE attrelid = 'llm_context_lifecycle_outbox'::regclass\n"
        "                 AND attname = 'tenant_scope' AND NOT attisdropped),\n"
        "              (SELECT attnum::smallint FROM pg_attribute\n"
        "               WHERE attrelid = 'llm_context_lifecycle_outbox'::regclass\n"
        "                 AND attname = 'evidence_id' AND NOT attisdropped)\n"
        "          ]\n"
        "    ) THEN"
    )


def test_migration_converges_nondeferrable_tenant_evidence_unique_constraint() -> None:
    """A pre-existing table must acquire the exact UPSERT arbiter after migration."""
    migration = Path(lifecycle_outbox.MIGRATION_PATH).read_text(encoding="utf-8")
    create_start = migration.index(
        "CREATE TABLE IF NOT EXISTS public.llm_context_lifecycle_outbox"
    )
    create_end = migration.index("\n    );", create_start)

    canonical_guard = _canonical_guard()
    guard_at = migration.index(canonical_guard, create_end)

    repair_guard = (
        "IF EXISTS (\n"
        "            SELECT 1\n"
        "            FROM pg_constraint\n"
        "            WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass\n"
        f"              AND conname = '{_CANONICAL_UNIQUE_CONSTRAINT}'\n"
        "        ) THEN"
    )
    repair_at = migration.index(repair_guard, guard_at)
    drop_at = migration.index(
        f"DROP CONSTRAINT {_CANONICAL_UNIQUE_CONSTRAINT}", repair_at
    )
    add_at = migration.index(
        f"ADD CONSTRAINT {_CANONICAL_UNIQUE_CONSTRAINT}", drop_at
    )
    unique_at = migration.index("UNIQUE (tenant_scope, evidence_id)", add_at)

    assert create_end < guard_at < repair_at < drop_at < add_at < unique_at


def test_repaired_replay_arbiter_is_post_verified_before_migration_success() -> None:
    """The exact UNIQUE admission predicate must repeat after repair."""
    migration = Path(lifecycle_outbox.MIGRATION_PATH).read_text(encoding="utf-8")
    canonical_guard = _canonical_guard()
    admission_at = migration.index(canonical_guard)
    add_at = migration.index(
        f"ADD CONSTRAINT {_CANONICAL_UNIQUE_CONSTRAINT}", admission_at
    )
    verification_at = migration.index(canonical_guard, add_at + 1)
    raise_at = migration.index(
        "RAISE EXCEPTION 'lifecycle outbox replay arbiter failed canonical verification'",
        verification_at,
    )

    assert admission_at < add_at < verification_at < raise_at


def test_runtime_upsert_requires_the_converged_tenant_evidence_arbiter() -> None:
    """The durable replay path must keep using the key migration 0008 converges."""
    source = Path(lifecycle_outbox.__file__).read_text(encoding="utf-8")
    assert "ON CONFLICT (tenant_scope, evidence_id) DO NOTHING" in source
