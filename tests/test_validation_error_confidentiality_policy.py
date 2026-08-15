# SPDX-License-Identifier: Apache-2.0
"""Confidentiality regressions for rejected-value validation evidence."""

from __future__ import annotations

import pytest

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


def test_reviewed_safe_value_is_bounded_explicit_evidence() -> None:
    """Callers may expose only a separately supplied reviewed diagnostic string."""
    secret = "actual-rejected-secret"

    error = ValidationError(
        field="mode",
        value=secret,
        reason="must name a supported mode",
        safe_value="unsupported-mode",
    )

    assert secret not in str(error)
    assert secret not in repr(error.details)
    assert error.details["value"] == "unsupported-mode"
    assert str(error) == (
        "[VALIDATION_ERROR] Invalid value for 'mode': unsupported-mode "
        "(must name a supported mode)"
    )


def test_safe_value_rejects_non_string_evidence() -> None:
    """Explicit evidence authority must not reintroduce arbitrary object rendering."""
    with pytest.raises(TypeError, match="safe_value must be a string or None"):
        ValidationError(field="mode", value="secret", safe_value=1)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "safe_value",
    ["", "x" * 129, "line\nbreak", "non-ascii-é"],
)
def test_safe_value_rejects_unbounded_or_non_printable_evidence(
    safe_value: str,
) -> None:
    """Explicit evidence remains finite, printable ASCII suitable for logs."""
    with pytest.raises(
        ValueError,
        match="safe_value must contain 1-128 printable ASCII characters",
    ):
        ValidationError(field="mode", value="secret", safe_value=safe_value)
