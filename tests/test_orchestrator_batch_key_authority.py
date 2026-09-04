# SPDX-License-Identifier: Apache-2.0
"""Regression tests for exact orchestrator batch-selector authority."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.orchestrator import PostgresBatchOrchestrator


class _StringifiableUuid:
    """Hostile non-string object whose text happens to be a valid UUID."""

    def __str__(self) -> str:
        """Return a valid UUID string to expose implicit coercion."""
        return "00000000-0000-0000-0000-000000000123"


@pytest.mark.parametrize(
    "invalid_key",
    [
        True,
        False,
        b"batch-key",
        ["batch-key"],
        {"batch": "key"},
        _StringifiableUuid(),
    ],
)
def test_non_string_batch_key_fails_before_database_io(
    invalid_key: object,
) -> None:
    """Only exact strings may choose UUID/path authority before PostgreSQL access."""
    database_calls: list[str] = []

    def forbidden_connect(_dsn: str) -> Any:
        database_calls.append("connect")
        raise AssertionError("database I/O must not occur for a non-string selector")

    driver = SimpleNamespace(connect=forbidden_connect)
    orchestrator = PostgresBatchOrchestrator(
        "postgresql://example",
        postgres_driver=driver,
    )

    with pytest.raises(ValidationError) as caught:
        orchestrator._resolve_batch_uuid(invalid_key)  # type: ignore[arg-type]

    assert caught.value.details["field"] == "batch_uuid"
    assert caught.value.details["value"] == "<redacted>"
    assert database_calls == []


def test_valid_uuid_string_preserves_exact_selector_without_database_io() -> None:
    """A valid exact UUID string must remain the direct authoritative selector."""
    database_calls: list[str] = []
    driver = SimpleNamespace(
        connect=lambda _dsn: database_calls.append("connect")
        or (_ for _ in ()).throw(AssertionError("unexpected database lookup"))
    )
    orchestrator = PostgresBatchOrchestrator(
        "postgresql://example",
        postgres_driver=driver,
    )
    batch_key = "00000000-0000-0000-0000-000000000123"

    assert orchestrator._resolve_batch_uuid(batch_key) == batch_key
    assert database_calls == []


class _LookupCursor:
    """Capture the exact input-file-path lookup key."""

    def __init__(self, lookup_values: list[str]) -> None:
        """Retain the caller-owned capture list."""
        self.lookup_values = lookup_values

    def __enter__(self) -> "_LookupCursor":
        """Return this cursor from its context manager."""
        return self

    def __exit__(self, *_exc: Any) -> None:
        """Leave the cursor context without suppressing errors."""

    def execute(self, _sql: str, params: tuple[str]) -> None:
        """Capture the exact parameter passed to the path-key lookup."""
        self.lookup_values.append(params[0])

    def fetchone(self) -> tuple[str]:
        """Return one deterministic resolved batch UUID."""
        return ("00000000-0000-0000-0000-000000000999",)


class _LookupConnection:
    """Provide one observable path-key lookup cursor."""

    def __init__(self, lookup_values: list[str]) -> None:
        """Retain the lookup capture list."""
        self.lookup_values = lookup_values

    def __enter__(self) -> "_LookupConnection":
        """Return this connection from its context manager."""
        return self

    def __exit__(self, *_exc: Any) -> None:
        """Leave the connection context without suppressing errors."""

    def cursor(self) -> _LookupCursor:
        """Return an observable cursor."""
        return _LookupCursor(self.lookup_values)


def test_exact_non_uuid_string_is_used_as_path_key_without_rewriting() -> None:
    """An exact non-UUID string must retain byte-for-byte path-key identity."""
    lookup_values: list[str] = []
    driver = SimpleNamespace(connect=lambda _dsn: _LookupConnection(lookup_values))
    orchestrator = PostgresBatchOrchestrator(
        "postgresql://example",
        postgres_driver=driver,
    )
    batch_key = "memory://batch/Case-Sensitive-Key"

    assert orchestrator._resolve_batch_uuid(batch_key) == (
        "00000000-0000-0000-0000-000000000999"
    )
    assert lookup_values == [batch_key]
