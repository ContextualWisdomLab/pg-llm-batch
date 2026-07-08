# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the KV config store and encrypted secret store."""

from __future__ import annotations

import pytest

from pg_llm_batch import config as cfg_mod
from pg_llm_batch.config import PostgresConfigStore, SecretStore
from pg_llm_batch.exceptions import ConfigError
from tests.conftest import FakePsycopg


@pytest.fixture()
def fake_pg(monkeypatch):
    fake = FakePsycopg()
    monkeypatch.setattr(cfg_mod, "psycopg", fake)
    return fake


def test_config_requires_dsn(fake_pg):
    with pytest.raises(ConfigError):
        PostgresConfigStore("")


def test_config_defaults_seeded_and_typed(fake_pg):
    store = PostgresConfigStore("postgresql://x")
    # int coercion from stored string
    assert store.get("token_limits", "per_batch") == 5_000_000_000
    # bool coercion
    assert store.get("optimization", "smart_batching") is True


def test_config_set_get_roundtrip(fake_pg):
    store = PostgresConfigStore("postgresql://x")
    store.set("gateway", "base_url", "https://gw.example/v1")
    # bypass cache to prove it persisted to the backing table
    store.cache.clear()
    assert store.get("gateway", "base_url") == "https://gw.example/v1"


def test_secret_store_base64_without_key(fake_pg, caplog):
    store = SecretStore("postgresql://x", fernet_key=None)
    store.set_secret("gateway_api_key.default", "sk-secret-123")
    # stored obfuscated, not plaintext
    stored_value = fake_pg.store.secrets["gateway_api_key.default"][0]
    assert stored_value != "sk-secret-123"
    assert store.get_secret("gateway_api_key.default") == "sk-secret-123"


def test_secret_store_fernet_encrypts_at_rest(fake_pg):
    from cryptography.fernet import Fernet

    key = Fernet.generate_key().decode()
    store = SecretStore("postgresql://x", fernet_key=key)
    store.set_secret("gateway_api_key.default", "sk-abc")
    value, is_encrypted = fake_pg.store.secrets["gateway_api_key.default"]
    assert is_encrypted is True
    assert value != "sk-abc"
    # a wrong key cannot decrypt
    other = SecretStore("postgresql://x", fernet_key=Fernet.generate_key().decode())
    with pytest.raises(Exception):
        other.get_secret("gateway_api_key.default")
    # the right key can
    assert store.get_secret("gateway_api_key.default") == "sk-abc"


def test_require_secret_raises_when_missing(fake_pg):
    store = SecretStore("postgresql://x")
    with pytest.raises(ConfigError):
        store.require_secret("does_not_exist")
