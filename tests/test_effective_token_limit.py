# SPDX-License-Identifier: Apache-2.0
"""Validation tests for per-run batch token limits."""

from __future__ import annotations

import pytest

from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.orchestrator import (
    PostgresBatchOrchestrator,
    _validate_effective_token_limit,
)


class _HostileInt(int):
    """Integer subclass that must never gain diagnostic rendering authority."""

    def __str__(self):
        """Fail if rejected-value validation invokes caller-controlled rendering."""
        raise AssertionError("rejected numeric subclass was rendered")


@pytest.mark.parametrize("value", [1, 128_000, 5_000_000_000])
def test_positive_integer_token_limits_are_preserved(value):
    """Valid stricter limits retain exact integer semantics."""
    assert _validate_effective_token_limit(value) == value


def test_missing_token_limit_preserves_configured_default():
    """An omitted override remains distinguishable from a concrete limit."""
    assert _validate_effective_token_limit(None) is None


@pytest.mark.parametrize(
    ("value", "expected_evidence"),
    [
        (0, "0"),
        (-1, "-1"),
        (True, "True"),
        (False, "False"),
        (1.5, "1.5"),
        ("100", "<redacted>"),
        (object(), "<redacted>"),
    ],
)
def test_invalid_token_limits_raise_structured_validation_errors(
    value, expected_evidence
):
    """Only bounded numeric configuration evidence is explicitly disclosed."""
    with pytest.raises(ValidationError, match="effective_token_limit") as exc_info:
        _validate_effective_token_limit(value)

    assert exc_info.value.details == {
        "field": "effective_token_limit",
        "value": expected_evidence,
        "reason": "must be a positive integer when provided",
    }


def test_invalid_token_limit_never_renders_numeric_subclasses():
    """Rejected numeric subclasses stay redacted without invoking their renderer."""
    with pytest.raises(ValidationError, match="effective_token_limit") as exc_info:
        _validate_effective_token_limit(_HostileInt(-1))

    assert exc_info.value.details["value"] == "<redacted>"


def test_oversized_numeric_evidence_falls_back_to_redaction():
    """Oversized numeric diagnostics preserve ValidationError instead of widening it."""
    oversized_negative_integer = -(10**128)

    with pytest.raises(ValidationError, match="effective_token_limit") as exc_info:
        _validate_effective_token_limit(oversized_negative_integer)

    assert exc_info.value.details["value"] == "<redacted>"


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
