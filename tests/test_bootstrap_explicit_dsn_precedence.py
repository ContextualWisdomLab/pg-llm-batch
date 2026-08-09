# SPDX-License-Identifier: Apache-2.0
"""Regression tests for explicit bootstrap source precedence."""

from __future__ import annotations

from pathlib import Path

import pytest

from pg_llm_batch import bootstrap
from pg_llm_batch.exceptions import ConfigError


DOCTORING = Path("docs/doctoring/bootstrap-dsn-precedence.md")
CHANGELOG = Path("CHANGELOG.md")


def _normalized(path: Path) -> str:
    """Return Markdown text with layout-only whitespace collapsed."""
    return " ".join(path.read_text(encoding="utf-8").split())


def test_explicit_empty_dsn_never_falls_back_to_environment(monkeypatch) -> None:
    """An explicitly supplied empty DSN must fail before consulting environment fallback."""
    monkeypatch.setenv(bootstrap.DSN_ENV_VAR, "postgresql://environment")

    with pytest.raises(ConfigError, match="explicit Postgres DSN"):
        bootstrap.resolve_dsn("")


def test_optional_secret_key_precedence_is_authoritative() -> None:
    """Docs must preserve explicit-empty secret-key precedence over ambient state."""
    doctoring = _normalized(DOCTORING)
    changelog = _normalized(CHANGELOG)

    assert "explicit empty Fernet" in doctoring
    assert "ambient bootstrap key" in doctoring
    assert "decryption authority" in doctoring
    assert "bootstrap secret-key precedence" in changelog.lower()
