# SPDX-License-Identifier: Apache-2.0
"""Regression tests for deterministic malformed boolean configuration fallback."""

from __future__ import annotations

from typing import Any

from pg_llm_batch import config as config_module


def test_malformed_boolean_uses_the_declared_default(monkeypatch: Any) -> None:
    """Malformed persisted text must not enable a false-default feature flag."""
    monkeypatch.setitem(
        config_module.DEFAULT_CONFIG_INDEX,
        "custom.feature_enabled",
        {
            "category": "custom",
            "key": "feature_enabled",
            "value": False,
            "type": bool,
            "description": "Test-only false-default feature flag",
        },
    )

    assert (
        config_module._deserialize_value("custom.feature_enabled", "not-a-boolean")
        is False
    )


def test_cached_scalar_configuration_is_returned_without_copying() -> None:
    """Scalar cached values should traverse the public ``get`` path unchanged."""
    store = object.__new__(config_module.PostgresConfigStore)
    store.cache = {"custom": {"retry_count": 3}}

    assert store.get("custom", "retry_count") == 3
