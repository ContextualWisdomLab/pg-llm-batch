# SPDX-License-Identifier: Apache-2.0
"""Regression tests for PostgreSQL restore-catalog query semantics."""

from __future__ import annotations

from pathlib import Path

from pg_llm_batch import postgres_restore_acceptance
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
        "pg_catalog.pg_am",
        "llm_remote_batch_jobs",
        "tenant_scope",
        "endpoint_alias",
        "remote_batch_id",
        "batch_status",
        "last_observed_at",
        "btree",
        "int2vector",
    )
    for fragment in required_fragments:
        assert fragment in sql


def test_catalog_sql_matches_packaged_lifecycle_index_shapes() -> None:
    """Bind probe predicates to the exact packaged unique and status indexes."""
    schema = (
        Path(__file__).resolve().parents[1] / "pg_llm_batch" / "schema.sql"
    ).read_text(encoding="utf-8")
    sql = postgres_restore_acceptance._CATALOG_SQL

    assert "UNIQUE (tenant_scope, endpoint_alias, remote_batch_id)" in schema
    assert (
        "CREATE INDEX IF NOT EXISTS "
        "idx_llm_remote_batch_jobs_tenant_status_observed"
    ) in schema
    assert "tenant_scope,\n        batch_status,\n        last_observed_at" in schema
    for ordinal, column_name in (
        (1, "tenant_scope"),
        (2, "endpoint_alias"),
        (3, "remote_batch_id"),
        (2, "batch_status"),
        (3, "last_observed_at"),
    ):
        assert f"pg_catalog.pg_get_indexdef(c.oid, {ordinal}, TRUE)" in sql
        assert f"OPERATOR(pg_catalog.=) '{column_name}'" in sql
    assert "NOT idx.indisunique" in sql
    assert "idx.indisunique" in sql
    assert "constraint_row.contype::pg_catalog.text" in sql
    assert "NOT constraint_row.condeferrable" in sql
    assert "access_method.amname::pg_catalog.text" in sql
    assert "idx.indoption OPERATOR(pg_catalog.=)" in sql
    assert "'0 0 0'::pg_catalog.int2vector" in sql


def test_catalog_query_authenticates_tenant_policy_semantics() -> None:
    """Bind restore acceptance to exact policy text and trusted object identity."""
    sql = postgres_restore_acceptance._CATALOG_SQL

    required_fragments = (
        "pg_catalog.pg_policy",
        "policy_row.polcmd::pg_catalog.text OPERATOR(pg_catalog.=) '*'",
        "policy_row.polpermissive IS TRUE",
        "policy_row.polroles OPERATOR(pg_catalog.=) ARRAY[0::pg_catalog.oid]",
        "plc_llm_remote_batch_jobs_tenant_scope",
        "plc_llm_result_stream_checkpoints_tenant_scope",
        "pg_catalog.pg_get_expr",
        "pg_catalog.replace(",
        "pg_catalog.regexp_replace(",
        "pg_llm_batch.tenant_scope",
        "pg_catalog.pg_depend",
        "'pg_catalog.pg_policy'::pg_catalog.regclass",
        "'pg_catalog.pg_proc'::pg_catalog.regclass",
        "'pg_catalog.current_setting(pg_catalog.text,pg_catalog.bool)'::pg_catalog.regprocedure",
        "'pg_catalog.pg_operator'::pg_catalog.regclass",
        "'pg_catalog.=(pg_catalog.text,pg_catalog.text)'::pg_catalog.regoperator",
        "function_dependency.deptype::pg_catalog.text OPERATOR(pg_catalog.=) 'n'",
        "operator_dependency.deptype::pg_catalog.text OPERATOR(pg_catalog.=) 'n'",
        "extra_policy.polrelid OPERATOR(pg_catalog.=) c.oid",
        "extra_policy.oid OPERATOR(pg_catalog.<>) policy_row.oid",
        "pg_catalog.current_schema()",
    )
    for fragment in required_fragments:
        assert fragment in sql

    assert "policy_row.polrelid = c.oid" not in sql
    assert "extra_policy.oid <> policy_row.oid" not in sql


def test_container_logging_smoke_runs_restore_catalog_index_decoys() -> None:
    """CI must execute the live same-name decoy proof on the packaged image."""
    logging_smoke = (
        Path(__file__).resolve().parents[1]
        / "tests"
        / "smoke_postgres_container_logging.sh"
    ).read_text(encoding="utf-8")

    assert "bash tests/smoke_restore_catalog_index_semantics.sh" in logging_smoke
