# SPDX-License-Identifier: Apache-2.0
"""Integration tests against a real pg_tiktoken + pg_cron Postgres container.

Run with a live DSN:
    docker compose up -d --build postgres
    PG_LLM_BATCH_TEST_DSN=postgresql://pgllm:pgllm@localhost:5432/pgllm \
        pytest -m integration

Skipped automatically when PG_LLM_BATCH_TEST_DSN is unset.
"""

from __future__ import annotations

import os
import uuid

import pytest

from pg_llm_batch import db
from pg_llm_batch.config import PostgresConfigStore, SecretStore
from pg_llm_batch.health import check_health
from pg_llm_batch.orchestrator import PostgresBatchOrchestrator
from pg_llm_batch.token_counter import TokenCounter

pytestmark = pytest.mark.integration

DSN = os.environ.get("PG_LLM_BATCH_TEST_DSN")

skip_no_db = pytest.mark.skipif(
    not DSN, reason="PG_LLM_BATCH_TEST_DSN not set; skipping live-DB integration"
)


@pytest.fixture(scope="module")
def dsn() -> str:
    db.apply_schema(DSN)
    return DSN


@skip_no_db
def test_health_reports_ready(dsn):
    report = check_health(dsn)
    components = {c["component"]: c for c in report["components"]}
    assert components["database"]["is_ready"] is True
    assert components["pg_tiktoken"]["is_ready"] is True, report
    assert report["ready"] is True


@skip_no_db
def test_pg_tiktoken_counts_tokens(dsn):
    counter = TokenCounter(dsn, config=PostgresConfigStore(dsn))
    assert counter._pg_available is True
    n = counter.count_tokens("The quick brown fox", "gpt-4o")
    assert n > 0


