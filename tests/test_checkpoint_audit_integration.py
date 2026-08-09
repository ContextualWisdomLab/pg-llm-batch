# SPDX-License-Identifier: Apache-2.0
"""Live PostgreSQL verification for checkpoint accepted-save audit evidence."""

from __future__ import annotations

import os
import uuid
from pathlib import Path

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
    reason="PG_LLM_BATCH_TEST_DSN not set; skipping live audit integration",
)


def _checkpoint(batch_id: str, digest: str) -> BatchResultCheckpoint:
    """Build one valid first checkpoint for live audit verification."""
    return BatchResultCheckpoint(
        schema_version=1,
        batch_id=batch_id,
        endpoint_alias="default",
        file_kind="result",
        file_id="file-live",
        file_line_number=1,
        batch_line_count=1,
        record_count=1,
        prefix_sha256=digest,
    )


@skip_no_db
def test_live_audit_is_tenant_isolated_append_only_and_rollback_safe() -> None:
    """Real least-privilege roles prove application and mutation boundaries."""
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    suffix = uuid.uuid4().hex[:12]
    database_name = f"audit_integration_{suffix}"
    application_role_name = f"audit_application_{suffix}"
    mutation_probe_role_name = f"audit_mutation_probe_{suffix}"
    application_password = uuid.uuid4().hex
    mutation_probe_password = uuid.uuid4().hex
    consumer = f"worker-{suffix}"
    batch_id = f"batch-{suffix}"
    database_dsn = make_conninfo(ADMIN_DSN, dbname=database_name)
    application_role_dsn = make_conninfo(
        ADMIN_DSN,
        dbname=database_name,
        user=application_role_name,
        password=application_password,
    )
    mutation_probe_role_dsn = make_conninfo(
        ADMIN_DSN,
        dbname=database_name,
        user=mutation_probe_role_name,
        password=mutation_probe_password,
    )
    application_role_created = False
    mutation_probe_role_created = False
    database_created = False

    try:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as cluster_admin:
            with cluster_admin.cursor() as cursor:
                # PostgreSQL utility statements cannot bind PASSWORD through a
                # protocol parameter. psycopg.sql.Literal performs the required
                # server-compatible quoting without string interpolation.
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
                    sql.SQL(
                        "CREATE ROLE {} LOGIN PASSWORD {} "
                        "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
                        "NOREPLICATION NOBYPASSRLS"
                    ).format(
                        sql.Identifier(mutation_probe_role_name),
                        sql.Literal(mutation_probe_password),
                    )
                )
                mutation_probe_role_created = True
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
                audit_sequence_parts = tuple(sequence_row[0])
                cursor.execute(
                    sql.SQL(
                        "GRANT USAGE, SELECT ON SEQUENCE {} TO {}"
                    ).format(
                        sql.Identifier(*audit_sequence_parts),
                        sql.Identifier(application_role_name),
                    )
                )
                cursor.execute(
                    sql.SQL(
                        "GRANT SELECT, UPDATE, DELETE, TRUNCATE ON "
                        "llm_result_checkpoint_audit_events TO {}"
                    ).format(sql.Identifier(mutation_probe_role_name))
                )
            database_admin.commit()

        tenant_a = AuditedPostgresBatchResultCheckpointStore(
            application_role_dsn,
            tenant_scope="tenant-a",
        )
        tenant_b = AuditedPostgresBatchResultCheckpointStore(
            application_role_dsn,
            tenant_scope="tenant-b",
        )
        first_a = _checkpoint(batch_id, "a" * 64)
        first_b = _checkpoint(batch_id, "b" * 64)

        assert tenant_a.save(consumer, first_a) == first_a
        assert tenant_b.save(consumer, first_b) == first_b
        assert tenant_a.save(consumer, first_a) == first_a

        events_a = tenant_a.list_audit_events(consumer, batch_id, "default")
        events_b = tenant_b.list_audit_events(consumer, batch_id, "default")
        assert len(events_a) == 2
        assert len(events_b) == 1
        assert {event.tenant_scope for event in events_a} == {"tenant-a"}
        assert {event.tenant_scope for event in events_b} == {"tenant-b"}

        timed_batch_id = f"timed-{suffix}"
        timed_checkpoint = _checkpoint(timed_batch_id, "c" * 64)
        with psycopg.connect(application_role_dsn) as timed_connection:
            with timed_connection.cursor() as cursor:
                cursor.execute("SELECT transaction_timestamp()")
                transaction_started_at = cursor.fetchone()[0]
                cursor.execute("SELECT pg_sleep(0.02)")
                cursor.execute("SELECT clock_timestamp()")
                before_save = cursor.fetchone()[0]

                assert (
                    tenant_a.save_in_transaction(
                        cursor,
                        consumer,
                        timed_checkpoint,
                    )
                    == timed_checkpoint
                )
                timed_events = tenant_a.list_audit_events_in_transaction(
                    cursor,
                    consumer,
                    timed_batch_id,
                    "default",
                )
                cursor.execute("SELECT clock_timestamp()")
                after_save = cursor.fetchone()[0]

                assert len(timed_events) == 1
                assert transaction_started_at < before_save
                assert before_save <= timed_events[0].recorded_at <= after_save
            timed_connection.rollback()

        with psycopg.connect(application_role_dsn) as unscoped_connection:
            with unscoped_connection.cursor() as cursor:
                cursor.execute("SELECT COUNT(*) FROM llm_result_checkpoint_audit_events")
                assert cursor.fetchone()[0] == 0

        with psycopg.connect(mutation_probe_role_dsn) as scoped_connection:
            with scoped_connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('pg_llm_batch.tenant_scope', %s, true)",
                    ("tenant-a",),
                )
                cursor.execute("SAVEPOINT before_update")
                with pytest.raises(psycopg.Error) as update_error:
                    cursor.execute(
                        "UPDATE llm_result_checkpoint_audit_events "
                        "SET file_id = 'changed'"
                    )
                assert update_error.value.sqlstate == "55000"
                cursor.execute("ROLLBACK TO SAVEPOINT before_update")

                cursor.execute("SAVEPOINT before_delete")
                with pytest.raises(psycopg.Error) as delete_error:
                    cursor.execute("DELETE FROM llm_result_checkpoint_audit_events")
                assert delete_error.value.sqlstate == "55000"
                cursor.execute("ROLLBACK TO SAVEPOINT before_delete")

                cursor.execute("SAVEPOINT before_truncate")
                with pytest.raises(psycopg.Error) as truncate_error:
                    cursor.execute("TRUNCATE llm_result_checkpoint_audit_events")
                assert truncate_error.value.sqlstate == "55000"
                cursor.execute("ROLLBACK TO SAVEPOINT before_truncate")
            scoped_connection.rollback()

        rollback_path = (
            Path(__file__).resolve().parents[1]
            / "pg_llm_batch/migrations/rollback/0008_result_checkpoint_audit_events.sql"
        )
        with psycopg.connect(database_dsn) as database_admin:
            with database_admin.cursor() as cursor:
                with pytest.raises(psycopg.Error) as rollback_error:
                    cursor.execute(rollback_path.read_text(encoding="utf-8"))
                assert rollback_error.value.sqlstate == "55000"
            database_admin.rollback()

        assert len(tenant_a.list_audit_events(consumer, batch_id, "default")) == 2
        assert len(tenant_b.list_audit_events(consumer, batch_id, "default")) == 1
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
                if mutation_probe_role_created:
                    cursor.execute(
                        sql.SQL("DROP ROLE IF EXISTS {}").format(
                            sql.Identifier(mutation_probe_role_name)
                        )
                    )
                if application_role_created:
                    cursor.execute(
                        sql.SQL("DROP ROLE IF EXISTS {}").format(
                            sql.Identifier(application_role_name)
                        )
                    )
