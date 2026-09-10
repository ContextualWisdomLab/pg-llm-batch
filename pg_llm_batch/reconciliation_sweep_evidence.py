# SPDX-License-Identifier: Apache-2.0
"""Content-free operator evidence for one bounded reconciliation sweep."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .exceptions import ValidationError
from .reconciliation import MAX_RECONCILIATION_CANDIDATES


def _invalid_evidence(reason: str) -> ValidationError:
    """Build a redacted validation error for untrusted sweep-count evidence."""
    return ValidationError(
        field="reconciliation_sweep_evidence",
        value="<redacted>",
        reason=reason,
        message="Reconciliation sweep evidence is invalid",
    )


def _validate_count(value: Any) -> int:
    """Return one exact bounded non-negative integer or fail closed."""
    if (
        type(value) is not int
        or value < 0
        or value > MAX_RECONCILIATION_CANDIDATES
    ):
        raise _invalid_evidence(
            "counts must be exact non-negative integers within the reconciliation budget"
        )
    return value


@dataclass(frozen=True, slots=True)
class ReconciliationSweepEvidence:
    """Record fixed-schema, count-only evidence for one reconciliation sweep."""

    candidate_count: int
    attempted_count: int
    applied_count: int
    deferred_count: int
    failed_count: int

    def __post_init__(self) -> None:
        """Validate bounded counts and their internal accounting invariants."""
        for value in (
            self.candidate_count,
            self.attempted_count,
            self.applied_count,
            self.deferred_count,
            self.failed_count,
        ):
            _validate_count(value)
        if self.attempted_count > self.candidate_count:
            raise _invalid_evidence("attempted count cannot exceed candidate count")
        if self.applied_count + self.deferred_count + self.failed_count != self.attempted_count:
            raise _invalid_evidence(
                "applied, deferred, and failed counts must partition attempted work"
            )

    def to_mapping(self) -> dict[str, int]:
        """Return a fixed count-only mapping suitable for metrics or audit sinks."""
        return {
            "candidate_count": self.candidate_count,
            "attempted_count": self.attempted_count,
            "applied_count": self.applied_count,
            "deferred_count": self.deferred_count,
            "failed_count": self.failed_count,
        }
