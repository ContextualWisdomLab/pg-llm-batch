# SPDX-License-Identifier: Apache-2.0
"""Tests for tenant-qualified cross-process reconciliation single-flight locks."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.reconciliation import ReconciliationCandidate
from pg_llm_batch.reconciliation_single_flight import (
    ReconciliationSingleFlightError,
    reconciliation_single_flight,
)


class RecordingCursor:
    """Minimal cursor double recording advisory-lock SQL and bounded results."""

    def __init__(
        self,
        results: list[Any],
        *,
        fail_execute_at: int | None = None,
        execute_error: Exception | None = None,
    ) -> None:
        """Store fetch results plus an optional deterministic execute failure."""
        self.results = list(results)
        self.fail_execute_at = fail_execute_at
        self.execute_error = execute_error or RuntimeError("database sentinel secret")
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        """Record one parameterized SQL execution or raise the configured failure."""
        self.calls.append((sql, params))
        if self.fail_execute_at == len(self.calls):
            raise self.execute_error

    def fetchone(self) -> Any:
        """Return the next configured database result."""
        return self.results.pop(0) if self.results else None


def test_single_flight_acquires_and_releases_same_parameterized_lock() -> None:
    """A free identity must hold one session advisory lock for the context body."""
    cursor = RecordingCursor([(True,), (True,)])
    candidate = ReconciliationCandidate("gateway-a", "batch-1")

    with reconciliation_single_flight(cursor, "tenant-a", candidate) as acquired:
        assert acquired is True
        assert len(cursor.calls) == 1

    assert len(cursor.calls) == 2
    acquire_sql, acquire_params = cursor.calls[0]
    release_sql, release_params = cursor.calls[1]
    assert "pg_try_advisory_lock(%s)" in acquire_sql
    assert "pg_advisory_unlock(%s)" in release_sql
    assert acquire_params == release_params
    assert len(acquire_params) == 1
    assert type(acquire_params[0]) is int
    assert -(1 << 63) <= acquire_params[0] < (1 << 63)
    assert "tenant-a" not in acquire_sql
    assert "gateway-a" not in acquire_sql
    assert "batch-1" not in acquire_sql


def test_single_flight_contention_returns_false_without_unlock() -> None:
    """A lock owned by another database session must defer without false release."""
    cursor = RecordingCursor([(False,)])

    with reconciliation_single_flight(
        cursor,
        "tenant-a",
        ReconciliationCandidate("gateway-a", "batch-1"),
    ) as acquired:
        assert acquired is False

    assert len(cursor.calls) == 1
    assert "pg_try_advisory_lock(%s)" in cursor.calls[0][0]


def test_single_flight_releases_when_context_body_raises() -> None:
    """Caller failure must not leak an acquired session advisory lock."""
    cursor = RecordingCursor([(True,), (True,)])

    with pytest.raises(ValueError, match="caller failure"):
        with reconciliation_single_flight(
            cursor,
            "tenant-a",
            ReconciliationCandidate("gateway-a", "batch-1"),
        ) as acquired:
            assert acquired is True
            raise ValueError("caller failure")

    assert len(cursor.calls) == 2
    assert "pg_advisory_unlock(%s)" in cursor.calls[1][0]


@pytest.mark.parametrize(
    ("tenant_scope", "candidate"),
    [
        ("../tenant", ReconciliationCandidate("gateway-a", "batch-1")),
        ("tenant-a", ReconciliationCandidate("\x00gateway", "batch-1")),
        ("tenant-a", ReconciliationCandidate("gateway-a", "secret/provider/path")),
    ],
)
def test_single_flight_invalid_identity_fails_before_database_work(
    tenant_scope: str,
    candidate: ReconciliationCandidate,
) -> None:
    """Untrusted identity text must fail closed without cursor or reflected content."""
    cursor = RecordingCursor([])

    with pytest.raises(ValidationError) as caught:
        with reconciliation_single_flight(cursor, tenant_scope, candidate):
            pytest.fail("invalid identity must never enter the context body")

    assert cursor.calls == []
    assert caught.value.details["value"] == "<redacted>"
    assert tenant_scope not in str(caught.value)
    assert candidate.endpoint_alias not in str(caught.value)
    assert candidate.remote_batch_id not in str(caught.value)


def test_single_flight_key_is_tenant_and_provider_identity_qualified() -> None:
    """Distinct trusted identities must not intentionally share advisory-lock keys."""
    candidates = (
        ("tenant-a", ReconciliationCandidate("gateway-a", "batch-1")),
        ("tenant-b", ReconciliationCandidate("gateway-a", "batch-1")),
        ("tenant-a", ReconciliationCandidate("gateway-b", "batch-1")),
        ("tenant-a", ReconciliationCandidate("gateway-a", "batch-2")),
    )
    keys: list[int] = []

    for tenant_scope, candidate in candidates:
        cursor = RecordingCursor([(False,)])
        with reconciliation_single_flight(cursor, tenant_scope, candidate) as acquired:
            assert acquired is False
        keys.append(cursor.calls[0][1][0])

    assert len(set(keys)) == len(keys)


def test_single_flight_normalizes_endpoint_alias_before_keying() -> None:
    """Equivalent endpoint aliases must contend on one canonical lock identity."""
    keys: list[int] = []
    for endpoint_alias in ("gateway-a", "  gateway-a  "):
        cursor = RecordingCursor([(False,)])
        with reconciliation_single_flight(
            cursor,
            "tenant-a",
            ReconciliationCandidate(endpoint_alias, "batch-1"),
        ) as acquired:
            assert acquired is False
        keys.append(cursor.calls[0][1][0])

    assert keys[0] == keys[1]


@pytest.mark.parametrize("result", [None, (), (1,), (True, False), "true"])
def test_single_flight_invalid_acquire_result_fails_closed(result: Any) -> None:
    """Malformed database lock evidence must never be interpreted as acquisition."""
    cursor = RecordingCursor([result])

    with pytest.raises(ReconciliationSingleFlightError) as caught:
        with reconciliation_single_flight(
            cursor,
            "tenant-a",
            ReconciliationCandidate("gateway-a", "batch-1"),
        ):
            pytest.fail("malformed lock evidence must not enter the context body")

    assert caught.value.details == {
        "phase": "acquire",
        "reason": "invalid_database_result",
    }


def test_single_flight_redacts_database_acquire_failure() -> None:
    """Lower-layer acquisition diagnostics must not escape package evidence."""
    sentinel = "postgres password=secret"
    cursor = RecordingCursor(
        [],
        fail_execute_at=1,
        execute_error=RuntimeError(sentinel),
    )

    with pytest.raises(ReconciliationSingleFlightError) as caught:
        with reconciliation_single_flight(
            cursor,
            "tenant-a",
            ReconciliationCandidate("gateway-a", "batch-1"),
        ):
            pytest.fail("failed acquisition must not enter the context body")

    assert caught.value.details == {
        "phase": "acquire",
        "reason": "database_operation_failed",
    }
    assert sentinel not in str(caught.value)


@pytest.mark.parametrize("release_result", [None, (), (False,), (1,), (True, False)])
def test_single_flight_unconfirmed_release_fails_closed(release_result: Any) -> None:
    """An acquired session lock needs explicit positive release evidence."""
    cursor = RecordingCursor([(True,), release_result])

    with pytest.raises(ReconciliationSingleFlightError) as caught:
        with reconciliation_single_flight(
            cursor,
            "tenant-a",
            ReconciliationCandidate("gateway-a", "batch-1"),
        ) as acquired:
            assert acquired is True

    assert caught.value.details == {
        "phase": "release",
        "reason": "lock_release_not_confirmed",
    }


def test_single_flight_redacts_database_release_failure() -> None:
    """Lower-layer release diagnostics must not escape package evidence."""
    sentinel = "postgres release secret"
    cursor = RecordingCursor(
        [(True,)],
        fail_execute_at=2,
        execute_error=RuntimeError(sentinel),
    )

    with pytest.raises(ReconciliationSingleFlightError) as caught:
        with reconciliation_single_flight(
            cursor,
            "tenant-a",
            ReconciliationCandidate("gateway-a", "batch-1"),
        ) as acquired:
            assert acquired is True

    assert caught.value.details == {
        "phase": "release",
        "reason": "database_operation_failed",
    }
    assert sentinel not in str(caught.value)
