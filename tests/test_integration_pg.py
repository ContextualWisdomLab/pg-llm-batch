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
    SecretStore(dsn).set_secret("gateway_api_key.default", "sk-int-test")

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
