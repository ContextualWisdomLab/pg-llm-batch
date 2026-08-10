# SPDX-License-Identifier: Apache-2.0
"""Fail-closed type contracts for TokenCounter resource configuration."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch import token_counter
from pg_llm_batch.exceptions import ValidationError


class _ForbiddenPsycopg:
    """Fail if invalid configuration reaches extension or connection acquisition."""

    @staticmethod
    def connect(*_args: Any, **_kwargs: Any) -> None:
        """Prove invalid buffer configuration is rejected before PostgreSQL I/O."""
        raise AssertionError("invalid buffer percentage reached PostgreSQL")


@pytest.mark.parametrize("invalid_value", [True, False, 5.0, "5", [], {}])
def test_token_counter_rejects_non_integer_buffer_percentage_before_postgres(
    monkeypatch: pytest.MonkeyPatch,
    invalid_value: Any,
) -> None:
    """Buffer percentage authority must be an exact integer, never coerced input."""
    monkeypatch.setattr(token_counter, "psycopg", _ForbiddenPsycopg())

    with pytest.raises(ValidationError, match="buffer_percentage"):
        token_counter.TokenCounter(
            "postgresql://example",
            buffer_percentage=invalid_value,
        )
