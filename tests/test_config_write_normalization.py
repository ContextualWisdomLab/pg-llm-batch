# SPDX-License-Identifier: Apache-2.0
"""Regression tests for stable configuration write and reload semantics."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch import config as config_module
from pg_llm_batch.config import PostgresConfigStore
from tests.conftest import FakePsycopg


@pytest.fixture()
def fake_pg(monkeypatch: Any) -> FakePsycopg:
    """Install the in-memory PostgreSQL driver used by configuration tests."""
    fake = FakePsycopg()
    monkeypatch.setattr(config_module, "psycopg", fake)
    return fake


def _register_mutable_default(monkeypatch: Any) -> None:
    """Register one nested mapping setting for cache-ownership tests."""
    monkeypatch.setitem(
        config_module.DEFAULT_CONFIG_INDEX,
        "custom.mapping_value",
        {
            "category": "custom",
            "key": "mapping_value",
            "value": {"nested": {"enabled": True}},
            "type": dict,
            "description": "Test-only nested mapping configuration",
        },
    )


def test_typed_string_write_matches_immediate_and_reloaded_reads(
    fake_pg: FakePsycopg,
) -> None:
    """CLI text writes must have one typed value before and after cache reload."""
    store = PostgresConfigStore("postgresql://example")

    store.set("optimization", "auto_split", "false")
    assert store.get("optimization", "auto_split") is False
    assert fake_pg.store.config["optimization.auto_split"][0] == "false"
    store.cache.clear()
    assert store.get("optimization", "auto_split") is False

    store.set("token_limits", "buffer_percentage", "17")
    assert store.get("token_limits", "buffer_percentage") == 17
    assert type(store.get("token_limits", "buffer_percentage")) is int
    assert fake_pg.store.config["token_limits.buffer_percentage"][0] == "17"
    store.cache.clear()
    assert store.get("token_limits", "buffer_percentage") == 17


def test_malformed_and_untyped_writes_persist_their_canonical_read_value(
    fake_pg: FakePsycopg,
) -> None:
    """Fallback defaults and untyped JSON text must survive process boundaries."""
    store = PostgresConfigStore("postgresql://example")

    store.set("optimization", "smart_batching", "not-a-boolean")
    assert store.get("optimization", "smart_batching") is True
    assert fake_pg.store.config["optimization.smart_batching"][0] == "true"

    store.set("custom", "payload", {"nested": True})
    assert store.get("custom", "payload") == '{"nested": true}'
    assert fake_pg.store.config["custom.payload"][0] == '{"nested": true}'
    store.cache.clear()
    assert store.get("custom", "payload") == '{"nested": true}'


def test_mutable_cache_reads_are_isolated_from_caller_mutation(
    fake_pg: FakePsycopg,
    monkeypatch: Any,
) -> None:
    """One caller must not mutate cache state that later reads treat as persisted."""
    _register_mutable_default(monkeypatch)
    store = PostgresConfigStore("postgresql://example")

    initial = store.get("custom", "mapping_value")
    initial["nested"]["enabled"] = False
    assert store.get("custom", "mapping_value") == {"nested": {"enabled": True}}

    store.set("custom", "mapping_value", {"nested": {"enabled": False}})
    written = store.get("custom", "mapping_value")
    written["nested"]["enabled"] = True
    assert store.get("custom", "mapping_value") == {"nested": {"enabled": False}}

    store.cache.clear()
    reloaded = store.get("custom", "mapping_value")
    reloaded["nested"]["enabled"] = True
    assert store.get("custom", "mapping_value") == {"nested": {"enabled": False}}
