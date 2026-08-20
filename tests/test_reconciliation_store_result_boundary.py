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
    """Minimal cursor double returning caller-controlled bounded page evidence."""

    def __init__(self, rows: Any) -> None:
        """Store the configured fetch result."""
        self.rows = rows

    def execute(self, _sql: str, _params: tuple[Any, ...]) -> None:
        """Accept the package's parameterized tenant binding and candidate query."""

    def fetchmany(self, _size: int) -> Any:
        """Return the configured database-boundary result unchanged."""
        return self.rows


class _HostileRows(list[Any]):
    """Expose whether a behavior-bearing fetchmany container is iterated."""

    def __init__(self, rows: list[Any]) -> None:
        """Initialize rows and an untouched iteration sentinel."""
        super().__init__(rows)
        self.iterated = False

    def __iter__(self):
        """Mark behavior execution before raising a content-bearing failure."""
        self.iterated = True
        raise RuntimeError("SECRET fetchmany container behavior")


def test_fetchmany_container_subclass_is_rejected_before_iteration() -> None:
    """Behavior-bearing fetchmany containers must fail before their methods execute."""
    rows = _HostileRows([("gateway-a", "batch-1")])

    with pytest.raises(ReconciliationStoreError):
        load_reconciliation_candidates_in_transaction(
            _Cursor(rows),
            "tenant-a",
            max_candidates=1,
        )

    assert rows.iterated is False


def test_fetchmany_result_cannot_exceed_validated_candidate_budget() -> None:
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


def test_oversized_fetchmany_page_is_rejected_before_full_snapshot_copy(
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
            raise AssertionError("oversized fetchmany page was copied")
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


def test_fetchmany_rows_are_snapshotted_before_conversion(
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


def test_overlong_persisted_endpoint_alias_is_rejected_before_normalization(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Overlong durable aliases must fail before any allocating normalization."""
    validator_called = False

    def _unexpected_validator(_value: Any) -> str:
        nonlocal validator_called
        validator_called = True
        raise AssertionError("overlong endpoint alias reached canonical normalization")

    monkeypatch.setattr(
        reconciliation_store,
        "validate_endpoint_alias",
        _unexpected_validator,
    )

    with pytest.raises(ValidationError):
        load_reconciliation_candidates_in_transaction(
            _Cursor([("a" * 129, "batch-1")]),
            "tenant-a",
            max_candidates=1,
        )

    assert validator_called is False


def test_overlong_persisted_remote_batch_id_is_rejected_before_regex_validation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Overlong durable IDs must fail before the regex validation boundary."""
    validator_called = False

    def _unexpected_validator(_value: Any, _field: str) -> str:
        nonlocal validator_called
        validator_called = True
        raise AssertionError("overlong remote batch ID reached regex validation")

    monkeypatch.setattr(
        reconciliation_store,
        "validate_remote_resource_id",
        _unexpected_validator,
    )

    with pytest.raises(ValidationError):
        load_reconciliation_candidates_in_transaction(
            _Cursor([("gateway-a", "b" * 257)]),
            "tenant-a",
            max_candidates=1,
        )

    assert validator_called is False


def test_candidate_retrieval_requests_a_bounded_cursor_page() -> None:
    """Candidate loading must request finite cursor materialization, never fetchall."""

    class _BoundedCursor:
        def __init__(self) -> None:
            self.fetchmany_sizes: list[int] = []
            self.fetchall_called = False

        def execute(self, _sql: str, _params: tuple[Any, ...]) -> None:
            return None

        def fetchmany(self, size: int) -> list[tuple[str, str]]:
            self.fetchmany_sizes.append(size)
            return [("gateway-a", "batch-1")]

        def fetchall(self) -> Any:
            self.fetchall_called = True
            raise AssertionError("unbounded fetchall must not be used")

    cursor = _BoundedCursor()
    candidates = load_reconciliation_candidates_in_transaction(
        cursor,
        "tenant-a",
        max_candidates=1,
    )

    assert [(candidate.endpoint_alias, candidate.remote_batch_id) for candidate in candidates] == [
        ("gateway-a", "batch-1")
    ]
    assert cursor.fetchmany_sizes == [2]
    assert cursor.fetchall_called is False
