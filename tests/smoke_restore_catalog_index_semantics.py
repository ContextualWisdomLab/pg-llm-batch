# SPDX-License-Identifier: Apache-2.0
"""Live PostgreSQL decoy proof for isolated restore-catalog authentication."""

from __future__ import annotations

import os

import psycopg

from pg_llm_batch.postgres_restore_acceptance import (
    PostgresRestoreAcceptanceError,
    inspect_postgres_restore_catalog,
)

DSN = os.environ.get(
    "PG_LLM_BATCH_RESTORE_CATALOG_ACCEPTANCE_DSN",
    "postgresql://postgres@127.0.0.1:5432/postgres",
)


def _require_complete_catalog(connection: object) -> None:
    """Accept only a packaged isolated restore catalog on the caller-owned connection."""
    evidence = inspect_postgres_restore_catalog(connection)
    if evidence.required_index_count != 2 or evidence.lifecycle_rls_forced is not True:
        raise SystemExit("packaged restore catalog was not accepted")


def _require_incomplete_catalog(connection: object) -> None:
    """Reject a same-name decoy without reflecting SQL or connection text."""
    try:
        inspect_postgres_restore_catalog(connection)
    except PostgresRestoreAcceptanceError as error:
        if str(error) != "PostgreSQL restore catalog is incomplete":
            raise SystemExit("decoy rejection used an unexpected category") from None
        return
    raise SystemExit("same-name decoy catalog object was accepted")


def main() -> None:
    """Prove packaged indexes and tenant policies while rejecting same-name decoys."""
    with psycopg.connect(DSN) as connection:
        connection.autocommit = True
        _require_complete_catalog(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                "DROP INDEX IF EXISTS idx_llm_remote_batch_jobs_tenant_status_observed"
            )
            cursor.execute(
                "CREATE INDEX idx_llm_remote_batch_jobs_tenant_status_observed "
                "ON com_config (config_key)"
            )
        _require_incomplete_catalog(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                "DROP INDEX IF EXISTS idx_llm_remote_batch_jobs_tenant_status_observed"
            )
            cursor.execute(
                "CREATE INDEX idx_llm_remote_batch_jobs_tenant_status_observed "
                "ON llm_remote_batch_jobs (batch_status, tenant_scope, last_observed_at)"
            )
        _require_incomplete_catalog(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                "DROP INDEX IF EXISTS idx_llm_remote_batch_jobs_tenant_status_observed"
            )
            cursor.execute(
                "CREATE INDEX idx_llm_remote_batch_jobs_tenant_status_observed "
                "ON llm_remote_batch_jobs (tenant_scope, batch_status, last_observed_at)"
            )
            cursor.execute(
                "ALTER TABLE llm_remote_batch_jobs "
                "DROP CONSTRAINT IF EXISTS uq_llm_remote_batch_jobs_tenant_endpoint_id"
            )
            cursor.execute(
                "CREATE INDEX uq_llm_remote_batch_jobs_tenant_endpoint_id "
                "ON llm_remote_batch_jobs "
                "(tenant_scope, endpoint_alias, remote_batch_id)"
            )
        _require_incomplete_catalog(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                "DROP INDEX IF EXISTS uq_llm_remote_batch_jobs_tenant_endpoint_id"
            )
            cursor.execute(
                "ALTER TABLE llm_remote_batch_jobs "
                "ADD CONSTRAINT uq_llm_remote_batch_jobs_tenant_endpoint_id "
                "UNIQUE (tenant_scope, endpoint_alias, remote_batch_id)"
            )
        _require_complete_catalog(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                "DROP POLICY IF EXISTS plc_llm_remote_batch_jobs_tenant_scope "
                "ON llm_remote_batch_jobs"
            )
            cursor.execute(
                "CREATE POLICY plc_llm_remote_batch_jobs_tenant_scope "
                "ON llm_remote_batch_jobs TO PUBLIC "
                "USING (true) WITH CHECK (true)"
            )
        _require_incomplete_catalog(connection)
        with connection.cursor() as cursor:
            cursor.execute(
                "DROP POLICY IF EXISTS plc_llm_remote_batch_jobs_tenant_scope "
                "ON llm_remote_batch_jobs"
            )
            cursor.execute(
                "CREATE POLICY plc_llm_remote_batch_jobs_tenant_scope "
                "ON llm_remote_batch_jobs TO PUBLIC "
                "USING (tenant_scope = "
                "current_setting('pg_llm_batch.tenant_scope', true)) "
                "WITH CHECK (tenant_scope = "
                "current_setting('pg_llm_batch.tenant_scope', true))"
            )
        _require_complete_catalog(connection)


if __name__ == "__main__":
    main()
