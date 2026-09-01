# SPDX-License-Identifier: Apache-2.0
"""Regression tests for BatchAccumulator mutation-boundary invariants."""

from __future__ import annotations

import pytest

from pg_llm_batch.exceptions import TokenLimitExceededError, ValidationError
from pg_llm_batch.token_counter import BatchAccumulator


class _CounterLimits:
    """Supply only the immutable resource ceilings the accumulator consumes."""

    effective_limit = 10
    azure_max_records_per_file = 2
    azure_max_bytes_per_file = 10


def _snapshot(accumulator: BatchAccumulator) -> tuple[object, ...]:
    """Capture all mutable accumulator state for rejection assertions."""
    return (
        list(accumulator.entries),
        accumulator.total_tokens,
        accumulator.record_count,
        accumulator.byte_size,
    )


def test_add_entry_rejects_aggregate_limit_bypass_without_mutation() -> None:
    """Mutation must enforce token, byte, and record ceilings without a probe call."""
    token_acc = BatchAccumulator(_CounterLimits(), "model")
    token_acc.add_entry("token-seed", "{}", tokens=6, byte_size=1)
    before = _snapshot(token_acc)
    with pytest.raises(TokenLimitExceededError):
        token_acc.add_entry("token-overflow", "{}", tokens=5, byte_size=1)
    assert _snapshot(token_acc) == before

    byte_acc = BatchAccumulator(_CounterLimits(), "model")
    byte_acc.add_entry("byte-seed", "{}", tokens=1, byte_size=6)
    before = _snapshot(byte_acc)
    with pytest.raises(ValidationError, match="max_bytes=10"):
        byte_acc.add_entry("byte-overflow", "{}", tokens=1, byte_size=5)
    assert _snapshot(byte_acc) == before

    record_acc = BatchAccumulator(_CounterLimits(), "model")
    record_acc.add_entry("record-1", "{}", tokens=1, byte_size=1)
    record_acc.add_entry("record-2", "{}", tokens=1, byte_size=1)
    before = _snapshot(record_acc)
    with pytest.raises(ValidationError, match="max_records=2"):
        record_acc.add_entry("record-overflow", "{}", tokens=1, byte_size=1)
    assert _snapshot(record_acc) == before
