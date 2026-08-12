# SPDX-License-Identifier: Apache-2.0
"""Regression tests for token-counting database diagnostic confidentiality."""

import logging

import pytest

from pg_llm_batch.token_counter import TokenCounter


def test_database_failure_log_does_not_render_lower_layer_exception(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Generic database failures must not copy lower-layer text into package logs."""
    secret_sentinel = "PROMPT-SECRET-token-counter-diagnostic-sentinel"
    counter = object.__new__(TokenCounter)
    counter._pg_available = True

    def fail_count(*_args: object, **_kwargs: object) -> int:
        raise RuntimeError(secret_sentinel)

    monkeypatch.setattr(counter, "_count_tokens_postgres", fail_count)
    caplog.set_level(logging.DEBUG, logger="pg_llm_batch.token_counter")

    with pytest.raises(RuntimeError, match="Token counting requires pg_tiktoken"):
        counter.count_tokens("purpose-bound prompt", "model-name")

    assert secret_sentinel not in caplog.text
    assert "PostgreSQL token counting failed" in caplog.text
