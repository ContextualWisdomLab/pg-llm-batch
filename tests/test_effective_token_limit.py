# SPDX-License-Identifier: Apache-2.0
"""Validation tests for per-run batch token limits."""

from __future__ import annotations

import pytest

from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.orchestrator import (
    PostgresBatchOrchestrator,
    _validate_effective_token_limit,
)


@pytest.mark.parametrize("value", [1, 128_000, 5_000_000_000])
def test_positive_integer_token_limits_are_preserved(value):
    """Valid stricter limits retain exact integer semantics."""
    assert _validate_effective_token_limit(value) == value


def test_missing_token_limit_preserves_configured_default():
    """An omitted override remains distinguishable from a concrete limit."""
    assert _validate_effective_token_limit(None) is None


@pytest.mark.parametrize("value", [0, -1, True, False, 1.5, "100", object()])
def test_invalid_token_limits_raise_structured_validation_errors(value):
    """Coercive, disabled, fractional, and non-positive values fail closed."""
    with pytest.raises(ValidationError, match="effective_token_limit") as exc_info:
        _validate_effective_token_limit(value)

    assert exc_info.value.details == {
        "field": "effective_token_limit",
        "value": value,
        "reason": "must be a positive integer when provided",
    }


def test_prepare_rejects_invalid_limit_before_batch_or_database_lookup():
    """Invalid limits consume no database connection or batch lookup work."""
    orchestrator = object.__new__(PostgresBatchOrchestrator)
    lookup_calls = []
    orchestrator._resolve_batch_uuid = lambda value: lookup_calls.append(value)

    with pytest.raises(ValidationError, match="effective_token_limit"):
        orchestrator.prepare_batches(
            batch_uuid="batch-key",
            effective_token_limit=0,
        )

    assert lookup_calls == []
