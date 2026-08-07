# SPDX-License-Identifier: Apache-2.0
"""Live PostgreSQL verification for the checkpoint migration operator."""

from __future__ import annotations

import os
import threading
import time
import uuid
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

import pytest

from pg_llm_batch import apply_checkpoint_schema_migrations
from pg_llm_batch import checkpoint_migrations
from pg_llm_batch.checkpoint_store import MIGRATION_PATH

pytestmark = pytest.mark.integration

ADMIN_DSN = os.environ.get("PG_LLM_BATCH_TEST_DSN")
skip_no_db = pytest.mark.skipif(
    not ADMIN_DSN,
    reason="PG_LLM_BATCH_TEST_DSN not set; skipping live migration integration",
)


@contextmanager
def _temporary_database() -> Iterator[str]:
    """Yield one isolated PostgreSQL database and remove it after the test."""
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    suffix = uuid.uuid4().hex[:12]
    database_name = f"migration_operator_{suffix}"
    database_created = False
    database_dsn = make_conninfo(ADMIN_DSN, dbname=database_name)
    try:
        with psycopg.connect(ADMIN_DSN, autocommit=True) as cluster_admin:
            with cluster_admin.cursor() as cursor:
                cursor.execute(
                    sql.SQL("CREATE DATABASE {}").format(
                        sql.Identifier(database_name)
                    )
                )
                database_created = True
        with psycopg.connect(database_dsn, autocommit=True) as database_admin:
            with database_admin.cursor() as cursor:
                cursor.execute('CREATE EXTENSION IF NOT EXISTS "uuid-ossp"')
        yield database_dsn
    finally:
        if database_created:
            with psycopg.connect(ADMIN_DSN, autocommit=True) as cluster_admin:
                with cluster_admin.cursor() as cursor:
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


def _table_names(database_dsn: str) -> tuple[str | None, str | None]:
    """Return the durable checkpoint and audit table identities, if present."""
    import psycopg

    with psycopg.connect(database_dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT "
                "to_regclass('public.llm_result_stream_checkpoints')::text, "
                "to_regclass('public.llm_result_checkpoint_audit_events')::text"
            )
            row = cursor.fetchone()
    assert row is not None
    return row[0], row[1]


@skip_no_db
def test_second_migration_failure_rolls_back_the_first(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Invalid migration 0008 leaves neither package table partially applied."""
    import psycopg

    checkpoint_path = tmp_path / "0007_result_stream_checkpoints.sql"
    checkpoint_path.write_bytes(MIGRATION_PATH.read_bytes())
    invalid_audit_path = tmp_path / "0008_result_checkpoint_audit_events.sql"
    invalid_audit_path.write_text("SELECT FROM;", encoding="utf-8")
    monkeypatch.setattr(
        checkpoint_migrations,
        "_CHECKPOINT_SCHEMA_MIGRATION_PATHS",
        (
            ("0007_result_stream_checkpoints", checkpoint_path),
            ("0008_result_checkpoint_audit_events", invalid_audit_path),
        ),
    )

    with _temporary_database() as database_dsn:
        with pytest.raises(psycopg.Error):
            apply_checkpoint_schema_migrations(database_dsn)
        assert _table_names(database_dsn) == (None, None)


@skip_no_db
def test_concurrent_operator_waits_for_the_transaction_advisory_lock() -> None:
    """A competing invocation waits until the held package lock is released."""
    import psycopg
    from psycopg.conninfo import make_conninfo

    application_name = f"checkpoint_migration_{uuid.uuid4().hex[:12]}"
    worker_errors: list[BaseException] = []
    worker_started = threading.Event()
    worker_finished = threading.Event()

    with _temporary_database() as database_dsn:
        worker_dsn = make_conninfo(database_dsn, application_name=application_name)
        with psycopg.connect(database_dsn) as lock_holder:
            with lock_holder.cursor() as cursor:
                cursor.execute(
                    "SELECT pg_advisory_xact_lock(%s, %s)",
                    (
                        checkpoint_migrations.CHECKPOINT_SCHEMA_MIGRATION_LOCK_NAMESPACE,
                        checkpoint_migrations.CHECKPOINT_SCHEMA_MIGRATION_LOCK_OPERATION,
                    ),
                )

            def run_worker() -> None:
                """Apply the migration plan and retain only test-local failures."""
                worker_started.set()
                try:
                    apply_checkpoint_schema_migrations(worker_dsn)
                except BaseException as exc:  # pragma: no cover - asserted below
                    worker_errors.append(exc)
                finally:
                    worker_finished.set()

            worker = threading.Thread(target=run_worker, daemon=True)
            worker.start()
            assert worker_started.wait(timeout=2.0)

            waiting_observed = False
            deadline = time.monotonic() + 5.0
            with psycopg.connect(database_dsn, autocommit=True) as observer:
                with observer.cursor() as cursor:
                    while time.monotonic() < deadline:
                        cursor.execute(
                            "SELECT EXISTS ("
                            "SELECT 1 FROM pg_locks AS migration_locks "
                            "JOIN pg_stat_activity AS migration_sessions "
                            "ON migration_sessions.pid = migration_locks.pid "
                            "WHERE migration_sessions.application_name = %s "
                            "AND migration_locks.locktype = 'advisory' "
                            "AND NOT migration_locks.granted"
                            ")",
                            (application_name,),
                        )
                        row = cursor.fetchone()
                        if row and row[0] is True:
                            waiting_observed = True
                            break
                        time.sleep(0.02)

            assert waiting_observed
            assert not worker_finished.is_set()
            lock_holder.commit()
            assert worker_finished.wait(timeout=10.0)
            worker.join(timeout=1.0)

        assert not worker.is_alive()
        assert worker_errors == []
        assert _table_names(database_dsn) == (
            "llm_result_stream_checkpoints",
            "llm_result_checkpoint_audit_events",
        )
