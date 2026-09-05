# SPDX-License-Identifier: Apache-2.0
"""Regression tests for lifecycle-outbox payload constraint convergence."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pg_llm_batch.context_lifecycle_outbox as lifecycle_outbox


_CANONICAL_PAYLOAD_CONSTRAINT = (
    "ck_llm_context_lifecycle_outbox_payload_canonical_v1"
)
_LEGACY_PAYLOAD_CONSTRAINTS = (
    "ck_llm_context_lifecycle_outbox_tenant_scope",
    "ck_llm_context_lifecycle_outbox_evidence_id",
    "ck_llm_context_lifecycle_outbox_event_type",
    "ck_llm_context_lifecycle_outbox_tenant_sha256",
    "ck_llm_context_lifecycle_outbox_subject_sha256",
    "ck_llm_context_lifecycle_outbox_authority_sha256",
    "ck_llm_context_lifecycle_outbox_origin_sha256",
    "ck_llm_context_lifecycle_outbox_truth_status",
    "ck_llm_context_lifecycle_outbox_provenance_sha256",
    "ck_llm_context_lifecycle_outbox_evidence_sha256",
)
_CANONICAL_PAYLOAD_SPEC = "\n".join(
    (
        "tenant_scope=^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        "evidence_id=^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$",
        "event_type=^[a-z][a-z0-9._:-]{0,127}$",
        "tenant_scope_sha256=^[0-9a-f]{64}$",
        "subject_ref_sha256=^[0-9a-f]{64}$",
        "authority_ref_sha256=^[0-9a-f]{64}$",
        "origin_ref_sha256=^[0-9a-f]{64}$",
        (
            "truth_status="
            "authoritative|observed|inferred|proposed|superseded|rejected"
        ),
        "provenance_ref_sha256=^[0-9a-f]{64}$",
        "evidence_ref_sha256=^[0-9a-f]{64}$",
    )
)
_CANONICAL_PAYLOAD_SHA256 = hashlib.sha256(
    _CANONICAL_PAYLOAD_SPEC.encode("utf-8")
).hexdigest()
_CANONICAL_PAYLOAD_STAMP = (
    "pg-llm-batch:payload-check:v1:sha256=" + _CANONICAL_PAYLOAD_SHA256
)


def test_outbox_payload_semantic_stamp_matches_reviewed_spec() -> None:
    """The stored payload stamp must be reproducible from the reviewed grammar."""
    assert _CANONICAL_PAYLOAD_SHA256 == (
        "29c9507c92caf7bc0891e8d2bd3f1ee57f1394f40c1566b09455b9eb6bb9c98a"
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


def test_outbox_migration_retires_legacy_payload_constraints() -> None:
    """Once canonical payload authority exists, legacy package checks must disappear."""
    migration = Path(lifecycle_outbox.MIGRATION_PATH).read_text(encoding="utf-8")
    canonical_at = migration.index(
        f"COMMENT ON CONSTRAINT {_CANONICAL_PAYLOAD_CONSTRAINT}"
    )
    timestamp_at = migration.index(
        "ck_llm_context_lifecycle_outbox_valid_time_canonical_v1",
        canonical_at,
    )

    last_drop_at = canonical_at
    for legacy_constraint in _LEGACY_PAYLOAD_CONSTRAINTS:
        drop_guard = (
            "IF EXISTS (\n"
            "        SELECT 1\n"
            "        FROM pg_constraint\n"
            "        WHERE conrelid = 'llm_context_lifecycle_outbox'::regclass\n"
            f"          AND conname = '{legacy_constraint}'\n"
            "    ) THEN"
        )
        drop_at = migration.index(drop_guard, last_drop_at)
        drop_constraint_at = migration.index(
            f"DROP CONSTRAINT {legacy_constraint}",
            drop_at,
        )
        assert canonical_at < drop_at < drop_constraint_at < timestamp_at
        last_drop_at = drop_constraint_at


def test_outbox_payload_constraint_remains_package_docker_byte_identical() -> None:
    """Packaged and container migrations must carry the same payload authority."""
    package_sql = Path(lifecycle_outbox.MIGRATION_PATH).read_bytes()
    docker_sql = Path("docker/postgres/init/04_context_lifecycle_outbox.sql").read_bytes()
    assert package_sql == docker_sql
