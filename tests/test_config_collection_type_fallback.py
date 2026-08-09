# SPDX-License-Identifier: Apache-2.0
"""Regression tests for declared collection configuration types."""

from __future__ import annotations

from typing import Any

from pg_llm_batch import config as config_module


def test_json_collection_shape_must_match_the_declared_type(
    monkeypatch: Any,
) -> None:
    """Valid JSON with the wrong container type must use the declared default."""
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
