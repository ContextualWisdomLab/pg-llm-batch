# SPDX-License-Identifier: Apache-2.0
"""Regression tests for bounded durable reconciliation store failures."""

from __future__ import annotations

import traceback
from typing import Any

import pytest

import pg_llm_batch.reconciliation_store as reconciliation_store
from pg_llm_batch.exceptions import PgLlmBatchError
from pg_llm_batch.reconciliation_store import (
    load_reconciliation_candidates_in_transaction,
)

_SECRET = "postgresql://secret-user:secret-password@private-db/internal"
_EXPECTED_MESSAGE = "Reconciliation candidate store operation failed"
_EXPECTED_CODE = "RECONCILIATION_STORE_ERROR"


class _ExplodingRows:
    """Expose secret-bearing behavior if an invalid result container is iterated."""

    def __iter__(self):
        raise RuntimeError(f"{_SECRET} iterate")


class _FailingCursor:
    """Fail at one selected cursor operation with secret-bearing lower-layer text."""

    def __init__(self, *, fail_on: str) -> None:
        self.fail_on = fail_on
        self.execute_calls = 0

    def execute(self, _sql: str, _params: tuple[Any, ...]) -> None:
        self.execute_calls += 1
        phase = "tenant" if self.execute_calls == 1 else "query"
        if self.fail_on == phase:
            raise RuntimeError(f"{_SECRET} {phase}")

    def fetchall(self) -> Any:
        if self.fail_on == "fetch":
            raise RuntimeError(f"{_SECRET} fetch")
        if self.fail_on == "container":
            return _ExplodingRows()
        return [("gateway-a", "batch-1")]


def _rendered(error: BaseException) -> str:
    """Render one traceback for diagnostic-confidentiality assertions."""
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


@pytest.mark.parametrize("fail_on", ["tenant", "query", "fetch", "container"])
def test_store_operational_failures_are_bounded_and_redacted(fail_on: str) -> None:
    """Database operational detail must not escape the package error boundary."""
    cursor = _FailingCursor(fail_on=fail_on)

    with pytest.raises(PgLlmBatchError) as caught:
        load_reconciliation_candidates_in_transaction(
            cursor,
            "tenant-a",
            max_candidates=1,
        )

    assert str(caught.value) == f"[{_EXPECTED_CODE}] {_EXPECTED_MESSAGE}"
    assert caught.value.error_code == _EXPECTED_CODE
    assert caught.value.details == {}
    assert _SECRET not in _rendered(caught.value)


def test_store_row_conversion_failure_is_bounded_and_redacted(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Unexpected internal row-conversion failures must remain content-free."""

    def _explode(_row: Any) -> Any:
        raise RuntimeError(f"{_SECRET} convert")

    monkeypatch.setattr(reconciliation_store, "_candidate_from_persisted_row", _explode)

    with pytest.raises(PgLlmBatchError) as caught:
        load_reconciliation_candidates_in_transaction(
            _FailingCursor(fail_on="none"),
            "tenant-a",
            max_candidates=1,
        )

    assert str(caught.value) == f"[{_EXPECTED_CODE}] {_EXPECTED_MESSAGE}"
    assert caught.value.error_code == _EXPECTED_CODE
    assert caught.value.details == {}
    assert _SECRET not in _rendered(caught.value)


def test_store_does_not_swallow_process_control_baseexceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Process-control exceptions must remain outside both store error wrappers."""

    class InterruptingCursor:
        def execute(self, _sql: str, _params: tuple[Any, ...]) -> None:
            raise KeyboardInterrupt()

    with pytest.raises(KeyboardInterrupt):
        load_reconciliation_candidates_in_transaction(
            InterruptingCursor(),
            "tenant-a",
            max_candidates=1,
        )

    def _interrupt_row(_row: Any) -> Any:
        raise KeyboardInterrupt()

    monkeypatch.setattr(reconciliation_store, "_candidate_from_persisted_row", _interrupt_row)

    with pytest.raises(KeyboardInterrupt):
        load_reconciliation_candidates_in_transaction(
            _FailingCursor(fail_on="none"),
            "tenant-a",
            max_candidates=1,
        )
