# SPDX-License-Identifier: Apache-2.0
"""Regression tests for PostgreSQL restore-catalog query semantics."""

from __future__ import annotations

from pg_llm_batch.postgres_restore_acceptance import inspect_postgres_restore_catalog


_REQUIRED_TABLES = (
    "com_config",
    "com_secrets",
    "llm_queues",
    "llm_batches",
    "llm_remote_batch_jobs",
    "llm_batch_file_payloads",
    "llm_batch_files",
    "llm_requests",
    "llm_jsonl_lines",
    "llm_endpoints",
    "llm_endpoint_models",
)
_REQUIRED_INDEXES = (
    "idx_llm_remote_batch_jobs_tenant_status_observed",
    "uq_llm_remote_batch_jobs_tenant_endpoint_id",
)
_CHECKPOINT_TABLE = "llm_result_stream_checkpoints"


class _RecordingCursor:
    """Record the exact PostgreSQL query and parameters supplied by the probe."""

    def __init__(self) -> None:
        self.sql: str | None = None
        self.params: tuple[object, ...] | None = None

    def __enter__(self) -> _RecordingCursor:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def execute(self, sql: object, params: object = None) -> None:
        assert type(sql) is str
        assert type(params) is tuple
        self.sql = sql
        self.params = params

    def fetchall(self) -> list[tuple[object, ...]]:
        rows: list[tuple[object, ...]] = [
            (name, "r", False, False)
            for name in _REQUIRED_TABLES
            if name != "llm_remote_batch_jobs"
        ]
        rows.append(("llm_remote_batch_jobs", "r", True, True))
        rows.extend((name, "i", False, False) for name in _REQUIRED_INDEXES)
        rows.append((_CHECKPOINT_TABLE, "r", True, True))
        return rows


class _RecordingConnection:
    """Expose a caller-owned cursor without constructing a package connection."""

    def __init__(self) -> None:
        self.cursor_handle = _RecordingCursor()

    def cursor(self) -> _RecordingCursor:
        return self.cursor_handle


def test_any_parameters_use_psycopg_array_values() -> None:
    """Bind list values to ``ANY(%s)`` while retaining tuple execute parameters."""
    connection = _RecordingConnection()

    inspect_postgres_restore_catalog(connection)

    params = connection.cursor_handle.params
    assert params is not None
    assert type(params) is tuple
    assert type(params[0]) is list
    assert params[0] == ["r", "i"]
    assert type(params[1]) is list
    assert "llm_remote_batch_jobs" in params[1]
    assert _CHECKPOINT_TABLE in params[1]


def test_catalog_query_authenticates_index_structure() -> None:
    """Require index ownership, keys, uniqueness, validity, and plain-index shape."""
    connection = _RecordingConnection()

    inspect_postgres_restore_catalog(connection)

    sql = connection.cursor_handle.sql
    assert sql is not None
    required_fragments = (
        "pg_catalog.pg_index",
        "indrelid",
        "indisunique",
        "indisvalid",
        "indisready",
        "indpred",
        "indexprs",
        "pg_catalog.pg_get_indexdef",
        "llm_remote_batch_jobs",
        "tenant_scope",
        "endpoint_alias",
        "remote_batch_id",
        "batch_status",
        "last_observed_at",
    )
    for fragment in required_fragments:
        assert fragment in sql