@skip_no_db
def test_end_to_end_batch_assembly(dsn):
    config = PostgresConfigStore(dsn)
    config.set("gateway", "base_url", "https://gw.invalid/v1")
    SecretStore(dsn, require_encryption=False).set_secret(
        "gateway_api_key.default", "sk-int-test"
    )

    import psycopg

    batch_uuid = str(uuid.uuid4())
    with psycopg.connect(dsn) as conn:
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO llm_queues (queue_name) VALUES (%s) "
                "ON CONFLICT (queue_name) DO NOTHING",
                ("integration-queue",),
            )
            cur.execute(
                "SELECT queue_uuid FROM llm_queues WHERE queue_name = %s",
                ("integration-queue",),
            )
            queue_uuid = cur.fetchone()[0]
            cur.execute(
                """
                INSERT INTO llm_batches (batch_uuid, queue_uuid, batch_name, model_name)
                VALUES (%s, %s, %s, %s)
                """,
                (batch_uuid, queue_uuid, "int-batch", "gpt-4o"),
            )
            for prompt in ("hello world", "the quick brown fox"):
                cur.execute(
                    """
                    INSERT INTO llm_requests
                        (batch_uuid, system_prompt, user_prompt, model_name)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (batch_uuid, "you are helpful", prompt, "gpt-4o"),
                )

    orch = PostgresBatchOrchestrator(dsn)
    result = orch.prepare_batches(batch_uuid=batch_uuid)
    assert len(result["ready"]) == 1
    payload = result["ready"][0]
    assert payload.request_count == 2
    assert payload.total_tokens > 0

    file_id = payload.file_path.split("memory://", 1)[1]
    jsonl = db.load_virtual_payload(dsn, file_id)
    assert jsonl and jsonl.count("\n") == 2


def _read_remote_progress(dsn: str, remote_batch_id: str):
    """Read one standalone lifecycle row under its forced-RLS tenant scope."""
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('pg_llm_batch.tenant_scope', %s, true)",
                ("standalone",),
            )
            cursor.execute(
                """
                SELECT total_requests,
                       total_requests_known,
                       completed_requests,
                       failed_requests,
                       observation_order
                FROM llm_remote_batch_jobs
                WHERE tenant_scope = %s
                  AND endpoint_alias = %s
                  AND remote_batch_id = %s
                """,
                ("standalone", "primary", remote_batch_id),
            )
            return cursor.fetchone()


def _delete_remote_progress(dsn: str, *remote_batch_ids: str) -> None:
    """Remove integration-only standalone lifecycle rows under forced RLS."""
    import psycopg

    with psycopg.connect(dsn) as connection:
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT set_config('pg_llm_batch.tenant_scope', %s, true)",
                ("standalone",),
            )
            cursor.execute(
                "DELETE FROM llm_remote_batch_jobs "
                "WHERE tenant_scope = %s AND remote_batch_id = ANY(%s)",
                ("standalone", list(remote_batch_ids)),
            )
        connection.commit()


@skip_no_db
def test_live_progress_upsert_distinguishes_unknown_total_and_guards_conflicts(
    dsn: str,
) -> None:
    """PostgreSQL must preserve sparse progress without manufacturing a known total."""
    suffix = uuid.uuid4().hex[:12]
    known_batch_id = f"known-progress-{suffix}"
    sparse_batch_id = f"sparse-progress-{suffix}"

    try:
        db.persist_remote_batch_state(
            dsn,
            "primary",
            {
                "id": known_batch_id,
                "status": "in_progress",
                "request_counts": {"total": 10, "completed": 9, "failed": 0},
            },
            1,
        )
        assert _read_remote_progress(dsn, known_batch_id) == (10, True, 9, 0, 1)

        rejected_known = db.persist_remote_batch_state(
            dsn,
            "primary",
            {
                "id": known_batch_id,
                "status": "in_progress",
                "request_counts": {"total": 10, "completed": 0, "failed": 2},
            },
            2,
        )
        assert _read_remote_progress(dsn, known_batch_id) == (10, True, 9, 0, 1)
        assert rejected_known["total_requests"] == 10
        assert rejected_known["completed_requests"] == 9
        assert rejected_known["failed_requests"] == 0
        assert rejected_known["observation_order"] == 1

        db.persist_remote_batch_state(
            dsn,
            "primary",
            {
                "id": known_batch_id,
                "status": "in_progress",
                "request_counts": {"total": 11, "completed": 0, "failed": 2},
            },
            3,
        )
        assert _read_remote_progress(dsn, known_batch_id) == (11, True, 9, 2, 3)

        db.persist_remote_batch_state(
            dsn,
            "primary",
            {
                "id": sparse_batch_id,
                "status": "in_progress",
                "request_counts": {"completed": 5},
            },
            1,
        )
        assert _read_remote_progress(dsn, sparse_batch_id) == (0, False, 5, 0, 1)

        db.persist_remote_batch_state(
            dsn,
            "primary",
            {
                "id": sparse_batch_id,
                "status": "in_progress",
                "request_counts": {"total": "invalid", "failed": 2},
            },
            2,
        )
        assert _read_remote_progress(dsn, sparse_batch_id) == (0, False, 5, 2, 2)

        rejected_sparse = db.persist_remote_batch_state(
            dsn,
            "primary",
            {
                "id": sparse_batch_id,
                "status": "in_progress",
                "request_counts": {"total": 6},
            },
            3,
        )
        assert _read_remote_progress(dsn, sparse_batch_id) == (0, False, 5, 2, 2)
        assert rejected_sparse["total_requests"] == 0
        assert rejected_sparse["completed_requests"] == 5
        assert rejected_sparse["failed_requests"] == 2
        assert rejected_sparse["observation_order"] == 2

        db.persist_remote_batch_state(
            dsn,
            "primary",
            {
                "id": sparse_batch_id,
                "status": "in_progress",
                "request_counts": {"total": 7},
            },
            4,
        )
        assert _read_remote_progress(dsn, sparse_batch_id) == (7, True, 5, 2, 4)
    finally:
        _delete_remote_progress(dsn, known_batch_id, sparse_batch_id)


@skip_no_db
def test_live_rls_separates_identical_provider_ids_by_tenant(dsn: str) -> None:
    """A non-bypass role cannot observe another tenant's lifecycle row."""
    import psycopg
    from psycopg import sql
    from psycopg.conninfo import make_conninfo

    db.apply_schema(dsn)
    suffix = uuid.uuid4().hex[:12]
    role_name = f"tenant_scope_test_{suffix}"
    password = uuid.uuid4().hex
    batch_id = f"batch-{suffix}"
    role_dsn = make_conninfo(dsn, user=role_name, password=password)

    with psycopg.connect(dsn) as admin:
        with admin.cursor() as cursor:
            cursor.execute(
                sql.SQL(
                    "CREATE ROLE {} LOGIN PASSWORD %s "
                    "NOSUPERUSER NOCREATEDB NOCREATEROLE NOINHERIT "
                    "NOREPLICATION NOBYPASSRLS"
                ).format(sql.Identifier(role_name)),
                (password,),
            )
            cursor.execute(
                sql.SQL(
                    "GRANT SELECT, INSERT, UPDATE ON "
                    "llm_remote_batch_jobs TO {}"
                ).format(sql.Identifier(role_name))
            )
        admin.commit()

    try:
        db.persist_tenant_remote_batch_state(
            role_dsn,
            "tenant-a",
            "primary",
            {"id": batch_id, "status": "in_progress"},
            1,
        )
        db.persist_tenant_remote_batch_state(
            role_dsn,
            "tenant-b",
            "primary",
            {"id": batch_id, "status": "completed"},
            2,
        )

        tenant_a = db.get_tenant_remote_batch_state(
            role_dsn,
            "tenant-a",
            "primary",
            batch_id,
        )
        tenant_b = db.get_tenant_remote_batch_state(
            role_dsn,
            "tenant-b",
            "primary",
            batch_id,
        )
        assert tenant_a is not None
        assert tenant_b is not None
        assert tenant_a["tenant_scope"] == "tenant-a"
        assert tenant_b["tenant_scope"] == "tenant-b"
        assert tenant_a["batch_status"] == "in_progress"
        assert tenant_b["batch_status"] == "completed"

        with psycopg.connect(role_dsn) as unscoped_connection:
            with unscoped_connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM llm_remote_batch_jobs "
                    "WHERE remote_batch_id = %s",
                    (batch_id,),
                )
                assert cursor.fetchone()[0] == 0

        pooled_connection = psycopg.connect(role_dsn)
        try:
            with pooled_connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config("
                    "'pg_llm_batch.tenant_scope', %s, true)",
                    ("tenant-a",),
                )
                cursor.execute(
                    "SELECT COUNT(*) FROM llm_remote_batch_jobs "
                    "WHERE remote_batch_id = %s",
                    (batch_id,),
                )
                assert cursor.fetchone()[0] == 1
            pooled_connection.rollback()

            with pooled_connection.cursor() as cursor:
                cursor.execute(
                    "SELECT COUNT(*) FROM llm_remote_batch_jobs "
                    "WHERE remote_batch_id = %s",
                    (batch_id,),
                )
                assert cursor.fetchone()[0] == 0
                cursor.execute(
                    "SELECT set_config("
                    "'pg_llm_batch.tenant_scope', %s, true)",
                    ("tenant-b",),
                )
                cursor.execute(
                    "SELECT COUNT(*) FROM llm_remote_batch_jobs "
                    "WHERE tenant_scope = %s AND remote_batch_id = %s",
                    ("tenant-a", batch_id),
                )
                assert cursor.fetchone()[0] == 0
                cursor.execute(
                    "SELECT COUNT(*) FROM llm_remote_batch_jobs "
                    "WHERE tenant_scope = %s AND remote_batch_id = %s",
                    ("tenant-b", batch_id),
                )
                assert cursor.fetchone()[0] == 1
        finally:
            pooled_connection.close()

        with psycopg.connect(role_dsn) as tenant_connection:
            with tenant_connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config("
                    "'pg_llm_batch.tenant_scope', %s, true)",
                    ("tenant-a",),
                )
                cursor.execute(
                    "SELECT COUNT(*) FROM llm_remote_batch_jobs "
                    "WHERE tenant_scope = %s AND remote_batch_id = %s",
                    ("tenant-b", batch_id),
                )
                assert cursor.fetchone()[0] == 0
    finally:
        with psycopg.connect(dsn) as admin:
            with admin.cursor() as cursor:
                cursor.execute(
                    "DELETE FROM llm_remote_batch_jobs WHERE remote_batch_id = %s",
                    (batch_id,),
                )
                cursor.execute(
                    sql.SQL("DROP OWNED BY {}").format(sql.Identifier(role_name))
                )
                cursor.execute(
                    sql.SQL("DROP ROLE {}").format(sql.Identifier(role_name))
                )
            admin.commit()
