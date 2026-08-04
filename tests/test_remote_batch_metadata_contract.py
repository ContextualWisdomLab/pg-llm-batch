# SPDX-License-Identifier: Apache-2.0
"""Regression tests for PostgreSQL-safe provider metadata persistence."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch import db


class _MetadataCursor:
    """Capture lifecycle SQL and bound parameters without a real database."""

    def __init__(self, driver: "_MetadataPsycopg") -> None:
        self.driver = driver

    def __enter__(self) -> "_MetadataCursor":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        """Record one SQL execution for deterministic trust-boundary assertions."""
        self.driver.executions.append((sql, params))


class _MetadataConnection:
    """Expose the connection operations used by lifecycle persistence."""

    def __init__(self, driver: "_MetadataPsycopg") -> None:
        self.driver = driver

    def __enter__(self) -> "_MetadataConnection":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def cursor(self) -> _MetadataCursor:
        """Return a cursor that records rather than executes SQL."""
        return _MetadataCursor(self.driver)

    def commit(self) -> None:
        """Record the explicit lifecycle transaction commit."""
        self.driver.commits += 1


class _MetadataPsycopg:
    """Minimal psycopg replacement for provider metadata contract tests."""

    def __init__(self) -> None:
        self.executions: list[tuple[str, Any]] = []
        self.connections: list[str] = []
        self.commits = 0

    def connect(self, dsn: str) -> _MetadataConnection:
        """Return a recording connection for the supplied DSN."""
        self.connections.append(dsn)
        return _MetadataConnection(self)


@pytest.mark.parametrize(
    "provider_metadata",
    [
        {"metadata_value": "\x00"},
        {"metadata\x00key": "value"},
        {"nested_values": ["safe", "\x00"]},
    ],
    ids=("nul-value", "nul-key", "nested-nul-value"),
)
def test_postgresql_incompatible_nul_metadata_normalizes_to_empty_object(
    monkeypatch: pytest.MonkeyPatch,
    provider_metadata: dict[str, Any],
) -> None:
    """NUL-bearing JSON metadata must fail closed before the jsonb parameter."""
    driver = _MetadataPsycopg()
    monkeypatch.setattr(db, "psycopg", driver)

    snapshot = db.persist_remote_batch_state(
        "postgresql://example",
        "primary",
        {"id": "batch-1", "metadata": provider_metadata},
        observation_order=22,
    )

    assert snapshot["provider_metadata"] == {}
    assert driver.executions[0][1][11] == "{}"
    assert driver.connections == ["postgresql://example"]
    assert driver.commits == 1
