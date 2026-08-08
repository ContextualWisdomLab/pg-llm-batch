# SPDX-License-Identifier: Apache-2.0
"""Live PostgreSQL integration tests for durable result checkpoints."""

from __future__ import annotations

import os
import uuid

import pytest

from pg_llm_batch import (
    BatchResultCheckpoint,
    CheckpointConflictError,
    PostgresBatchResultCheckpointStore,
    apply_result_checkpoint_schema,
)

pytestmark = pytest.mark.integration

DSN = os.environ.get("PG_LLM_BATCH_TEST_DSN")
skip_no_db = pytest.mark.skipif(
    not DSN,
    reason="PG_LLM_BATCH_TEST_DSN not set; skipping live-DB integration",
)


def _checkpoint(batch_id: str, *, record_count: int, digest: str) -> BatchResultCheckpoint:
    """Build one live-database checkpoint with monotonic positions."""
    return BatchResultCheckpoint(
        schema_version=1,
        batch_id=batch_id,
        endpoint_alias="default",
        file_kind="result",
        file_id="file-live",
        file_line_number=record_count,
        batch_line_count=record_count,
        record_count=record_count,
        prefix_sha256=digest,
    )


@skip_no_db
def test_live_checkpoint_compare_and_swap_is_idempotent_and_fail_closed() -> None:
    """PostgreSQL preserves exact CAS state and rejects a stale writer."""
    import psycopg

    apply_result_checkpoint_schema(DSN)
    suffix = uuid.uuid4().hex
    consumer = f"integration-{suffix}"
    batch_id = f"batch-{suffix}"
    store = PostgresBatchResultCheckpointStore(DSN, tenant_scope="standalone")
    first = _checkpoint(batch_id, record_count=1, digest="a" * 64)
    second = _checkpoint(batch_id, record_count=2, digest="b" * 64)

    try:
        assert store.save(consumer, first) == first
        assert store.save(consumer, first) == first
        assert store.save(consumer, second, expected_previous=first) == second
        assert store.load(consumer, batch_id, "default") == second
        with pytest.raises(CheckpointConflictError):
            store.save(consumer, first, expected_previous=first)
    finally:
        with psycopg.connect(DSN) as connection:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT set_config('pg_llm_batch.tenant_scope', %s, true)",
                    ("standalone",),
                )
                cursor.execute(
                    "DELETE FROM llm_result_stream_checkpoints "
                    "WHERE checkpoint_consumer_name = %s",
                    (consumer,),
                )
            connection.commit()
