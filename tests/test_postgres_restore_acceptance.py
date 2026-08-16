# SPDX-License-Identifier: Apache-2.0
"""Catalog-acceptance regressions for an isolated PostgreSQL restore target."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.postgres_restore_acceptance import (
    PostgresRestoreAcceptanceError,
    inspect_postgres_restore_catalog,
)
from pg_llm_batch.postgres_schema_evidence import inspect_postgres_schema


REQUIRED_TABLES = (
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
REQUIRED_INDEXES = (
    "idx_llm_remote_batch_jobs_tenant_status_observed",
    "uq_llm_remote_batch_jobs_tenant_endpoint_id",
)
CHECKPOINT_TABLE = "llm_result_stream_checkpoints"


class _CatalogCursor:
    """Return one finite catalog snapshot through the caller-owned cursor seam."""

    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.rows = rows
        self.executed_sql: str | None = None
        self.executed_params: tuple[object, ...] | None = None

    def __enter__(self) -> _CatalogCursor:
        return self

    def __exit__(self, *_exc: object) -> bool:
        return False

    def execute(self, sql: object, params: object = None) -> None:
        if type(sql) is not str:
            raise AssertionError("catalog SQL must be an exact built-in string")
        self.executed_sql = sql
        self.executed_params = params if type(params) is tuple else None

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self.rows)


class _CatalogConnection:
    """Expose one caller-owned connection that never carries a DSN."""

    def __init__(self, rows: list[tuple[object, ...]]) -> None:
        self.cursor_handle = _CatalogCursor(rows)

    def cursor(self) -> _CatalogCursor:
        return self.cursor_handle


class _HostileName(str):
    """Refuse rendering if rejected catalog names leak into diagnostics."""

    def __str__(self) -> str:
        raise AssertionError("must not render hostile catalog names")


class _ExecuteFailureCursor(_CatalogCursor):
    """Surface a lower-layer catalog failure without becoming operator evidence."""

    def execute(self, sql: object, params: object = None) -> None:
        del sql, params
        raise RuntimeError("password=supersecret host=db.internal")


class _ExecuteFailureConnection(_CatalogConnection):
    """Return a cursor whose execute path leaks deployment text."""

    def cursor(self) -> _CatalogCursor:
        return _ExecuteFailureCursor([])


def _relation(
    name: str,
    kind: str,
    row_security: bool = False,
    force_row_security: bool = False,
) -> tuple[str, str, bool, bool]:
    return (name, kind, row_security, force_row_security)


def _complete_catalog(
    *,
    lifecycle_rls: bool = True,
    include_checkpoint: bool = True,
) -> list[tuple[object, ...]]:
    rows: list[tuple[object, ...]] = [
        _relation(name, "r") for name in REQUIRED_TABLES if name != "llm_remote_batch_jobs"
    ]
    rows.append(
        _relation(
            "llm_remote_batch_jobs",
            "r",
            row_security=lifecycle_rls,
            force_row_security=lifecycle_rls,
        )
    )
    rows.extend(_relation(name, "i") for name in REQUIRED_INDEXES)
    if include_checkpoint:
        rows.append(
            _relation(
                CHECKPOINT_TABLE,
                "r",
                row_security=True,
                force_row_security=True,
            )
        )
    return rows


def test_inspect_restore_catalog_accepts_complete_isolated_target() -> None:
    connection = _CatalogConnection(_complete_catalog())

    evidence = inspect_postgres_restore_catalog(connection)
    schema = inspect_postgres_schema()

    assert evidence.required_table_count == len(REQUIRED_TABLES)
    assert evidence.required_index_count == len(REQUIRED_INDEXES)
    assert evidence.lifecycle_rls_enabled is True
    assert evidence.lifecycle_rls_forced is True
    assert evidence.checkpoint_store_present is True
    assert evidence.checkpoint_store_rls_forced is True
    assert evidence.expected_schema_sha256 == schema.sha256
    assert evidence.expected_schema_size_bytes == schema.size_bytes
    assert "password" not in evidence.as_dict()
    assert "host" not in evidence.as_dict()


def test_inspect_restore_catalog_rejects_missing_lifecycle_table() -> None:
    rows = [
        row
        for row in _complete_catalog()
        if row[0] != "llm_remote_batch_jobs"
    ]
    connection = _CatalogConnection(rows)

    with pytest.raises(
        PostgresRestoreAcceptanceError,
        match="PostgreSQL restore catalog is incomplete",
    ):
        inspect_postgres_restore_catalog(connection)


def test_inspect_restore_catalog_rejects_unforced_lifecycle_rls() -> None:
    connection = _CatalogConnection(_complete_catalog(lifecycle_rls=False))

    with pytest.raises(
        PostgresRestoreAcceptanceError,
        match="PostgreSQL restore catalog failed tenant isolation checks",
    ):
        inspect_postgres_restore_catalog(connection)


def test_inspect_restore_catalog_allows_schema_init_without_checkpoint_store() -> None:
    connection = _CatalogConnection(_complete_catalog(include_checkpoint=False))

    evidence = inspect_postgres_restore_catalog(connection)

    assert evidence.checkpoint_store_present is False
    assert evidence.checkpoint_store_rls_forced is False
    assert evidence.required_table_count == len(REQUIRED_TABLES)


def test_inspect_restore_catalog_rejects_checkpoint_store_without_forced_rls() -> None:
    rows = _complete_catalog(include_checkpoint=False)
    rows.append(_relation(CHECKPOINT_TABLE, "r", row_security=True, force_row_security=False))
    connection = _CatalogConnection(rows)

    with pytest.raises(
        PostgresRestoreAcceptanceError,
        match="PostgreSQL restore catalog failed tenant isolation checks",
    ):
        inspect_postgres_restore_catalog(connection)


def test_inspect_restore_catalog_rejects_hostile_relation_name() -> None:
    rows = _complete_catalog()
    rows[0] = (_HostileName("com_config"), "r", False, False)
    connection = _CatalogConnection(rows)

    with pytest.raises(
        PostgresRestoreAcceptanceError,
        match="PostgreSQL restore catalog evidence is invalid",
    ):
        inspect_postgres_restore_catalog(connection)


def test_inspect_restore_catalog_hides_lower_layer_diagnostics() -> None:
    connection = _ExecuteFailureConnection([])

    with pytest.raises(
        PostgresRestoreAcceptanceError,
        match="PostgreSQL restore catalog could not be inspected",
    ) as raised:
        inspect_postgres_restore_catalog(connection)

    assert "supersecret" not in str(raised.value)
    assert "db.internal" not in str(raised.value)
    assert raised.value.__cause__ is None


def test_inspect_restore_catalog_rejects_oversized_catalog() -> None:
    rows = _complete_catalog() + [_relation(f"extra_table_{index}", "r") for index in range(8)]
    connection = _CatalogConnection(rows)

    with pytest.raises(
        PostgresRestoreAcceptanceError,
        match="PostgreSQL restore catalog evidence is invalid",
    ):
        inspect_postgres_restore_catalog(connection)


def test_inspect_restore_catalog_uses_parameterized_current_schema_probe() -> None:
    connection = _CatalogConnection(_complete_catalog())

    inspect_postgres_restore_catalog(connection)

    sql = connection.cursor_handle.executed_sql
    params = connection.cursor_handle.executed_params
    assert sql is not None
    assert "current_schema()" in sql
    assert "%s" in sql
    assert params is not None
    assert "llm_remote_batch_jobs" in params[1]
    assert CHECKPOINT_TABLE in params[1]


def test_inspect_restore_catalog_rejects_non_tuple_params_leakage_path() -> None:
    class _BadFetchCursor(_CatalogCursor):
        def fetchall(self) -> list[tuple[object, ...]]:
            return [("com_config", "r", False, False)]  # type: ignore[return-value]

    class _BadFetchConnection(_CatalogConnection):
        def cursor(self) -> _CatalogCursor:
            return _BadFetchCursor([])

    # A single required table is incomplete even if the row shape is valid.
    with pytest.raises(
        PostgresRestoreAcceptanceError,
        match="PostgreSQL restore catalog is incomplete",
    ):
        inspect_postgres_restore_catalog(_BadFetchConnection([]))
