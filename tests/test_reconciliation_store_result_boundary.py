# SPDX-License-Identifier: Apache-2.0
"""Regression tests for the bounded reconciliation-store fetch boundary."""

from __future__ import annotations

from typing import Any

import pytest

import pg_llm_batch.reconciliation_store as reconciliation_store
from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.reconciliation_store import (
    ReconciliationStoreError,
    load_reconciliation_candidates_in_transaction,
)


class _Cursor:
    """Minimal cursor double returning caller-controlled fetchall evidence."""

    def __init__(self, rows: Any) -> None:
        """Store the configured fetchall result."""
        self.rows = rows

    def execute(self, _sql: str, _params: tuple[Any, ...]) -> None:
        """Accept the package's parameterized tenant binding and candidate query."""

    def fetchall(self) -> Any:
        """Return the configured database-boundary result unchanged."""
        return self.rows


class _HostileRows(list[Any]):
    """Expose whether a behavior-bearing fetchall container is iterated."""

    def __init__(self, rows: list[Any]) -> None:
        """Initialize rows and an untouched iteration sentinel."""
        super().__init__(rows)
        self.iterated = False

    def __iter__(self):
        """Mark behavior execution before raising a content-bearing failure."""
        self.iterated = True
        raise RuntimeError("SECRET fetchall container behavior")


def test_fetchall_container_subclass_is_rejected_before_iteration() -> None:
    """Behavior-bearing fetchall containers must fail before their methods execute."""
    rows = _HostileRows([("gateway-a", "batch-1")])

    with pytest.raises(ReconciliationStoreError):
        load_reconciliation_candidates_in_transaction(
            _Cursor(rows),
            "tenant-a",
            max_candidates=1,
        )

    assert rows.iterated is False


def test_fetchall_result_cannot_exceed_validated_candidate_budget() -> None:
    """A cursor that violates SQL LIMIT must not widen the package work budget."""
    rows = [
        ("gateway-a", "batch-1"),
        ("gateway-b", "batch-2"),
    ]

    with pytest.raises(ReconciliationStoreError):
        load_reconciliation_candidates_in_transaction(
            _Cursor(rows),
            "tenant-a",
            max_candidates=1,
        )


def test_oversized_fetchall_page_is_rejected_before_full_snapshot_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An oversized exact result page must not be duplicated before budget rejection."""
    rows = [
        ("gateway-a", "batch-1"),
        ("gateway-b", "batch-2"),
    ]
    real_tuple = tuple
    copied_oversized_page = False

    def _bounded_tuple(value: Any) -> tuple[Any, ...]:
        nonlocal copied_oversized_page
        if value is rows:
            copied_oversized_page = True
            raise AssertionError("oversized fetchall page was copied")
        return real_tuple(value)

    monkeypatch.setattr(
        reconciliation_store,
        "tuple",
        _bounded_tuple,
        raising=False,
    )

    with pytest.raises(ReconciliationStoreError):
        load_reconciliation_candidates_in_transaction(
            _Cursor(rows),
            "tenant-a",
            max_candidates=1,
        )

    assert copied_oversized_page is False


def test_fetchall_rows_are_snapshotted_before_conversion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller mutation during conversion must not widen the validated row page."""
    rows = [("gateway-a", "batch-1")]
    converted_rows: list[Any] = []
    original_converter = reconciliation_store._candidate_from_persisted_row

    def _append_during_conversion(row: Any) -> Any:
        converted_rows.append(row)
        if len(converted_rows) == 1:
            rows.append(("gateway-b", "batch-2"))
        return original_converter(row)

    monkeypatch.setattr(
        reconciliation_store,
        "_candidate_from_persisted_row",
        _append_during_conversion,
    )

    candidates = load_reconciliation_candidates_in_transaction(
        _Cursor(rows),
        "tenant-a",
        max_candidates=1,
    )

    assert len(candidates) == 1
    assert len(converted_rows) == 1
    assert len(rows) == 2


def test_mutable_row_is_snapshotted_before_conversion(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller mutation must not rewrite a fetched candidate before validation."""
    fetched_row = ["gateway-a", "batch-1"]
    rows = [fetched_row]
    converted_rows: list[Any] = []
    original_converter = reconciliation_store._candidate_from_persisted_row

    def _mutate_before_conversion(row: Any) -> Any:
        fetched_row[:] = ["gateway-b", "batch-2"]
        converted_rows.append(row)
        return original_converter(row)

    monkeypatch.setattr(
        reconciliation_store,
        "_candidate_from_persisted_row",
        _mutate_before_conversion,
    )

    candidates = load_reconciliation_candidates_in_transaction(
        _Cursor(rows),
        "tenant-a",
        max_candidates=1,
    )

    assert converted_rows == [("gateway-a", "batch-1")]
    assert candidates[0].endpoint_alias == "gateway-a"
    assert candidates[0].remote_batch_id == "batch-1"
    assert fetched_row == ["gateway-b", "batch-2"]


def test_oversized_exact_row_is_rejected_before_snapshot_copy(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid row cardinality must fail before copying unbounded row members."""
    oversized_row = ["gateway-a", "batch-1", "unexpected"]
    real_tuple = tuple
    copied_oversized_row = False

    def _bounded_tuple(value: Any) -> tuple[Any, ...]:
        nonlocal copied_oversized_row
        if value is oversized_row:
            copied_oversized_row = True
            raise AssertionError("oversized persisted row was copied")
        return real_tuple(value)

    monkeypatch.setattr(
        reconciliation_store,
        "tuple",
        _bounded_tuple,
        raising=False,
    )

    with pytest.raises(ValidationError):
        load_reconciliation_candidates_in_transaction(
            _Cursor([oversized_row]),
            "tenant-a",
            max_candidates=1,
        )

    assert copied_oversized_row is False
