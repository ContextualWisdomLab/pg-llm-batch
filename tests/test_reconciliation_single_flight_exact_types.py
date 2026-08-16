# SPDX-License-Identifier: Apache-2.0
"""Hostile-subclass regressions for reconciliation single-flight evidence."""

from __future__ import annotations

import traceback
from typing import Any

import pytest

from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.reconciliation import ReconciliationCandidate
from pg_llm_batch.reconciliation_single_flight import (
    ReconciliationSingleFlightError,
    reconciliation_single_flight,
)

_SECRET_SENTINEL = "SECRET-SENTINEL hostile single-flight evidence"


class _RecordingCursor:
    """Record lock operations while returning configured database evidence."""

    def __init__(self, results: list[Any]) -> None:
        self.results = list(results)
        self.calls: list[tuple[str, tuple[Any, ...]]] = []

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        """Record one parameterized advisory-lock operation."""
        self.calls.append((sql, params))

    def fetchone(self) -> Any:
        """Return the next configured database result."""
        return self.results.pop(0) if self.results else None


class _HostileTenantScope(str):
    """Represent caller-controlled tenant text with executable behavior."""

    def __hash__(self) -> int:
        """Raise if the subclass reaches hashing or set membership."""
        raise RuntimeError(_SECRET_SENTINEL)


class _HostileCandidate(ReconciliationCandidate):
    """Execute caller code if candidate attributes are read before refusal."""

    def __getattribute__(self, name: str) -> Any:
        """Raise instead of supplying a trustworthy endpoint alias."""
        if name == "endpoint_alias":
            raise RuntimeError(_SECRET_SENTINEL)
        return super().__getattribute__(name)


class _HostileLockRow(tuple[Any, ...]):
    """Execute database-row subclass code during result-shape validation."""

    def __len__(self) -> int:
        """Raise instead of supplying a trustworthy result shape."""
        raise RuntimeError(_SECRET_SENTINEL)


def _rendered_exception(error: BaseException) -> str:
    """Render one traceback for confidentiality assertions."""
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


@pytest.mark.parametrize(
    ("tenant_scope", "candidate"),
    [
        (
            _HostileTenantScope("tenant-a"),
            ReconciliationCandidate("gateway-a", "batch-1"),
        ),
        (
            "tenant-a",
            _HostileCandidate("gateway-a", "batch-1"),
        ),
    ],
)
def test_hostile_identity_subclasses_fail_before_database_work(
    tenant_scope: Any,
    candidate: Any,
) -> None:
    """Identity subclasses must not execute before bounded validation."""
    cursor = _RecordingCursor([])

    with pytest.raises(ValidationError) as caught:
        with reconciliation_single_flight(cursor, tenant_scope, candidate):
            pytest.fail("invalid identity must not enter the context body")

    assert caught.value.details["field"] == "reconciliation_single_flight_identity"
    assert caught.value.details["value"] == "<redacted>"
    assert _SECRET_SENTINEL not in _rendered_exception(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert cursor.calls == []


def test_hostile_lock_row_subclass_is_bounded_database_evidence() -> None:
    """Database result subclasses must not execute during shape validation."""
    cursor = _RecordingCursor([_HostileLockRow((True,))])

    with pytest.raises(ReconciliationSingleFlightError) as caught:
        with reconciliation_single_flight(
            cursor,
            "tenant-a",
            ReconciliationCandidate("gateway-a", "batch-1"),
        ):
            pytest.fail("invalid lock evidence must not enter the context body")

    assert caught.value.details == {
        "phase": "acquire",
        "reason": "invalid_database_result",
    }
    assert _SECRET_SENTINEL not in _rendered_exception(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert len(cursor.calls) == 1
