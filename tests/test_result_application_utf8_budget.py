# SPDX-License-Identifier: Apache-2.0
"""Regression coverage for byte-bounded result-application snapshots."""

from __future__ import annotations

from typing import Any

import pytest

import pg_llm_batch.result_application as result_application
from pg_llm_batch.exceptions import ValidationError


def test_json_snapshot_text_budget_counts_utf8_bytes(monkeypatch: Any) -> None:
    """Multibyte JSON text must consume its encoded-byte resource budget."""
    monkeypatch.setattr(result_application, "_MAX_RECORD_JSON_TEXT_CHARS", 3)

    with pytest.raises(ValidationError) as caught:
        result_application._snapshot_json_record({"a": "한"})

    assert caught.value.details["field"] == "item.record"
    assert caught.value.details["value"] == "<redacted>"


def test_json_snapshot_numeric_values_consume_text_budget(monkeypatch: Any) -> None:
    """Integer JSON values must not bypass the snapshot's finite text budget."""
    monkeypatch.setattr(result_application, "_MAX_RECORD_JSON_TEXT_CHARS", 4)

    with pytest.raises(ValidationError) as caught:
        result_application._snapshot_json_record({"n": 12345})

    assert caught.value.details["field"] == "item.record"
    assert caught.value.details["value"] == "<redacted>"
