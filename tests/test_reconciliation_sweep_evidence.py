# SPDX-License-Identifier: Apache-2.0
"""Tests for bounded content-free reconciliation sweep evidence."""

from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.reconciliation import MAX_RECONCILIATION_CANDIDATES
from pg_llm_batch.reconciliation_sweep_evidence import ReconciliationSweepEvidence


def test_sweep_evidence_serializes_only_bounded_counts() -> None:
    """Operator evidence must expose only fixed count categories."""
    evidence = ReconciliationSweepEvidence(
        candidate_count=5,
        attempted_count=4,
        applied_count=2,
        deferred_count=1,
        failed_count=1,
    )

    assert evidence.to_mapping() == {
        "candidate_count": 5,
        "attempted_count": 4,
        "applied_count": 2,
        "deferred_count": 1,
        "failed_count": 1,
    }


def test_sweep_evidence_is_immutable() -> None:
    """Evidence already handed to an audit sink must not be mutable in place."""
    evidence = ReconciliationSweepEvidence(
        candidate_count=1,
        attempted_count=1,
        applied_count=1,
        deferred_count=0,
        failed_count=0,
    )

    with pytest.raises(FrozenInstanceError):
        evidence.applied_count = 0  # type: ignore[misc]


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("candidate_count", -1),
        ("attempted_count", True),
        ("applied_count", MAX_RECONCILIATION_CANDIDATES + 1),
        ("deferred_count", 1.0),
        ("failed_count", "1"),
    ],
)
def test_sweep_evidence_rejects_untrusted_count_types_and_ranges(
    field_name: str,
    value: object,
) -> None:
    """Every evidence count must be an exact bounded non-negative integer."""
    values: dict[str, object] = {
        "candidate_count": 1,
        "attempted_count": 1,
        "applied_count": 1,
        "deferred_count": 0,
        "failed_count": 0,
    }
    values[field_name] = value

    with pytest.raises(ValidationError) as caught:
        ReconciliationSweepEvidence(**values)  # type: ignore[arg-type]

    assert caught.value.details["field"] == "reconciliation_sweep_evidence"
    assert caught.value.details["value"] == "<redacted>"


def test_sweep_evidence_rejects_more_attempts_than_candidates() -> None:
    """A sweep cannot claim to attempt more work than its bounded candidate page."""
    with pytest.raises(ValidationError) as caught:
        ReconciliationSweepEvidence(
            candidate_count=1,
            attempted_count=2,
            applied_count=2,
            deferred_count=0,
            failed_count=0,
        )

    assert caught.value.details["value"] == "<redacted>"


def test_sweep_evidence_requires_outcomes_to_partition_attempts() -> None:
    """Applied, deferred, and failed counts must exactly partition attempted work."""
    with pytest.raises(ValidationError) as caught:
        ReconciliationSweepEvidence(
            candidate_count=3,
            attempted_count=3,
            applied_count=1,
            deferred_count=1,
            failed_count=0,
        )

    assert caught.value.details["value"] == "<redacted>"


def test_sweep_evidence_accepts_empty_and_maximum_pages() -> None:
    """No-work and full-budget sweeps are valid bounded operator evidence."""
    assert ReconciliationSweepEvidence(0, 0, 0, 0, 0).attempted_count == 0
    evidence = ReconciliationSweepEvidence(
        MAX_RECONCILIATION_CANDIDATES,
        MAX_RECONCILIATION_CANDIDATES,
        MAX_RECONCILIATION_CANDIDATES,
        0,
        0,
    )
    assert evidence.candidate_count == MAX_RECONCILIATION_CANDIDATES
