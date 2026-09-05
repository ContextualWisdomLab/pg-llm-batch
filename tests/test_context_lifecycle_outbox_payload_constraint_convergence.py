# SPDX-License-Identifier: Apache-2.0
"""Regression tests for lifecycle-outbox payload constraint convergence."""

from __future__ import annotations

from pathlib import Path

import pg_llm_batch.context_lifecycle_outbox as lifecycle_outbox


_CANONICAL_PAYLOAD_CONSTRAINT = (
    "ck_llm_context_lifecycle_outbox_payload_canonical_v1"
)
_CANONICAL_PAYLOAD_STAMP = (
    "pg-llm-batch:payload-check:v1:"
    "sha256=1ff07a511e201295d934dedf36e6d9f6a2362c4acb98be582f9b8fa3a1da3c7d"
)


def test_outbox_migration_converges_payload_value_contract_after_create() -> None:
    """Existing tables must gain the canonical value contract after CREATE skips."""
    migration = Path(lifecycle_outbox.MIGRATION_PATH).read_text(encoding="utf-8")
    create_start = migration.index(
        "CREATE TABLE IF NOT EXISTS public.llm_context_lifecycle_outbox"
    )
    create_end = migration.index("\n    );", create_start)

    guard = (
        "IF NOT EXISTS (\n"
        "        SELECT 1\n"
        "        FROM pg_constraint\n"
        "        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass\n"
        f"          AND conname = '{_CANONICAL_PAYLOAD_CONSTRAINT}'\n"
        "          AND contype = 'c'\n"
        "          AND convalidated\n"
        "          AND NOT connoinherit\n"
        "          AND pg_catalog.obj_description(oid, 'pg_constraint') =\n"
        f"              '{_CANONICAL_PAYLOAD_STAMP}'\n"
        "    ) THEN"
    )
    guard_at = migration.index(guard, create_end)
    add_at = migration.index(
        f"ADD CONSTRAINT {_CANONICAL_PAYLOAD_CONSTRAINT}", guard_at
    )
    comment_at = migration.index(
        f"COMMENT ON CONSTRAINT {_CANONICAL_PAYLOAD_CONSTRAINT}", add_at
    )

    assert create_end < guard_at < add_at < comment_at
    payload_block = migration[add_at:comment_at]
    for required_fragment in (
        "tenant_scope ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'",
        "evidence_id ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'",
        "event_type ~ '^[a-z][a-z0-9._:-]{0,127}$'",
        "tenant_scope_sha256 ~ '^[0-9a-f]{64}$'",
        "subject_ref_sha256 ~ '^[0-9a-f]{64}$'",
        "authority_ref_sha256 ~ '^[0-9a-f]{64}$'",
        "origin_ref_sha256 ~ '^[0-9a-f]{64}$'",
        "truth_status IN (",
        "provenance_ref_sha256 ~ '^[0-9a-f]{64}$'",
        "evidence_ref_sha256 ~ '^[0-9a-f]{64}$'",
    ):
        assert required_fragment in payload_block


def test_outbox_payload_constraint_remains_package_docker_byte_identical() -> None:
    """Packaged and container migrations must carry the same payload authority."""
    package_sql = Path(lifecycle_outbox.MIGRATION_PATH).read_bytes()
    docker_sql = Path("docker/postgres/init/04_context_lifecycle_outbox.sql").read_bytes()
    assert package_sql == docker_sql
