# SPDX-License-Identifier: Apache-2.0
"""Live PostgreSQL verification for checkpoint-audit snapshot manifests."""

from __future__ import annotations

import os
import uuid

import pytest

from pg_llm_batch import (
    AuditedPostgresBatchResultCheckpointStore,
    BatchResultCheckpoint,
    apply_result_checkpoint_audit_schema,
    apply_result_checkpoint_schema,
)

pytestmark = pytest.mark.integration

ADMIN_DSN = os.environ.get("PG_LLM_BATCH_TEST_DSN")
skip_no_db = pytest.mark.skipif(
    not ADMIN_DSN,
    reason="PG_LLM_BATCH_TEST_DSN not set; skipping live audit snapshot integration",
)


def _checkpoint(batch_id: str) -> BatchResultCheckpoint:
    """Build one valid checkpoint for live snapshot-manifest verification."""
    return BatchResultCheckpoint(
        schema_version=1,
        batch_id=batch_id,
        endpoint_alias="default",
        file_kind="result",
        file_id="file-snapshot",
        file_line_number=1,
        batch_line_count=1,
        record_count=1,
        prefix_sha256="d" * 64,
    )


@skip_no_db
def test_live_snapshot_manifest_uses_one_repeatable_read_view() -> None:
    """A later commit stays outside the stable snapshot and page size cannot change its hash."""
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    suffix = uuid.uuid4().hex[:12]
    database_name = f"audit_snapshot_{suffix}"
    application_role_name = f"audit_snapshot_app_{suffix}"
    application_password = uuid.uuid4().hex
    consumer = f"worker-{suffix}"
    batch_id = f"batch-{suffix}"
    database_dsn = make_conninfo(ADMIN_DSN, dbname=database_name)
    application_role_dsn = make_conninfo(
        ADMIN_DSN,
        dbname=database_name,
        user=application_role_name,
        password=application_password,
    )
    application_role_created = False
    database_created = False

    try:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as cluster_admin:
            with cluster_admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "CREATE ROLE {} LOGIN PASSWORD {} "
                        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
                        "NOREPLICATION NOBYPASSRLS"
                    ).format(
                        sql.Identifier(application_role_name),
                        sql.Literal(application_password),
                    )
                )
                application_role_created = True
                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(sql.Identifier(database_name))
                )
                database_created = True

        with psycopg.connect(database_dsn, autocommit=True) as database_admin:
            with database_admin.cursor() as cursor:
                cursor.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')

        apply_result_checkpoint_schema(database_dsn)
        apply_result_checkpoint_audit_schema(database_dsn)

        with psycopg.connect(database_dsn) as database_admin:
            with database_admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL(
                        "GRANT SELECT, INSERT, UPDATE ON "
                        "llm_result_stream_checkpoints TO {}"
                    ).format(sql.Identifier(application_role_name))
                )
                cursor.execute(
                    sql.SQL(
                        "GRANT SELECT, INSERT ON "
                        "llm_result_checkpoint_audit_events TO {}"
                    ).format(sql.Identifier(application_role_name))
                )
                cursor.execute(
                    "SELECT parse_ident(pg_get_serial_sequence(%s, %s))",
                    (
                        "llm_result_checkpoint_audit_events",
                        "checkpoint_audit_event_id",
                    ),
                )
                sequence_row = cursor.fetchone()
                if (
                    not sequence_row
                    or not isinstance(sequence_row[0], (list, tuple))
                    or not sequence_row[0]
                    or not all(
                        isinstance(part, str) and part for part in sequence_row[0]
                    )
                ):
                    raise RuntimeError("audit identity sequence could not be resolved")
                cursor.execute(
                    sql.SQL("GRANT USAGE, SELECT ON SEQUENCE {} TO {}").format(
                        sql.Identifier(*tuple(sequence_row[0])),
                        sql.Identifier(application_role_name),
                    )
                )
            database_admin.commit()

        store = AuditedPostgresBatchResultCheckpointStore(
            application_role_dsn,
            tenant_scope="tenant-a",
        )
        checkpoint = _checkpoint(batch_id)
        assert store.save(consumer, checkpoint) == checkpoint
        assert store.save(consumer, checkpoint) == checkpoint

        with psycopg.connect(application_role_dsn) as snapshot_connection:
            with snapshot_connection.cursor() as cursor:
                cursor.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ")
                baseline = store.list_audit_events_in_transaction(
                    cursor,
                    consumer,
                    batch_id,
                    "default",
                )
                assert len(baseline) == 2
                baseline_ids = tuple(event.audit_event_id for event in baseline)

                assert store.save(consumer, checkpoint) == checkpoint

                one_at_a_time = store.build_audit_snapshot_manifest_in_transaction(
                    cursor,
                    consumer,
                    batch_id,
                    "default",
                    max_events=2,
                    page_size=1,
                )
                two_at_a_time = store.build_audit_snapshot_manifest_in_transaction(
                    cursor,
                    consumer,
                    batch_id,
                    "default",
                    max_events=2,
                    page_size=2,
                )
                assert one_at_a_time == two_at_a_time
                assert one_at_a_time.event_count == 2
                assert one_at_a_time.newest_audit_event_id == baseline_ids[0]
                assert one_at_a_time.oldest_audit_event_id == baseline_ids[-1]
                assert len(one_at_a_time.snapshot_sha256) == 64
            snapshot_connection.rollback()

        assert len(store.list_audit_events(consumer, batch_id, "default")) == 3

        with psycopg.connect(application_role_dsn) as read_committed_connection:
            with read_committed_connection.cursor() as cursor:
                cursor.execute("BEGIN ISOLATION LEVEL READ COMMITTED")
                with pytest.raises(
                    RuntimeError,
                    match="REPEATABLE READ or SERIALIZABLE",
                ):
                    store.build_audit_snapshot_manifest_in_transaction(
                        cursor,
                        consumer,
                        batch_id,
                        "default",
                    )
            read_committed_connection.rollback()

        with psycopg.connect(
            application_role_dsn,
            autocommit=True,
        ) as autocommit_connection:
            with autocommit_connection.cursor() as cursor:
                cursor.execute("SET default_transaction_isolation TO 'repeatable read'")
                with pytest.raises(
                    RuntimeError,
                    match="active PostgreSQL transaction",
                ):
                    store.build_audit_snapshot_manifest_in_transaction(
                        cursor,
                        consumer,
                        batch_id,
                        "default",
                    )
    finally:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as cluster_admin:
            with cluster_admin.cursor() as cursor:
                if database_created:
                    cursor.execute(
                        "SELECT pg_terminate_backend(pid) FROM pg_stat_activity "
                        "WHERE datname = %s AND pid <> pg_backend_pid()",
                        (database_name,),
                    )
                    cursor.execute(
                        sql.SQL("DROP DATABASE IF EXISTS {}").format(
                            sql.Identifier(database_name)
                        )
                    )
                if application_role_created:
                    cursor.execute(
                        sql.SQL("DROP ROLE IF EXISTS {}").format(
                            sql.Identifier(application_role_name)
                        )
                    )
