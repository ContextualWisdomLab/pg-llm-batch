# SPDX-License-Identifier: Apache-2.0
"""Tests for explicit SecretStore at-rest encryption policy."""

from __future__ import annotations

import pytest

from pg_llm_batch import config as config_mod
from pg_llm_batch.exceptions import ConfigError

_SECRET_SENTINEL = "SECRET-SENTINEL hostile Fernet key"


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


class _HostileFernetKey(str):
    """Execute caller-controlled code if a string subclass receives key authority."""

    def encode(self, *_args, **_kwargs):
        """Raise instead of producing key bytes."""
        raise RuntimeError(_SECRET_SENTINEL)


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


def test_encryption_cannot_be_disabled_before_database_access(monkeypatch) -> None:
    """No caller may opt back into reversible Base64 secret persistence."""
    fake_psycopg = _Psycopg()
    monkeypatch.setattr(config_mod, "psycopg", fake_psycopg)

    with pytest.raises(ConfigError, match="encryption"):
        config_mod.SecretStore(
            "postgresql://database",
            require_encryption=False,
        )

    assert fake_psycopg.connect_calls == 0
    assert fake_psycopg.connection.close_calls == 0


def test_malformed_fernet_key_fails_before_database_access(monkeypatch) -> None:
    """Malformed encryption keys must fail closed before database acquisition."""
    fake_psycopg = _Psycopg()
    monkeypatch.setattr(config_mod, "psycopg", fake_psycopg)

    with pytest.raises(ConfigError, match="encryption") as caught:
        config_mod.SecretStore(
            "postgresql://database",
            fernet_key="not-a-valid-fernet-key",
        )

    assert fake_psycopg.connect_calls == 0
    assert fake_psycopg.connection.close_calls == 0
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_fernet_key_subclass_fails_before_database_access(monkeypatch) -> None:
    """Bootstrap key authority must require an exact built-in string."""
    fake_psycopg = _Psycopg()
    monkeypatch.setattr(config_mod, "psycopg", fake_psycopg)

    with pytest.raises(ConfigError, match="encryption") as caught:
        config_mod.SecretStore(
            "postgresql://database",
            fernet_key=_HostileFernetKey("not-a-real-key"),
        )

    assert fake_psycopg.connect_calls == 0
    assert fake_psycopg.connection.close_calls == 0
    assert _SECRET_SENTINEL not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
