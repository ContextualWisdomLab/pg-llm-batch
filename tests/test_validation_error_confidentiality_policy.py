# SPDX-License-Identifier: Apache-2.0
"""Confidentiality regressions for rejected-value validation evidence."""

from __future__ import annotations

from pg_llm_batch.exceptions import ValidationError


def test_default_validation_error_does_not_retain_or_render_rejected_content() -> None:
    """Arbitrary rejected content must stay outside package-owned error evidence."""
    secret = "credential-shaped-sentinel-7f4a6b89"

    error = ValidationError(
        field="api_key",
        value=secret,
        reason="must satisfy the configured policy",
    )

    assert secret not in str(error)
    assert secret not in repr(error)
    assert secret not in repr(error.args)
    assert secret not in repr(error.details)
    assert error.details == {
        "field": "api_key",
        "value": "<redacted>",
        "reason": "must satisfy the configured policy",
    }


def test_default_validation_error_never_calls_rejected_value_repr() -> None:
    """Safe-default construction must not execute caller-controlled rendering."""

    class HostileRejectedValue:
        def __repr__(self) -> str:
            raise AssertionError("rejected value repr must not run")

    error = ValidationError(
        field="payload",
        value=HostileRejectedValue(),
        reason="must be a supported value",
    )

    assert str(error) == (
        "[VALIDATION_ERROR] Invalid value for 'payload' (must be a supported value)"
    )
    assert error.details["value"] == "<redacted>"
