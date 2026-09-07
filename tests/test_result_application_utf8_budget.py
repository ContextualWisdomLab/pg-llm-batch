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


@pytest.mark.parametrize(
    ("integer_value", "remaining_bytes", "expected"),
    [
        (1, 0, True),
        (0, 1, False),
        (-1, 2, False),
    ],
)
def test_integer_decimal_budget_covers_exhausted_zero_and_signed_boundaries(
    integer_value: int,
    remaining_bytes: int,
    expected: bool,
) -> None:
    """The conservative decimal bound handles empty, zero, and sign budgets exactly."""
    assert (
        result_application._integer_decimal_text_exceeds_budget(
            integer_value,
            remaining_bytes,
        )
        is expected
    )


def test_json_snapshot_rejects_integer_from_conservative_bound(monkeypatch: Any) -> None:
    """A definitely oversized integer fails before exact decimal materialization."""
    monkeypatch.setattr(result_application, "_MAX_RECORD_JSON_TEXT_CHARS", 1)

    with pytest.raises(ValidationError) as caught:
        result_application._snapshot_json_record({"": 100})

    assert caught.value.details["field"] == "item.record"
    assert caught.value.details["value"] == "<redacted>"


def test_json_snapshot_rejects_integer_text_conversion_overflow() -> None:
    """Interpreter integer-string limits must fail through redacted validation."""
    with pytest.raises(ValidationError) as caught:
        result_application._snapshot_json_record({"n": 10**5000})

    assert caught.value.details["field"] == "item.record"
    assert caught.value.details["value"] == "<redacted>"
