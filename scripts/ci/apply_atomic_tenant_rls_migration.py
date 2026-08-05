# SPDX-License-Identifier: Apache-2.0
"""Apply the reviewed atomic tenant RLS migration to both schema copies.

This temporary exact-head helper exists only to turn the committed RED schema
contract green.  The verification workflow removes it before publishing the
final feature head.
"""

from __future__ import annotations

from pathlib import Path

CANONICAL_SCHEMA_PATH = Path("pg_llm_batch/schema.sql")
DEPLOYED_SCHEMA_PATH = Path("docker/postgres/init/02_schema.sql")
START_MARKER = "-- Reapplying the schema may occur after FORCE RLS was installed."
END_MARKER = "DROP INDEX IF EXISTS idx_llm_remote_batch_jobs_status_observed;"

ATOMIC_MIGRATION = """-- Reapplying the schema may occur after FORCE RLS was installed. psql
-- can autocommit individual statements, so the owner transition, legacy-row
-- backfill, and constraint migration execute inside one anonymous block. If any
-- operation fails, PostgreSQL rolls the entire statement back and FORCE RLS is
-- never left disabled between committed statements.
DO $$
BEGIN
    ALTER TABLE llm_remote_batch_jobs NO FORCE ROW LEVEL SECURITY;
    ALTER TABLE llm_remote_batch_jobs
        ADD COLUMN IF NOT EXISTS tenant_scope TEXT;
    UPDATE llm_remote_batch_jobs
    SET tenant_scope = 'standalone'
    WHERE tenant_scope IS NULL;
    ALTER TABLE llm_remote_batch_jobs
        ALTER COLUMN tenant_scope SET DEFAULT 'standalone';
    ALTER TABLE llm_remote_batch_jobs
        ALTER COLUMN tenant_scope SET NOT NULL;

    IF EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_llm_remote_batch_jobs_endpoint_id'
          AND conrelid = 'llm_remote_batch_jobs'::regclass
    ) THEN
        ALTER TABLE llm_remote_batch_jobs
            DROP CONSTRAINT uq_llm_remote_batch_jobs_endpoint_id;
    END IF;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_llm_remote_batch_jobs_tenant_scope'
          AND conrelid = 'llm_remote_batch_jobs'::regclass
    ) THEN
        ALTER TABLE llm_remote_batch_jobs
            ADD CONSTRAINT ck_llm_remote_batch_jobs_tenant_scope
            CHECK (
                tenant_scope ~ '^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$'
            ) NOT VALID;
    END IF;
    ALTER TABLE llm_remote_batch_jobs
        VALIDATE CONSTRAINT ck_llm_remote_batch_jobs_tenant_scope;

    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_llm_remote_batch_jobs_tenant_endpoint_id'
          AND conrelid = 'llm_remote_batch_jobs'::regclass
    ) THEN
        ALTER TABLE llm_remote_batch_jobs
            ADD CONSTRAINT uq_llm_remote_batch_jobs_tenant_endpoint_id
            UNIQUE (tenant_scope, endpoint_alias, remote_batch_id);
    END IF;

    ALTER TABLE llm_remote_batch_jobs FORCE ROW LEVEL SECURITY;
END $$;

"""


def apply_atomic_migration(schema: str) -> str:
    """Replace the unsafe multi-statement transition with one atomic block."""
    start = schema.index(START_MARKER)
    end = schema.index(END_MARKER, start)
    repaired = schema[:start] + ATOMIC_MIGRATION + schema[end:]
    migration = repaired[start : repaired.index(END_MARKER, start)]
    if "DISABLE ROW LEVEL SECURITY" in migration:
        raise RuntimeError("owner-bypass migration still disables row security")
    required_tokens = (
        "NO FORCE ROW LEVEL SECURITY",
        "ADD COLUMN IF NOT EXISTS tenant_scope TEXT",
        "SET tenant_scope = 'standalone'",
        "ALTER COLUMN tenant_scope SET NOT NULL",
        "FORCE ROW LEVEL SECURITY",
    )
    missing_tokens = [token for token in required_tokens if token not in migration]
    if missing_tokens:
        raise RuntimeError(f"atomic migration is incomplete: {missing_tokens}")
    return repaired


def main() -> int:
    """Patch canonical and deployed schemas only when their inputs are identical."""
    canonical = CANONICAL_SCHEMA_PATH.read_text(encoding="utf-8")
    deployed = DEPLOYED_SCHEMA_PATH.read_text(encoding="utf-8")
    if deployed != canonical:
        raise RuntimeError("PostgreSQL image schema drifted before migration repair")
    repaired = apply_atomic_migration(canonical)
    CANONICAL_SCHEMA_PATH.write_text(repaired, encoding="utf-8")
    DEPLOYED_SCHEMA_PATH.write_text(repaired, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
