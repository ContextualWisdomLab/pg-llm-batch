# SPDX-License-Identifier: Apache-2.0
"""Tests for bounded tenant-qualified durable reconciliation candidate discovery."""

from __future__ import annotations

import traceback
from typing import Any

import pytest

from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.reconciliation import (
    MAX_RECONCILIATION_CANDIDATES,
    ReconciliationCandidate,
)
from pg_llm_batch.reconciliation_store import (
    load_reconciliation_candidates_in_transaction,
)

_SECRET_SENTINEL = "SECRET-SENTINEL hostile durable candidate"


class RecordingCursor:
    """Minimal cursor double recording tenant binding and candidate query calls."""

    def __init__(self, rows: list[Any]) -> None:
        """Store rows returned by ``fetchall`` and initialize an empty call log."""
        self.rows = rows
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        """Record one parameterized SQL execution."""
        self.calls.append((sql, params))

    def fetchall(self) -> list[Any]:
        """Return the configured candidate rows."""
        return list(self.rows)


class _HostileTenantScope(str):
    """Represent forged tenant text that must be rejected before database work."""

    def __hash__(self) -> int:
        """Raise if the subclass reaches behavior-bearing identity operations."""
        raise RuntimeError(_SECRET_SENTINEL)


class _HostileCandidateRow(tuple[Any, ...]):
    """Execute caller-controlled code if a row subclass is inspected."""

    def __len__(self) -> int:
        """Raise instead of supplying a trustworthy persisted row shape."""
        raise RuntimeError(_SECRET_SENTINEL)


class _HostileEndpointAlias(str):
    """Execute caller-controlled code if persisted alias subclasses are trusted."""

    def strip(self, _chars: str | None = None) -> str:
        """Raise instead of supplying a trustworthy canonical alias."""
        raise RuntimeError(_SECRET_SENTINEL)


class _HostileRemoteBatchId(str):
    """Represent a forged persisted resource-ID subclass."""


def _rendered_exception(error: BaseException) -> str:
    """Render one traceback for confidentiality assertions."""
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


def test_load_reconciliation_candidates_binds_tenant_and_orders_oldest_first():
    """Selection must bind tenant RLS before a bounded oldest-observation query."""
    cursor = RecordingCursor(
        [
            ("gateway-a", "batch-1"),
            ("gateway-b", "batch-2"),
        ]
    )

    candidates = load_reconciliation_candidates_in_transaction(
        cursor,
        "tenant-a",
        max_candidates=2,
    )

    assert candidates == (
        ReconciliationCandidate("gateway-a", "batch-1"),
        ReconciliationCandidate("gateway-b", "batch-2"),
    )
    assert len(cursor.calls) == 2
    tenant_sql, tenant_params = cursor.calls[0]
    assert "set_config('pg_llm_batch.tenant_scope'" in tenant_sql
    assert tenant_params == ("tenant-a",)

    query_sql, query_params = cursor.calls[1]
    assert "FROM llm_remote_batch_jobs" in query_sql
    assert "WHERE tenant_scope = %s" in query_sql
    assert "ORDER BY last_observed_at ASC" in query_sql
    assert "endpoint_alias ASC" in query_sql
    assert "remote_batch_id ASC" in query_sql
    assert "LIMIT %s" in query_sql
    assert query_params == ("tenant-a", 2)


@pytest.mark.parametrize(
    "max_candidates",
    [0, True, MAX_RECONCILIATION_CANDIDATES + 1, "1"],
)
def test_candidate_budget_fails_before_database_work(max_candidates: Any):
    """Malformed or excessive selection budgets must fail before cursor activity."""
    cursor = RecordingCursor([])

    with pytest.raises(ValidationError) as caught:
        load_reconciliation_candidates_in_transaction(
            cursor,
            "tenant-a",
            max_candidates=max_candidates,
        )

    assert cursor.calls == []
    assert caught.value.details["value"] == "<redacted>"
    assert str(max_candidates) not in str(caught.value)


