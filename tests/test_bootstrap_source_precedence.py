# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for bootstrap source precedence and type authority."""

from __future__ import annotations

import pytest

from pg_llm_batch.bootstrap import resolve_dsn, resolve_secret_key
from pg_llm_batch.exceptions import ConfigError


@pytest.mark.parametrize("explicit", ("", "   ", False, 0, b"postgresql://db"))
def test_explicit_dsn_never_falls_back_to_environment(monkeypatch, explicit) -> None:
    """An explicitly supplied invalid DSN must not inherit ambient DB authority."""
    monkeypatch.setenv("PG_LLM_BATCH_DSN", "postgresql://ambient.example/db")

    with pytest.raises(ConfigError):
        resolve_dsn(explicit)  # type: ignore[arg-type]


def test_omitted_dsn_rejects_blank_environment(monkeypatch) -> None:
    """An omitted DSN may use the environment only when it is a nonblank string."""
    monkeypatch.setenv("PG_LLM_BATCH_DSN", "  \t ")

    with pytest.raises(ConfigError):
        resolve_dsn()


def test_valid_explicit_dsn_preserves_exact_text(monkeypatch) -> None:
    """A valid explicit DSN remains authoritative and byte-for-byte unchanged."""
    monkeypatch.setenv("PG_LLM_BATCH_DSN", "postgresql://ambient.example/db")
    explicit = "postgresql://operator.example/db?application_name=pg-llm-batch"

    assert resolve_dsn(explicit) == explicit


@pytest.mark.parametrize("explicit", (False, 0, b"fernet-key"))
def test_explicit_secret_key_type_error_never_falls_back(monkeypatch, explicit) -> None:
    """Invalid explicit key types must not silently inherit ambient decryption authority."""
    monkeypatch.setenv("PG_LLM_BATCH_SECRET_KEY", "ambient-secret-key")

    with pytest.raises(ConfigError):
        resolve_secret_key(explicit)  # type: ignore[arg-type]


def test_explicit_empty_secret_key_remains_explicit(monkeypatch) -> None:
    """An explicit empty key deliberately disables ambient-key fallback."""
    monkeypatch.setenv("PG_LLM_BATCH_SECRET_KEY", "ambient-secret-key")

    assert resolve_secret_key("") == ""
