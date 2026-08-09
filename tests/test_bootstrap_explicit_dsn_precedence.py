# SPDX-License-Identifier: Apache-2.0
"""Regression tests for explicit bootstrap database-target precedence."""

from __future__ import annotations

import pytest

from pg_llm_batch import bootstrap
from pg_llm_batch.exceptions import ConfigError


def test_explicit_empty_dsn_never_falls_back_to_environment(monkeypatch) -> None:
    """An explicitly supplied empty DSN must fail before consulting environment fallback."""
    monkeypatch.setenv(bootstrap.DSN_ENV_VAR, "postgresql://environment")

    with pytest.raises(ConfigError, match="explicit Postgres DSN"):
        bootstrap.resolve_dsn("")