@pytest.mark.parametrize("max_candidates", [1, MAX_RECONCILIATION_CANDIDATES])
def test_candidate_budget_accepts_inclusive_bounds(max_candidates: int) -> None:
    """Both documented candidate-budget boundaries must reach the durable query."""
    cursor = RecordingCursor([])

    assert (
        load_reconciliation_candidates_in_transaction(
            cursor,
            "tenant-a",
            max_candidates=max_candidates,
        )
        == ()
    )
    assert len(cursor.calls) == 2
    assert cursor.calls[1][1] == ("tenant-a", max_candidates)


def test_invalid_tenant_scope_fails_before_database_work():
    """Untrusted tenant text must never reach tenant-context or candidate SQL."""
    cursor = RecordingCursor([])

    with pytest.raises(ValidationError):
        load_reconciliation_candidates_in_transaction(
            cursor,
            "../tenant",
            max_candidates=1,
        )

    assert cursor.calls == []


def test_hostile_tenant_scope_subclass_fails_before_database_work() -> None:
    """Tenant authority must use an exact built-in string before cursor work."""
    cursor = RecordingCursor([])
    tenant_scope = _HostileTenantScope("tenant-a")

    with pytest.raises(ValidationError) as caught:
        load_reconciliation_candidates_in_transaction(
            cursor,
            tenant_scope,
            max_candidates=1,
        )

    assert cursor.calls == []
    assert caught.value.details["field"] == "tenant_scope"
    assert caught.value.details["value"] == "<redacted>"
    assert _SECRET_SENTINEL not in _rendered_exception(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_invalid_persisted_candidate_is_redacted():
    """Corrupt durable identifiers must not escape through validation evidence."""
    sentinel = "secret/provider/path"
    cursor = RecordingCursor([("gateway-a", sentinel)])

    with pytest.raises(ValidationError) as caught:
        load_reconciliation_candidates_in_transaction(
            cursor,
            "tenant-a",
            max_candidates=1,
        )

    assert sentinel not in str(caught.value)
    assert caught.value.details["value"] == "<redacted>"


def test_persisted_endpoint_alias_must_already_be_canonical():
    """Durable key corruption must fail closed instead of changing endpoint identity."""
    sentinel = " gateway-a "
    cursor = RecordingCursor([(sentinel, "batch-1")])

    with pytest.raises(ValidationError) as caught:
        load_reconciliation_candidates_in_transaction(
            cursor,
            "tenant-a",
            max_candidates=1,
        )

    assert sentinel not in str(caught.value)
    assert caught.value.details["value"] == "<redacted>"


@pytest.mark.parametrize("malformed_row", ["not-a-row", ["only-one-field"]])
def test_malformed_persisted_candidate_shape_is_redacted(malformed_row: Any):
    """Malformed durable row shapes must fail closed without reflecting row data."""
    cursor = RecordingCursor([malformed_row])

    with pytest.raises(ValidationError) as caught:
        load_reconciliation_candidates_in_transaction(
            cursor,
            "tenant-a",
            max_candidates=1,
        )

    assert str(malformed_row) not in str(caught.value)
    assert caught.value.details["value"] == "<redacted>"


@pytest.mark.parametrize(
    "row",
    [
        _HostileCandidateRow(("gateway-a", "batch-1")),
        (_HostileEndpointAlias("gateway-a"), "batch-1"),
        ("gateway-a", _HostileRemoteBatchId("batch-1")),
    ],
)
def test_hostile_persisted_candidate_subclasses_are_bounded(row: Any) -> None:
    """Persisted rows and identities must use exact database primitive types."""
    cursor = RecordingCursor([row])

    with pytest.raises(ValidationError) as caught:
        load_reconciliation_candidates_in_transaction(
            cursor,
            "tenant-a",
            max_candidates=1,
        )

    assert caught.value.details["field"] == "reconciliation_candidate"
    assert caught.value.details["value"] == "<redacted>"
    assert _SECRET_SENTINEL not in _rendered_exception(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_empty_candidate_page_is_a_valid_bounded_result():
    """A tenant with no durable lifecycle rows should return an empty tuple."""
    cursor = RecordingCursor([])

    assert (
        load_reconciliation_candidates_in_transaction(
            cursor,
            "tenant-a",
            max_candidates=1,
        )
        == ()
    )
