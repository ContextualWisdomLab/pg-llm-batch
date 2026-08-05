# SPDX-License-Identifier: Apache-2.0
"""Schema contracts for tenant-scoped durable lifecycle isolation."""

from __future__ import annotations

from pathlib import Path

from pg_llm_batch import db


def _canonical_schema() -> str:
    """Return the packaged canonical lifecycle schema text."""
    return Path(db.SCHEMA_PATH).read_text(encoding="utf-8")


def _deployed_schema() -> str:
    """Return the PostgreSQL image initialization schema text."""
    repository_root = Path(__file__).resolve().parents[1]
    return (repository_root / "docker/postgres/init/02_schema.sql").read_text(
        encoding="utf-8"
    )


def test_lifecycle_identity_is_tenant_qualified() -> None:
    """Current-state rows use a trusted tenant-qualified business identity."""
    schema = _canonical_schema()

    assert "tenant_scope TEXT NOT NULL DEFAULT 'standalone'" in schema
    assert "CONSTRAINT ck_llm_remote_batch_jobs_tenant_scope" in schema
    assert "tenant_scope ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'" in schema
    assert "CONSTRAINT uq_llm_remote_batch_jobs_tenant_endpoint_id" in schema
    assert "UNIQUE (tenant_scope, endpoint_alias, remote_batch_id)" in schema
    assert "UNIQUE (endpoint_alias, remote_batch_id)" not in schema
    assert "idx_llm_remote_batch_jobs_tenant_status_observed" in schema


def test_legacy_lifecycle_rows_are_backfilled_without_deletion() -> None:
    """The idempotent migration maps existing rows to standalone deterministically."""
    schema = _canonical_schema()

    assert (
        "ALTER TABLE llm_remote_batch_jobs\n"
        "    ADD COLUMN IF NOT EXISTS tenant_scope TEXT;"
    ) in schema
    assert (
        "UPDATE llm_remote_batch_jobs\n"
        "SET tenant_scope = 'standalone'\n"
        "WHERE tenant_scope IS NULL;"
    ) in schema
    assert "ALTER COLUMN tenant_scope SET DEFAULT 'standalone'" in schema
    assert "ALTER COLUMN tenant_scope SET NOT NULL" in schema
    assert "DROP CONSTRAINT uq_llm_remote_batch_jobs_endpoint_id" in schema
    assert "DELETE FROM llm_remote_batch_jobs" not in schema.upper()
    assert "TRUNCATE llm_remote_batch_jobs" not in schema.upper()


def test_rls_owner_transition_is_atomic_for_psql_reapplication() -> None:
    """Reapplying the SQL file cannot expose an owner-bypass window between statements."""
    schema = _canonical_schema()
    migration_start = schema.index(
        "-- Reapplying the schema may occur after FORCE RLS was installed."
    )
    migration_end = schema.index(
        "DROP INDEX IF EXISTS idx_llm_remote_batch_jobs_status_observed;"
    )
    migration = schema[migration_start:migration_end]

    assert "DISABLE ROW LEVEL SECURITY" not in migration
    atomic_start = migration.index("DO $$\nBEGIN")
    atomic_end = migration.index("END $$;", atomic_start) + len("END $$;")
    atomic_transition = migration[atomic_start:atomic_end]
    assert "NO FORCE ROW LEVEL SECURITY" in atomic_transition
    assert "ADD COLUMN IF NOT EXISTS tenant_scope TEXT" in atomic_transition
    assert "SET tenant_scope = 'standalone'" in atomic_transition
    assert "ALTER COLUMN tenant_scope SET NOT NULL" in atomic_transition
    assert "FORCE ROW LEVEL SECURITY" in atomic_transition
    assert atomic_transition.index("NO FORCE ROW LEVEL SECURITY") < atomic_transition.index(
        "SET tenant_scope = 'standalone'"
    )
    assert atomic_transition.index("SET tenant_scope = 'standalone'") < atomic_transition.index(
        "FORCE ROW LEVEL SECURITY"
    )


def test_lifecycle_row_security_is_forced_and_default_deny() -> None:
    """Missing transaction tenant context cannot expose or mutate lifecycle rows."""
    schema = _canonical_schema()
    policy_expression = (
        "tenant_scope = current_setting('pg_llm_batch.tenant_scope', true)"
    )

    assert "DROP POLICY IF EXISTS plc_llm_remote_batch_jobs_tenant_scope" in schema
    assert "CREATE POLICY plc_llm_remote_batch_jobs_tenant_scope" in schema
    assert "ON llm_remote_batch_jobs\n    TO PUBLIC" in schema
    assert schema.count(policy_expression) == 2
    assert "ALTER TABLE llm_remote_batch_jobs ENABLE ROW LEVEL SECURITY" in schema
    assert "ALTER TABLE llm_remote_batch_jobs FORCE ROW LEVEL SECURITY" in schema
    assert "COALESCE(current_setting" not in schema


def test_postgres_image_uses_the_exact_canonical_schema() -> None:
    """Container initialization cannot drift from tenant isolation migrations."""
    assert _deployed_schema() == _canonical_schema()
