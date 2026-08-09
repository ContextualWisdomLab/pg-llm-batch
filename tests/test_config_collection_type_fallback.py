# SPDX-License-Identifier: Apache-2.0
"""Regression tests for declared collection configuration types."""

from __future__ import annotations

from typing import Any

from pg_llm_batch import config as config_module


def _register_collection_defaults(monkeypatch: Any) -> tuple[dict[str, bool], list[str]]:
    """Register mutable test-only defaults and return their authoritative objects."""
    declared_mapping = {"enabled": True}
    declared_sequence = ["default"]
    monkeypatch.setitem(
        config_module.DEFAULT_CONFIG_INDEX,
        "custom.mapping_value",
        {
            "category": "custom",
            "key": "mapping_value",
            "value": declared_mapping,
            "type": dict,
            "description": "Test-only mapping configuration",
        },
    )
    monkeypatch.setitem(
        config_module.DEFAULT_CONFIG_INDEX,
        "custom.sequence_value",
        {
            "category": "custom",
            "key": "sequence_value",
            "value": declared_sequence,
            "type": list,
            "description": "Test-only sequence configuration",
        },
    )
    return declared_mapping, declared_sequence


def test_json_collection_shape_must_match_the_declared_type(
    monkeypatch: Any,
) -> None:
    """Valid JSON with the wrong container type must use the declared default."""
    declared_mapping, declared_sequence = _register_collection_defaults(monkeypatch)

    assert config_module._deserialize_value("custom.mapping_value", '["wrong"]') == (
        declared_mapping
    )
    assert config_module._deserialize_value(
        "custom.sequence_value", '{"wrong":true}'
    ) == declared_sequence
    assert config_module._deserialize_value(
        "custom.mapping_value", '{"enabled":false}'
    ) == {"enabled": False}
    assert config_module._deserialize_value(
        "custom.sequence_value", '["configured"]'
    ) == ["configured"]


def test_mutable_declared_defaults_are_isolated_from_callers(monkeypatch: Any) -> None:
    """Fallback consumers must not receive the process-wide mutable default object."""
    declared_mapping, declared_sequence = _register_collection_defaults(monkeypatch)

    mapping_fallback = config_module._deserialize_value(
        "custom.mapping_value", '["wrong"]'
    )
    sequence_fallback = config_module._deserialize_value(
        "custom.sequence_value", '{"wrong":true}'
    )
    missing_mapping = config_module._default_value("custom", "mapping_value", {})
    missing_sequence = config_module._default_value("custom", "sequence_value", [])

    assert mapping_fallback is not declared_mapping
    assert sequence_fallback is not declared_sequence
    assert missing_mapping is not declared_mapping
    assert missing_sequence is not declared_sequence

    mapping_fallback["enabled"] = False
    sequence_fallback.append("mutated")
    missing_mapping["extra"] = True
    missing_sequence.append("extra")

    assert declared_mapping == {"enabled": True}
    assert declared_sequence == ["default"]
    assert config_module._deserialize_value(
        "custom.mapping_value", '["wrong"]'
    ) == {"enabled": True}
    assert config_module._deserialize_value(
        "custom.sequence_value", '{"wrong":true}'
    ) == ["default"]
