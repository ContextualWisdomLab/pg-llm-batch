# SPDX-License-Identifier: Apache-2.0
"""Fail-closed configured resource ceilings for ``TokenCounter``."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch import token_counter
from pg_llm_batch.exceptions import ValidationError


class _Config:
    """Return one overridden resource value and safe defaults elsewhere."""

    _DEFAULTS = {
        ("token_limits", "buffer_percentage"): 5,
        ("token_limits", "per_batch"): 1_000,
        ("token_limits", "per_request"): 100,
        ("azure_limits", "max_records_per_file"): 50,
        ("azure_limits", "max_bytes_per_file"): 4096,
        ("azure_limits", "max_files_per_job"): 10,
    }

    def __init__(self, category: str, key: str, value: Any) -> None:
        self._override = (category, key, value)

    def get(self, category: str, key: str, default: Any = None) -> Any:
        """Return the selected invalid value or one known-safe test default."""
        if (category, key) == self._override[:2]:
            return self._override[2]
        return self._DEFAULTS.get((category, key), default)


class _ForbiddenPsycopg:
    """Fail if malformed resource configuration reaches PostgreSQL setup."""

    @staticmethod
    def connect(*_args: Any, **_kwargs: Any) -> None:
        """Prove validation happens before connection acquisition."""
        raise AssertionError("invalid TokenCounter resource limit reached PostgreSQL")


@pytest.mark.parametrize(
    ("category", "key", "field"),
    [
        ("token_limits", "per_batch", "max_tokens_per_batch"),
        ("token_limits", "per_request", "default_model_limit"),
        ("azure_limits", "max_records_per_file", "azure_max_records_per_file"),
        ("azure_limits", "max_bytes_per_file", "azure_max_bytes_per_file"),
        ("azure_limits", "max_files_per_job", "azure_max_files_per_job"),
    ],
)
@pytest.mark.parametrize("invalid_value", [True, False, 0, -1, 1.0, "1", [], {}])
def test_configured_resource_ceiling_requires_exact_positive_integer(
    monkeypatch: pytest.MonkeyPatch,
    category: str,
    key: str,
    field: str,
    invalid_value: Any,
) -> None:
    """All configured hard ceilings fail closed before pg_tiktoken/PostgreSQL."""
    monkeypatch.setattr(token_counter, "psycopg", _ForbiddenPsycopg())

    with pytest.raises(ValidationError, match=field):
        token_counter.TokenCounter(
            "postgresql://example",
            config=_Config(category, key, invalid_value),
        )


def test_huge_exact_batch_limit_uses_integer_buffer_arithmetic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An exact positive integer ceiling must not overflow through float math."""
    monkeypatch.setattr(token_counter, "psycopg", None)
    huge_limit = 10**1_000

    counter = token_counter.TokenCounter(
        "postgresql://example",
        config=_Config("token_limits", "per_batch", huge_limit),
    )

    assert counter.token_limit == huge_limit
    assert counter.effective_limit == huge_limit * 95 // 100
