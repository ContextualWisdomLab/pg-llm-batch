# SPDX-License-Identifier: Apache-2.0
"""Regression tests for the bounded reconciliation-store fetch boundary."""

from __future__ import annotations

from typing import Any

import pytest

import pg_llm_batch.reconciliation_store as reconciliation_store
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
