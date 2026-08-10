# SPDX-License-Identifier: Apache-2.0
"""Fail-closed type contracts for bootstrap authority inputs."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch import bootstrap
from pg_llm_batch.exceptions import ConfigError


@pytest.mark.parametrize("invalid_value", [True, 7, b"postgresql://bytes", ["dsn"]])
def test_explicit_dsn_rejects_non_string_values_before_environment_fallback(
    monkeypatch: pytest.MonkeyPatch,
    invalid_value: Any,
) -> None:
    """Only an omitted value or exact string may select the database target."""
    monkeypatch.setenv(bootstrap.DSN_ENV_VAR, "postgresql://environment")

    with pytest.raises(ConfigError, match="string"):
        bootstrap.resolve_dsn(invalid_value)


@pytest.mark.parametrize("invalid_value", [True, 7, b"fernet-key", ["key"]])
def test_explicit_secret_key_rejects_non_string_values_before_environment_fallback(
    monkeypatch: pytest.MonkeyPatch,
    invalid_value: Any,
) -> None:
    """Explicit decryption authority must be a string, including the valid empty string."""
    monkeypatch.setenv(bootstrap.SECRET_KEY_ENV_VAR, "ambient-fernet-key")

    with pytest.raises(ConfigError, match="string"):
        bootstrap.resolve_secret_key(invalid_value)
