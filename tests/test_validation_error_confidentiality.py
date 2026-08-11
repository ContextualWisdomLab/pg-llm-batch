# SPDX-License-Identifier: Apache-2.0
"""Privacy regressions for rejected values in package validation evidence."""

from __future__ import annotations

from typing import Any

from pg_llm_batch.exceptions import ValidationError


SENSITIVE_SENTINEL = "sensitive-value-7c6d66d2"
REDACTED_VALUE = "<redacted>"


class _ExplodingRepr:
    """Test value that proves safe validation never renders caller objects."""

    def __repr__(self) -> str:
        """Fail if production diagnostics attempt to render this caller object."""
        raise AssertionError("ValidationError must not call repr(value) by default")


def _observable_exception_state(error: ValidationError) -> str:
    """Return user-visible exception surfaces used by ordinary diagnostics."""
    return " | ".join((str(error), repr(error), repr(error.args), repr(error.details)))


def test_validation_error_redacts_rejected_values_by_default() -> None:
    """The safe default must not duplicate confidential caller values."""
    error = ValidationError(
        field="user_prompt",
        value=SENSITIVE_SENTINEL,
        reason="must satisfy the accepted input contract",
    )

    assert SENSITIVE_SENTINEL not in _observable_exception_state(error)
    assert error.details == {
        "field": "user_prompt",
        "value": REDACTED_VALUE,
        "reason": "must satisfy the accepted input contract",
    }


def test_validation_error_safe_default_never_renders_rejected_objects() -> None:
    """Rejected arbitrary objects must not execute their representation hooks."""
    error = ValidationError(
        field="request",
        value=_ExplodingRepr(),
        reason="must be an exact supported type",
    )

    assert error.details["value"] == REDACTED_VALUE
    assert "request" in str(error)
    assert "exact supported type" in str(error)


def test_validation_error_requires_explicit_opt_in_for_safe_value_evidence() -> None:
    """Reviewed non-sensitive values may remain available only by explicit opt-in."""
    safe_value: Any = 5
    error = ValidationError(
        field="max_retry_attempts",
        value=safe_value,
        reason="must be between one and ten",
        expose_value=True,
    )

    assert error.details["value"] == safe_value
    assert "5" in str(error)
