# SPDX-License-Identifier: Apache-2.0
"""Static contract tests for production database integrity controls."""

from __future__ import annotations

from pathlib import Path


SCHEMA_SQL = (
    Path(__file__).resolve().parents[1] / "pg_llm_batch" / "schema.sql"
).read_text(encoding="utf-8")


def test_batch_files_reference_real_queues_without_random_defaults():
    """Every prepared file belongs to an existing queue in fresh and legacy schemas."""
    assert "queue_uuid UUID NOT NULL," in SCHEMA_SQL
    assert "queue_uuid UUID NOT NULL DEFAULT uuid_generate_v4()" not in SCHEMA_SQL
    assert "CONSTRAINT fk_llm_batch_files_queue" in SCHEMA_SQL
    assert "ALTER COLUMN queue_uuid DROP DEFAULT" in SCHEMA_SQL
    assert "orphaned llm_batch_files rows" in SCHEMA_SQL
    assert "USING ERRCODE = '23503'" in SCHEMA_SQL


def test_business_identities_are_unique_and_replay_safe():
    """Batch, file, and per-payload line identities cannot silently duplicate."""
    expected_indexes = {
        "uq_llm_batches_input_file_path": "input_file_path",
        "uq_llm_batch_files_batch_part": "batch_uuid, part_index",
        "uq_llm_batch_files_file_path": "file_path",
        "uq_llm_batch_files_payload_file": "payload_file_id",
        "uq_llm_jsonl_lines_payload_request": "payload_file_id, request_uuid",
        "uq_llm_jsonl_lines_payload_sequence": "payload_file_id, sequence_no",
    }
    for index_name, indexed_columns in expected_indexes.items():
        assert f"CREATE UNIQUE INDEX IF NOT EXISTS {index_name}" in SCHEMA_SQL
        assert indexed_columns in SCHEMA_SQL

    assert "CREATE UNIQUE INDEX IF NOT EXISTS uq_llm_jsonl_lines_request" not in (
        SCHEMA_SQL
    )
    assert "CREATE INDEX IF NOT EXISTS idx_llm_jsonl_lines_req" in SCHEMA_SQL


def test_preparation_and_status_queries_have_targeted_indexes():
    """Commercially hot queue and status scans use bounded index access paths."""
    assert "CREATE INDEX IF NOT EXISTS idx_llm_requests_batch_prepare" in SCHEMA_SQL
    assert "ON llm_requests(batch_uuid, created_at)" in SCHEMA_SQL
    assert "request_status = 'queued' AND batch_file_uuid IS NULL" in SCHEMA_SQL
    assert "CREATE INDEX IF NOT EXISTS idx_llm_batches_status_updated" in SCHEMA_SQL
    assert "ON llm_batches(batch_status, updated_at)" in SCHEMA_SQL


def test_only_redundant_payload_index_is_removed():
    """Retry lookups retain their request index while payload lookup stays covered."""
    assert "DROP INDEX IF EXISTS idx_llm_jsonl_lines_payload" in SCHEMA_SQL
    assert "DROP INDEX IF EXISTS idx_llm_jsonl_lines_req" not in SCHEMA_SQL
    assert "CREATE INDEX IF NOT EXISTS idx_llm_jsonl_lines_payload" not in SCHEMA_SQL
    assert "CREATE INDEX IF NOT EXISTS idx_llm_jsonl_lines_req" in SCHEMA_SQL


def test_postgres_image_schema_is_an_exact_canonical_mirror():
    """The deployable PostgreSQL image initializes the packaged canonical schema."""
    root = Path(__file__).resolve().parents[1]
    canonical = (root / "pg_llm_batch" / "schema.sql").read_text(
        encoding="utf-8"
    )
    mirror = (
        root / "docker" / "postgres" / "init" / "02_schema.sql"
    ).read_text(encoding="utf-8")
    mirror_header = (
        "-- SPDX-License-Identifier: Apache-2.0\n"
        "-- Build-context mirror of pg_llm_batch/schema.sql (canonical source read by\n"
        "-- pg_llm_batch/db.py). Kept here so docker/postgres/Dockerfile builds with its\n"
        "-- own directory as the build context (the central coverage-evidence job builds\n"
        "-- each changed Dockerfile with context = its own directory). Keep in sync with\n"
        "-- pg_llm_batch/schema.sql.\n"
    )
    assert mirror == mirror_header + canonical
