# SPDX-License-Identifier: Apache-2.0
"""Current-main regressions for rejected-value diagnostic confidentiality."""

from __future__ import annotations

from pg_llm_batch.exceptions import ValidationError


def test_validation_error_default_does_not_retain_rejected_value() -> None:
    """Arbitrary rejected values must not become package-owned diagnostics."""
    secret = "postgresql://operator:secret@example.internal/db"

    error = ValidationError(field="database_target", value=secret, reason="invalid")

    assert secret not in str(error)
    assert secret not in repr(error)
    assert all(secret not in repr(argument) for argument in error.args)
    assert error.details == {
        "field": "database_target",
        "value": "<redacted>",
        "reason": "invalid",
    }
