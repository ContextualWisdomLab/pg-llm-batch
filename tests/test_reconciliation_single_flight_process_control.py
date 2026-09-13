# SPDX-License-Identifier: Apache-2.0
"""Process-control regressions for reconciliation single-flight cleanup."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.reconciliation import ReconciliationCandidate
from pg_llm_batch.reconciliation_single_flight import (
    ReconciliationSingleFlightError,
    reconciliation_single_flight,
)


class _ReleaseFailureCursor:
    """Acquire one advisory lock and then fail closed when release is checked."""

    def __init__(self) -> None:
        """Start with no recorded advisory-lock operations."""
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self.results: list[tuple[bool]] = [(True,), (False,)]

    def execute(self, sql: str, params: tuple[Any, ...]) -> None:
        """Record one parameterized advisory-lock operation."""
        self.calls.append((sql, params))

    def fetchone(self) -> tuple[bool] | None:
        """Return acquisition success followed by unconfirmed release."""
        return self.results.pop(0) if self.results else None


@pytest.mark.parametrize("signal_type", [KeyboardInterrupt, SystemExit])
def test_release_failure_does_not_mask_process_control_signal(
    signal_type: type[BaseException],
) -> None:
    """Cleanup failure must stay bounded without replacing process control."""
    cursor = _ReleaseFailureCursor()
    signal = signal_type("process control sentinel")

    with pytest.raises(signal_type) as caught:
        with reconciliation_single_flight(
            cursor,
            "tenant-a",
            ReconciliationCandidate("gateway-a", "batch-1"),
        ) as acquired:
            assert acquired is True
            raise signal

    assert caught.value is signal
    assert len(cursor.calls) == 2
    assert "pg_advisory_unlock(%s)" in cursor.calls[1][0]
    release_error = caught.value.__cause__
    assert type(release_error) is ReconciliationSingleFlightError
    assert release_error.details == {
        "phase": "release",
        "reason": "lock_release_not_confirmed",
    }
