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


def test_add_entry_rejects_forged_jsonl_byte_accounting_without_mutation() -> None:
    """A caller cannot under-report JSONL bytes to bypass the file-size ceiling."""
    accumulator = BatchAccumulator(_CounterLimits(), "model")
    before = _snapshot(accumulator)

    with pytest.raises(ValidationError, match="max_bytes=10"):
        accumulator.add_entry(
            "forged-byte-count",
            "abcdefghij",
            tokens=1,
            byte_size=1,
        )

    assert _snapshot(accumulator) == before


def test_add_entry_counts_actual_jsonl_bytes_across_multiple_records() -> None:
    """Aggregate bytes cannot be reduced by repeatedly under-reporting each record."""
    accumulator = BatchAccumulator(
        _CounterLimits(),
        "model",
        max_records=10,
        max_bytes=10,
    )
    for index in range(3):
        accumulator.add_entry(
            f"record-{index}",
            "{}",
            tokens=1,
            byte_size=1,
        )

    assert accumulator.byte_size == 9
    before = _snapshot(accumulator)
    with pytest.raises(ValidationError, match="max_bytes=10"):
        accumulator.add_entry("record-overflow", "{}", tokens=1, byte_size=1)
    assert _snapshot(accumulator) == before


def test_add_entry_rejects_embedded_jsonl_record_delimiters_without_mutation() -> None:
    """One accumulator entry must not smuggle additional physical JSONL records."""
    accumulator = BatchAccumulator(
        _CounterLimits(),
        "model",
        max_records=1,
        max_bytes=100,
    )

    for json_line in ('{"first":1}\n{"second":2}', '{"first":1}\r{"second":2}'):
        before = _snapshot(accumulator)
        with pytest.raises(
            ValidationError,
            match="single physical JSONL record",
        ) as error:
            accumulator.add_entry(
                "embedded-record-delimiter",
                json_line,
                tokens=1,
                byte_size=1,
            )
        assert error.value.details == {
            "field": "json_line",
            "value": "<provided>",
            "reason": "must be a single physical JSONL record without CR/LF",
        }
        assert _snapshot(accumulator) == before


def test_add_entry_rejects_behavior_bearing_jsonl_text_before_use() -> None:
    """Caller-controlled str subclasses must not execute before record validation."""

    class BehaviorBearingStr(str):
        def __contains__(self, _item: object) -> bool:
            raise AssertionError("caller containment must not run")

        def encode(self, *_args: object, **_kwargs: object) -> bytes:
            raise AssertionError("caller encoding must not run")

    accumulator = BatchAccumulator(
        _CounterLimits(),
        "model",
        max_records=1,
        max_bytes=100,
    )
    before = _snapshot(accumulator)

    with pytest.raises(ValidationError, match="single physical JSONL record") as error:
        accumulator.add_entry(
            "behavior-bearing-jsonl",
            BehaviorBearingStr("{}"),
            tokens=1,
            byte_size=1,
        )

    assert error.value.details == {
        "field": "json_line",
        "value": "<provided>",
        "reason": "must be a single physical JSONL record without CR/LF",
    }
    assert _snapshot(accumulator) == before
