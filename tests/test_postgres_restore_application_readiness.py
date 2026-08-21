# SPDX-License-Identifier: Apache-2.0
"""Tests for bounded application-readiness inspection after PostgreSQL restore."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.postgres_restore_application_readiness import (
    PostgresRestoreApplicationReadinessError,
    inspect_postgres_restore_application_readiness,
)


_SUCCESS_ROW = (True, True, True, True, True, 1, True)


class _Cursor:
    """Minimal DB-API cursor double for one fixed readiness observation."""

    def __init__(self, row: object = _SUCCESS_ROW, *, fail: bool = False) -> None:
        self.row = row
        self.fail = fail
        self.executed_sql: str | None = None

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_args: object) -> None:
        return None

    def execute(self, sql: str) -> None:
        if self.fail:
            raise RuntimeError("secret database detail")
        self.executed_sql = sql

    def fetchone(self) -> object:
        return self.row


class _Connection:
    """Minimal caller-owned connection double exposing one cursor."""

    def __init__(self, cursor: _Cursor) -> None:
        self.test_cursor = cursor

    def cursor(self) -> _Cursor:
        return self.test_cursor


def _inspect(row: object = _SUCCESS_ROW):
    cursor = _Cursor(row)
    evidence = inspect_postgres_restore_application_readiness(_Connection(cursor))
    return evidence, cursor


def test_restore_application_readiness_accepts_exact_prerequisites() -> None:
    """Exact database-side prerequisites produce fixed content-free evidence."""
    evidence, cursor = _inspect()

    assert evidence.as_dict() == {
        "database_reachable": True,
        "pg_tiktoken_extension_present": True,
        "tiktoken_count_callable": True,
        "tiktoken_encode_callable": True,
        "config_table_readable": True,
        "health_function_count": 1,
        "health_function_executable": True,
    }
    assert cursor.executed_sql is not None
    assert "pg_catalog.pg_extension" in cursor.executed_sql
    assert "pg_catalog.pg_depend" in cursor.executed_sql
    assert "pg_catalog.pg_class" in cursor.executed_sql
    assert "pg_catalog.pg_proc" in cursor.executed_sql
    assert "pg_catalog.has_table_privilege" in cursor.executed_sql
    assert cursor.executed_sql.count("pg_catalog.has_schema_privilege") >= 4
    assert cursor.executed_sql.count("pg_catalog.has_function_privilege") >= 3
    assert "pg_llm_batch_health_check()" not in cursor.executed_sql


@pytest.mark.parametrize(
    "row",
    [
        list(_SUCCESS_ROW),
        _SUCCESS_ROW[:-1],
        ("yes", True, True, True, True, 1, True),
        (True, "yes", True, True, True, 1, True),
        (True, True, "yes", True, True, 1, True),
        (True, True, True, "yes", True, 1, True),
        (True, True, True, True, "yes", 1, True),
        (True, True, True, True, True, 1.0, True),
        (True, True, True, True, True, True, True),
        (True, True, True, True, True, 1, "yes"),
    ],
)
def test_restore_application_readiness_rejects_malformed_rows(row: object) -> None:
    """Behavior-bearing or incorrectly typed database rows fail closed."""
    with pytest.raises(
        PostgresRestoreApplicationReadinessError,
        match="^PostgreSQL restore application-readiness evidence is invalid$",
    ):
        _inspect(row)


@pytest.mark.parametrize(
    ("row", "message"),
    [
        ((False, True, True, True, True, 1, True), "database is unavailable"),
        ((True, False, True, True, True, 1, True), "tokenizer is unavailable"),
        ((True, True, False, True, True, 1, True), "tokenizer is unavailable"),
        ((True, True, True, False, True, 1, True), "tokenizer is unavailable"),
        ((True, True, True, True, False, 1, True), "configuration is unavailable"),
        ((True, True, True, True, True, 0, True), "health contract is unavailable"),
        ((True, True, True, True, True, 2, True), "health contract is unavailable"),
        ((True, True, True, True, True, 1, False), "health contract is unavailable"),
    ],
)
def test_restore_application_readiness_rejects_missing_prerequisites(
    row: tuple[object, ...],
    message: str,
) -> None:
    """Every missing database-side prerequisite is rejected with fixed text."""
    with pytest.raises(
        PostgresRestoreApplicationReadinessError,
        match=rf"^PostgreSQL restore target {message}$",
    ):
        _inspect(row)


def test_restore_application_readiness_bounds_database_failure() -> None:
    """Lower-layer database diagnostics never enter the package error surface."""
    connection = _Connection(_Cursor(fail=True))

    with pytest.raises(
        PostgresRestoreApplicationReadinessError,
        match="^PostgreSQL restore application readiness could not be inspected$",
    ) as exc_info:
        inspect_postgres_restore_application_readiness(connection)

    assert "secret database detail" not in str(exc_info.value)


def test_restore_application_readiness_bounds_invalid_connection() -> None:
    """An invalid caller-owned connection also fails through the fixed boundary."""
    with pytest.raises(
        PostgresRestoreApplicationReadinessError,
        match="^PostgreSQL restore application readiness could not be inspected$",
    ):
        inspect_postgres_restore_application_readiness(object())


def test_restore_application_readiness_preserves_process_control() -> None:
    """Process-control signals are not rewritten as ordinary database failures."""

    class _ProcessControlConnection:
        def cursor(self) -> Any:
            raise KeyboardInterrupt

    with pytest.raises(KeyboardInterrupt):
        inspect_postgres_restore_application_readiness(_ProcessControlConnection())
