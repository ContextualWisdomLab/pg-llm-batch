# SPDX-License-Identifier: Apache-2.0
"""Regression tests for encryption-required legacy-secret readiness."""

from __future__ import annotations

import pytest

from pg_llm_batch import config as config_mod
from pg_llm_batch.exceptions import ConfigError
from tests.conftest import FakePsycopg


class _PolicyCursor:
    """Return one bounded encryption-policy readiness result."""

    def __init__(self, policy_row: tuple[bool] | BaseException) -> None:
        self.policy_row = policy_row
        self.queries: list[str] = []

    def __enter__(self) -> _PolicyCursor:
        """Enter the deterministic cursor context."""
        return self

    def __exit__(self, *_args: object) -> None:
        """Leave the deterministic cursor context."""

    def execute(self, sql: str, *_args: object) -> None:
        """Record the readiness probe or raise its configured database failure."""
        self.queries.append(sql)
        if isinstance(self.policy_row, BaseException):
            raise self.policy_row

    def fetchone(self) -> tuple[bool]:
        """Return whether any persisted row violates required encryption."""
        assert not isinstance(self.policy_row, BaseException)
        return self.policy_row


class _PolicyConnection:
    """Expose one cursor and deterministic connection cleanup evidence."""

    def __init__(self, policy_row: tuple[bool] | BaseException) -> None:
        self.autocommit = False
        self.close_calls = 0
        self.policy_cursor = _PolicyCursor(policy_row)

    def cursor(self) -> _PolicyCursor:
        """Return the single readiness-probe cursor."""
        return self.policy_cursor

    def close(self) -> None:
        """Record deterministic constructor-failure cleanup."""
        self.close_calls += 1


class _Psycopg:
    """Return a preconfigured connection while recording acquisitions."""

    def __init__(self, policy_row: tuple[bool] | BaseException) -> None:
        self.connection = _PolicyConnection(policy_row)
        self.connect_calls = 0

    def connect(self, _dsn: str) -> _PolicyConnection:
        """Return the deterministic policy connection."""
        self.connect_calls += 1
        return self.connection


class _ValidFernet:
    """Accept an opaque test key without depending on cryptography internals."""

    def __init__(self, _key: bytes) -> None:
        """Accept the supplied key as valid for constructor-boundary testing."""


def _install_policy_doubles(
    monkeypatch,
    policy_row: tuple[bool] | BaseException,
) -> _Psycopg:
    """Install deterministic schema, crypto, and PostgreSQL boundary doubles."""
    fake_psycopg = _Psycopg(policy_row)
    monkeypatch.setattr(config_mod, "psycopg", fake_psycopg)
    monkeypatch.setattr(config_mod, "Fernet", _ValidFernet)
    monkeypatch.setattr(config_mod, "_schema_is_compatible", lambda *_args: True)
    return fake_psycopg


def test_required_encryption_rejects_existing_unencrypted_rows(monkeypatch) -> None:
    """Production-required encryption must not accept legacy Base64 rows silently."""
    fake_psycopg = _install_policy_doubles(monkeypatch, (True,))

    with pytest.raises(ConfigError, match="unencrypted") as caught:
        config_mod.SecretStore(
            "postgresql://database",
            fernet_key="opaque-valid-key",
            require_encryption=True,
        )

    assert fake_psycopg.connect_calls == 1
    assert fake_psycopg.connection.close_calls == 1
    assert len(fake_psycopg.connection.policy_cursor.queries) == 1
    query = fake_psycopg.connection.policy_cursor.queries[0]
    assert "is_encrypted IS NOT TRUE" in query
    assert "secret_value" not in query
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_required_encryption_proves_no_legacy_rows_before_accepting_store(monkeypatch) -> None:
    """An encryption-required store must positively probe durable legacy state."""
    fake_psycopg = _install_policy_doubles(monkeypatch, (False,))

    store = config_mod.SecretStore(
        "postgresql://database",
        fernet_key="opaque-valid-key",
        require_encryption=True,
    )

    assert fake_psycopg.connect_calls == 1
    assert fake_psycopg.connection.close_calls == 0
    assert len(fake_psycopg.connection.policy_cursor.queries) == 1
    store.close()
    assert fake_psycopg.connection.close_calls == 1


def test_required_encryption_probe_redacts_database_failures(monkeypatch) -> None:
    """Readiness probe failures must not retain database diagnostics or secrets."""
    sentinel = "sensitive-database-diagnostic"
    fake_psycopg = _install_policy_doubles(monkeypatch, RuntimeError(sentinel))

    with pytest.raises(ConfigError, match="could not be verified") as caught:
        config_mod.SecretStore(
            "postgresql://database",
            fernet_key="opaque-valid-key",
            require_encryption=True,
        )

    assert sentinel not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert fake_psycopg.connection.close_calls == 1


def test_required_encryption_rejects_late_unencrypted_row(monkeypatch) -> None:
    """A required-mode store must reject legacy rows introduced after readiness."""
    fake_psycopg = FakePsycopg()
    monkeypatch.setattr(config_mod, "psycopg", fake_psycopg)
    monkeypatch.setattr(config_mod, "Fernet", _ValidFernet)
    store = config_mod.SecretStore(
        "postgresql://database",
        fernet_key="opaque-valid-key",
        require_encryption=True,
    )
    fake_psycopg.store.secrets["late_secret"] = ("Zm9v", False)

    with pytest.raises(ConfigError, match="required encryption policy") as caught:
        store.get_secret("late_secret")

    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
