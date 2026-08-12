# SPDX-License-Identifier: Apache-2.0
"""Regression tests for SecretStore encryption capability boundaries."""

from __future__ import annotations

import pytest

from pg_llm_batch import config as config_mod
from pg_llm_batch.exceptions import ConfigError


class _Connection:
    """Minimal connection double that records deterministic cleanup."""

    def __init__(self) -> None:
        self.autocommit = False
        self.close_calls = 0

    def close(self) -> None:
        self.close_calls += 1


class _Psycopg:
    """Record whether database acquisition happened before local validation."""

    def __init__(self) -> None:
        self.connect_calls = 0
        self.connection = _Connection()

    def connect(self, _dsn: str) -> _Connection:
        self.connect_calls += 1
        return self.connection


def test_fernet_request_fails_before_database_access_when_crypto_is_unavailable(
    monkeypatch,
) -> None:
    """Never downgrade an explicit encryption request to Base64 persistence."""
    fake_psycopg = _Psycopg()
    monkeypatch.setattr(config_mod, "psycopg", fake_psycopg)
    monkeypatch.setattr(config_mod, "Fernet", None)
    monkeypatch.setattr(config_mod.SecretStore, "_ensure_table", lambda _self: None)

    with pytest.raises(ConfigError, match="Fernet"):
        config_mod.SecretStore("postgresql://database", fernet_key="explicit-key")

    assert fake_psycopg.connect_calls == 0
    assert fake_psycopg.connection.close_calls == 0
