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


def _require_rejected_catalog(
    connection: object,
    *,
    expected_message: str,
) -> None:
    """Reject a catalog decoy with its exact content-free failure category."""
    try:
        inspect_postgres_restore_catalog(connection)
    except PostgresRestoreAcceptanceError as error:
        if str(error) != expected_message:
            raise SystemExit("decoy rejection used an unexpected category") from None
        return
    raise SystemExit("same-name decoy catalog object was accepted")


def _require_incomplete_catalog(connection: object) -> None:
    """Require structural catalog decoys to fail as incomplete."""
    _require_rejected_catalog(
        connection,
        expected_message="PostgreSQL restore catalog is incomplete",
    )


def _require_tenant_isolation_rejection(connection: object) -> None:
    """Require tenant-policy decoys to fail the isolation boundary explicitly."""
    _require_rejected_catalog(
        connection,
        expected_message="PostgreSQL restore catalog failed tenant isolation checks",
    )


def _restore_tenant_policy(
    cursor: object,
    *,
    table_name: str,
    policy_name: str,
) -> None:
    """Restore the exact package tenant predicate after a live decoy probe."""
    cursor.execute(f"DROP POLICY IF EXISTS {policy_name} ON {table_name}")
    cursor.execute(
        f"CREATE POLICY {policy_name} ON {table_name} TO PUBLIC "
        "USING (tenant_scope = "
        "current_setting('pg_llm_batch.tenant_scope', true)) "
        "WITH CHECK (tenant_scope = "
        "current_setting('pg_llm_batch.tenant_scope', true))"
    )


def _install_permissive_decoy(
    cursor: object,
    *,
    table_name: str,
    policy_name: str,
) -> None:
    """Replace one package policy with a same-name tenant-isolation bypass."""
    cursor.execute(f"DROP POLICY IF EXISTS {policy_name} ON {table_name}")
    cursor.execute(
        f"CREATE POLICY {policy_name} ON {table_name} TO PUBLIC "
        "USING (true) WITH CHECK (true)"
    )


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
            _install_permissive_decoy(
                cursor,
                table_name="llm_remote_batch_jobs",
                policy_name="plc_llm_remote_batch_jobs_tenant_scope",
            )
        _require_tenant_isolation_rejection(connection)
        with connection.cursor() as cursor:
            _restore_tenant_policy(
                cursor,
                table_name="llm_remote_batch_jobs",
                policy_name="plc_llm_remote_batch_jobs_tenant_scope",
            )
        _require_complete_catalog(connection)
        with connection.cursor() as cursor:
            _install_permissive_decoy(
                cursor,
                table_name="llm_result_stream_checkpoints",
                policy_name="plc_llm_result_stream_checkpoints_tenant_scope",
            )
        _require_tenant_isolation_rejection(connection)
        with connection.cursor() as cursor:
            _restore_tenant_policy(
                cursor,
                table_name="llm_result_stream_checkpoints",
                policy_name="plc_llm_result_stream_checkpoints_tenant_scope",
            )
        _require_complete_catalog(connection)


if __name__ == "__main__":
    main()
