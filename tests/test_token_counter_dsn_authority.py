# SPDX-License-Identifier: Apache-2.0
"""Connection-authority tests for ``TokenCounter`` PostgreSQL DSNs."""

from __future__ import annotations

import pytest

import pg_llm_batch.token_counter as token_counter_module
from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.token_counter import TokenCounter


class _BehaviorBearingDsn(str):
    """A string-shaped caller value whose protocol hooks reveal authority leaks."""

    def __new__(cls, value: str) -> "_BehaviorBearingDsn":
        instance = super().__new__(cls, value)
        instance.bool_calls = 0
        instance.str_calls = 0
        instance.repr_calls = 0
        return instance

    def __bool__(self) -> bool:
        self.bool_calls += 1
        return False

    def __str__(self) -> str:
        self.str_calls += 1
        return "postgresql://rewritten.invalid/database"

    def __repr__(self) -> str:
        self.repr_calls += 1
        return "<dsn-content-sentinel>"


class _NonStringDsn:
    """A non-string object that must never gain connection or diagnostic authority."""

    def __init__(self) -> None:
        self.bool_calls = 0
        self.repr_calls = 0

    def __bool__(self) -> bool:
        self.bool_calls += 1
        return True

    def __repr__(self) -> str:
        self.repr_calls += 1
        return "<non-string-dsn-sentinel>"


class _ConfigProbe:
    """Record whether configuration lookup happened before DSN admission."""

    def __init__(self) -> None:
        self.calls = 0

    def get(self, category: str, key: str, default: object) -> object:
        self.calls += 1
        return default


def test_behavior_bearing_string_dsn_is_snapshotted_without_protocol_hooks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Retain an exact built-in string, never caller-controlled string behavior."""
    monkeypatch.setattr(token_counter_module, "psycopg", None)
    expected = "postgresql://user:sentinel@example.invalid/database"
    supplied = _BehaviorBearingDsn(expected)

    counter = TokenCounter(supplied)

    assert type(counter.postgres_dsn) is str
    assert counter.postgres_dsn == expected
    assert supplied.bool_calls == 0
    assert supplied.str_calls == 0
    assert supplied.repr_calls == 0


def test_empty_dsn_rejection_is_content_free_and_precedes_config_lookup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject empty string authority without retaining or rendering caller content."""
    monkeypatch.setattr(token_counter_module, "psycopg", None)
    supplied = _BehaviorBearingDsn("")
    config = _ConfigProbe()

    with pytest.raises(ValidationError) as captured:
        TokenCounter(supplied, config=config)

    assert captured.value.details == {
        "field": "postgres_dsn",
        "value": "<invalid>",
        "reason": "must be a non-empty string",
    }
    assert "dsn-content-sentinel" not in str(captured.value)
    assert supplied.bool_calls == 0
    assert supplied.str_calls == 0
    assert supplied.repr_calls == 0
    assert config.calls == 0


def test_non_string_dsn_is_rejected_without_executing_caller_protocols(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Reject non-string authority before truthiness, rendering, config, or database work."""
    monkeypatch.setattr(token_counter_module, "psycopg", None)
    supplied = _NonStringDsn()
    config = _ConfigProbe()

    with pytest.raises(ValidationError) as captured:
        TokenCounter(supplied, config=config)  # type: ignore[arg-type]

    assert captured.value.details["value"] == "<invalid>"
    assert "non-string-dsn-sentinel" not in str(captured.value)
    assert supplied.bool_calls == 0
    assert supplied.repr_calls == 0
    assert config.calls == 0


def test_builtin_string_dsn_characters_are_preserved_exactly(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep libpq DSN characters unchanged while taking package ownership."""
    monkeypatch.setattr(token_counter_module, "psycopg", None)
    supplied = "  postgresql://user:p%40ss@example.invalid/db?application_name=a+b  "

    counter = TokenCounter(supplied)

    assert type(counter.postgres_dsn) is str
    assert counter.postgres_dsn == supplied
