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


def test_serialization_and_typed_deserialization_fallbacks(monkeypatch):
    assert cfg_mod._serialize_value({"a": 1}) == '{"a": 1}'
    assert cfg_mod._serialize_value([1, 2]) == "[1, 2]"
    assert cfg_mod._serialize_value(True) == "true"
    assert cfg_mod._serialize_value(12) == "12"

    assert cfg_mod._deserialize_value("optimization.smart_batching", "YES") is True
    assert cfg_mod._deserialize_value("optimization.smart_batching", "off") is False
    assert cfg_mod._deserialize_value("optimization.smart_batching", "maybe") is True
    assert cfg_mod._deserialize_value("token_limits.per_batch", "invalid") == (
        5_000_000_000
    )

    monkeypatch.setitem(
        cfg_mod.DEFAULT_CONFIG_INDEX,
        "custom.mapping",
        {"type": dict, "value": {"safe": True}},
    )
    monkeypatch.setitem(
        cfg_mod.DEFAULT_CONFIG_INDEX,
        "custom.ratio",
        {"type": float, "value": 0.5},
    )
    assert cfg_mod._deserialize_value("custom.mapping", "not-json") == {
        "safe": True
    }
    assert cfg_mod._deserialize_value("custom.ratio", "1.25") == 1.25
    assert cfg_mod._deserialize_value("custom.ratio", "invalid") == 0.5
    assert cfg_mod._deserialize_value("custom.raw", "value") == "value"
    assert cfg_mod._split_full_key("gateway.base_url") == ("gateway", "base_url")
    assert cfg_mod._split_full_key("standalone") == ("global", "standalone")


def test_config_missing_lookup_show_and_factory(fake_pg):
    store = cfg_mod.get_config_store("postgresql://x")
    assert store.get("unknown", "key", "fallback") == "fallback"
    store.set("unknown", "key", {"nested": True})
    store.cache.clear()
    assert store.get("unknown", "key") == '{"nested": true}'
    rows = list(store.show_config())
    assert rows == sorted(rows)
    assert ("unknown", "key", '{"nested": true}') in rows
    connection = store._conn
    store.close()
    assert connection.closed is True
    assert store._conn is None
    store.close()


def test_store_constructor_requires_dependency_and_dsn(monkeypatch, fake_pg):
    monkeypatch.setattr(cfg_mod, "psycopg", None)
    with pytest.raises(ConfigError, match="psycopg is required"):
        PostgresConfigStore("postgresql://x")
    with pytest.raises(ConfigError, match="psycopg is required"):
        SecretStore("postgresql://x")

    monkeypatch.setattr(cfg_mod, "psycopg", fake_pg)
    with pytest.raises(ConfigError, match="DSN"):
        PostgresConfigStore("")
    with pytest.raises(ConfigError, match="DSN"):
        SecretStore("")


def test_encrypted_secret_requires_matching_key(fake_pg):
    fake_pg.store.secrets["encrypted"] = ("opaque", True)
    store = SecretStore("postgresql://x")
    with pytest.raises(ConfigError, match="no Fernet key"):
        store.get_secret("encrypted")
    assert store.get_secret("absent", "default") == "default"
    store.set_secret("present", "value")
    assert store.require_secret("present") == "value"


def test_close_swallows_driver_cleanup_errors(fake_pg):
    class BrokenConnection:
        def close(self):
            raise OSError("driver shutdown failed")

    config = PostgresConfigStore("postgresql://x")
    config._conn = BrokenConnection()
    config.close()
    assert config._conn is None

    secrets = SecretStore("postgresql://x")
    secrets._conn = BrokenConnection()
    secrets.close()
    assert secrets._conn is None
    secrets.close()
