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


def _tenant_migration(schema: str) -> str:
    """Return the bounded legacy-to-tenant migration section."""
    migration_start = schema.index(
        "-- Reapplying the schema may occur after FORCE RLS was installed."
    )
    migration_end = schema.index(
        "DROP INDEX IF EXISTS idx_llm_remote_batch_jobs_status_observed;"
    )
    return schema[migration_start:migration_end]


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
    migration = _tenant_migration(schema)

    assert "ADD COLUMN IF NOT EXISTS tenant_scope TEXT" in migration
    assert "SET tenant_scope = 'standalone'" in migration
    assert "WHERE tenant_scope IS NULL" in migration
    assert "ALTER COLUMN tenant_scope SET DEFAULT 'standalone'" in migration
    assert "ALTER COLUMN tenant_scope SET NOT NULL" in migration
    assert "DROP CONSTRAINT uq_llm_remote_batch_jobs_endpoint_id" in migration
    assert "DELETE FROM llm_remote_batch_jobs" not in schema.upper()
    assert "TRUNCATE llm_remote_batch_jobs" not in schema.upper()


def test_rls_owner_transition_is_atomic_for_psql_reapplication() -> None:
    """Reapplying SQL cannot commit an enabled/forced RLS transition piecemeal."""
    migration = _tenant_migration(_canonical_schema())

    assert "DISABLE ROW LEVEL SECURITY" not in migration
    atomic_start = migration.index("DO $$\nBEGIN")
    atomic_end = migration.index("END $$;", atomic_start) + len("END $$;")
    atomic_transition = migration[atomic_start:atomic_end]
    enable_statement = "ALTER TABLE llm_remote_batch_jobs ENABLE ROW LEVEL SECURITY;"
    force_statement = "ALTER TABLE llm_remote_batch_jobs FORCE ROW LEVEL SECURITY;"

    assert "NO FORCE ROW LEVEL SECURITY" in atomic_transition
    assert "ADD COLUMN IF NOT EXISTS tenant_scope TEXT" in atomic_transition
    assert "SET tenant_scope = 'standalone'" in atomic_transition
    assert "ALTER COLUMN tenant_scope SET NOT NULL" in atomic_transition
    assert enable_statement in atomic_transition
    assert force_statement in atomic_transition
    assert atomic_transition.index("NO FORCE ROW LEVEL SECURITY") < atomic_transition.index(
        "SET tenant_scope = 'standalone'"
    )
    assert atomic_transition.index(
        "SET tenant_scope = 'standalone'"
    ) < atomic_transition.index(enable_statement)
    assert atomic_transition.index(enable_statement) < atomic_transition.rindex(
        force_statement
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
