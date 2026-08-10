# SPDX-License-Identifier: Apache-2.0
"""Fail-closed resource-limit contracts for ``BatchAccumulator``."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.token_counter import BatchAccumulator


def _counter(*, max_records: Any = 100, max_bytes: Any = 4096) -> Any:
    """Return the minimal counter authority consumed by ``BatchAccumulator``."""
    return SimpleNamespace(
        effective_limit=1_000,
        azure_max_records_per_file=max_records,
        azure_max_bytes_per_file=max_bytes,
    )


@pytest.mark.parametrize("invalid_value", [True, False, 0, -1, 1.0, "1", [], {}])
def test_explicit_max_records_requires_exact_positive_integer(
    invalid_value: Any,
) -> None:
    """An explicit record ceiling must never be ignored, coerced, or truth-tested."""
    with pytest.raises(ValidationError, match="max_records"):
        BatchAccumulator(_counter(), "model", max_records=invalid_value)


@pytest.mark.parametrize("invalid_value", [True, False, 0, -1, 1.0, "1", [], {}])
def test_explicit_max_bytes_requires_exact_positive_integer(invalid_value: Any) -> None:
    """An explicit byte ceiling must never be ignored, coerced, or truth-tested."""
    with pytest.raises(ValidationError, match="max_bytes"):
        BatchAccumulator(_counter(), "model", max_bytes=invalid_value)


@pytest.mark.parametrize(
    ("field", "counter"),
    [
        ("max_records", _counter(max_records=0)),
        ("max_records", _counter(max_records=True)),
        ("max_bytes", _counter(max_bytes=0)),
        ("max_bytes", _counter(max_bytes=True)),
    ],
)
def test_configured_default_limits_are_validated_after_selection(
    field: str,
    counter: Any,
) -> None:
    """Malformed counter defaults must fail instead of becoming accumulator authority."""
    with pytest.raises(ValidationError, match=field):
        BatchAccumulator(counter, "model")


def test_explicit_positive_limits_override_counter_defaults_exactly() -> None:
    """Reviewed explicit ceilings retain their exact integer values."""
    accumulator = BatchAccumulator(
        _counter(max_records=111, max_bytes=222),
        "model",
        max_records=7,
        max_bytes=8192,
    )

    assert accumulator.max_records == 7
    assert accumulator.max_bytes == 8192
