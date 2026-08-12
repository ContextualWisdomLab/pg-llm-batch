# SPDX-License-Identifier: Apache-2.0
"""Regression tests for least-privilege pg_tiktoken runtime readiness."""

from __future__ import annotations

from pg_llm_batch import token_counter as tc_mod
from pg_llm_batch.token_counter import TokenCounter


class _ProbeCursor:
    """Record runtime readiness SQL and return an installed-function projection."""

    def __init__(self, connection: "_ProbeConnection") -> None:
        self.connection = connection

    def __enter__(self) -> "_ProbeCursor":
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def execute(self, sql: str, params: object = None) -> None:
        self.connection.executions.append((sql, params))

    def fetchone(self) -> tuple[bool, bool, bool]:
        return (True, True, True)


class _ProbeConnection:
    """Minimal Psycopg connection double for a runtime capability probe."""

    def __init__(self) -> None:
        self.closed = False
        self.autocommit = False
        self.executions: list[tuple[str, object]] = []
        self.commit_calls = 0
        self.close_calls = 0

    def cursor(self) -> _ProbeCursor:
        return _ProbeCursor(self)

    def commit(self) -> None:
        self.commit_calls += 1

    def close(self) -> None:
        self.close_calls += 1
        self.closed = True


class _ProbePsycopg:
    """Return one inspectable connection without granting installation authority."""

    def __init__(self) -> None:
        self.connection = _ProbeConnection()
        self.connect_calls = 0

    def connect(self, _dsn: str) -> _ProbeConnection:
        self.connect_calls += 1
        return self.connection


def test_runtime_pg_tiktoken_readiness_never_installs_extensions(monkeypatch) -> None:
    """Ordinary token counting must inspect capability without executing DDL."""
    driver = _ProbePsycopg()
    monkeypatch.setattr(tc_mod, "psycopg", driver)

    counter = TokenCounter("postgresql://database")

    assert counter._pg_available is True
    assert driver.connect_calls == 1
    statements = [sql.upper() for sql, _params in driver.connection.executions]
    assert statements
    assert all("CREATE EXTENSION" not in sql for sql in statements)
    assert driver.connection.commit_calls == 0
