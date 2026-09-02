# SPDX-License-Identifier: Apache-2.0
"""Resource-policy authority tests for ``TokenCounter`` configuration reads."""

from __future__ import annotations

import pytest

import pg_llm_batch.token_counter as token_counter_module
from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.token_counter import TokenCounter


class _FailingConfig:
    """Return defaults except for one configured policy key that becomes unavailable."""

    def __init__(self, fail_at: tuple[str, str]) -> None:
        self.fail_at = fail_at

    def get(self, category: str, key: str, default: object) -> object:
        """Raise a sentinel failure only when the selected authority is read."""
        if (category, key) == self.fail_at:
            raise RuntimeError("private-config-sentinel")
        return default


@pytest.mark.parametrize(
    "fail_at",
    [
        ("token_limits", "buffer_percentage"),
        ("token_limits", "per_batch"),
        ("token_limits", "per_request"),
        ("azure_limits", "max_records_per_file"),
        ("azure_limits", "max_bytes_per_file"),
        ("azure_limits", "max_files_per_job"),
    ],
)
def test_explicit_resource_policy_read_failure_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
    fail_at: tuple[str, str],
) -> None:
    """An unavailable explicit config authority must not widen a hard resource policy."""
    monkeypatch.setattr(token_counter_module, "psycopg", None)

    with pytest.raises(ValidationError) as captured:
        TokenCounter(
            "postgresql://example.invalid/database",
            config=_FailingConfig(fail_at),
        )

    assert captured.value.details == {
        "field": f"{fail_at[0]}.{fail_at[1]}",
        "value": "<unavailable>",
        "reason": "configured value could not be read",
    }
    assert "private-config-sentinel" not in str(captured.value)


def test_missing_config_authority_still_uses_documented_defaults(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Standalone operation keeps package defaults when no config authority is supplied."""
    monkeypatch.setattr(token_counter_module, "psycopg", None)

    counter = TokenCounter("postgresql://example.invalid/database")

    assert counter.token_limit == TokenCounter.DEFAULT_MAX_TOKENS_PER_BATCH
    assert counter.default_model_limit == TokenCounter.DEFAULT_MODEL_LIMIT
    assert counter.azure_max_records_per_file == TokenCounter.DEFAULT_AZURE_MAX_RECORDS
    assert counter.azure_max_bytes_per_file == TokenCounter.DEFAULT_AZURE_MAX_BYTES
    assert counter.azure_max_files_per_job == TokenCounter.DEFAULT_AZURE_MAX_FILES
