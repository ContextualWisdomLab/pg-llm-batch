# SPDX-License-Identifier: Apache-2.0
"""Tests for explicit SecretStore at-rest encryption policy."""

from __future__ import annotations

import pytest

from pg_llm_batch import config as config_mod
from pg_llm_batch.exceptions import ConfigError


class _Connection:
    """Minimal connection double for pre-acquisition policy assertions."""

    def __init__(self) -> None:
        self.close_calls = 0

    def close(self) -> None:
        """Record deterministic cleanup if acquisition unexpectedly occurs."""
        self.close_calls += 1


class _Psycopg:
    """Record whether policy validation occurs before database acquisition."""

    def __init__(self) -> None:
        self.connect_calls = 0
        self.connection = _Connection()

    def connect(self, _dsn: str) -> _Connection:
        """Return a connection while recording an unexpected acquisition."""
        self.connect_calls += 1
        return self.connection


def test_encryption_is_required_by_default_before_database_access(monkeypatch) -> None:
    """The default SecretStore policy must fail closed before database access."""
    fake_psycopg = _Psycopg()
    monkeypatch.setattr(config_mod, "psycopg", fake_psycopg)

    with pytest.raises(ConfigError, match="encryption"):
        config_mod.SecretStore("postgresql://database")

    assert fake_psycopg.connect_calls == 0
    assert fake_psycopg.connection.close_calls == 0


def test_encryption_required_without_key_fails_before_database_access(monkeypatch) -> None:
    """An encryption-required deployment cannot silently select Base64 storage."""
    fake_psycopg = _Psycopg()
    monkeypatch.setattr(config_mod, "psycopg", fake_psycopg)

    with pytest.raises(ConfigError, match="encryption"):
        config_mod.SecretStore(
            "postgresql://database",
            require_encryption=True,
        )

    assert fake_psycopg.connect_calls == 0
    assert fake_psycopg.connection.close_calls == 0
