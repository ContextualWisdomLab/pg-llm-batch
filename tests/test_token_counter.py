# SPDX-License-Identifier: Apache-2.0
"""Unit tests for the pg_tiktoken SQL wrapper and DB tokenizer lookup."""

from __future__ import annotations

import pytest

from pg_llm_batch import token_counter as tc_mod
from pg_llm_batch import db as db_mod
from pg_llm_batch.exceptions import TokenLimitExceededError, ValidationError
from pg_llm_batch.models import BatchRequest
from pg_llm_batch.token_counter import BatchAccumulator, TokenCounter
from tests.conftest import FakePsycopg


@pytest.fixture()
def fake_pg(monkeypatch):
    fake = FakePsycopg()
    monkeypatch.setattr(tc_mod, "psycopg", fake)
    monkeypatch.setattr(tc_mod, "UndefinedFunction", fake.errors.UndefinedFunction)
    monkeypatch.setattr(db_mod, "psycopg", fake)
    return fake


def test_dsn_required():
    with pytest.raises(ValidationError):
        TokenCounter("")


def test_count_tokens_uses_pg_tiktoken_wrapper(fake_pg):
    # token_fn counts whitespace words
    counter = TokenCounter("postgresql://x")
    assert counter._pg_available is True
    assert counter.count_tokens("hello world foo", "gpt-4o") == 3
    assert counter.count_tokens("", "gpt-4o") == 0


def test_db_tokenizer_lookup_falls_back_to_model_name(fake_pg):
    counter = TokenCounter("postgresql://x")
    # llm_endpoint_models returns nothing -> tokenizer name is the model name
    assert counter.get_tiktoken_name("gpt-4o") == "gpt-4o"


def test_db_tokenizer_lookup_prefers_mapping(fake_pg, monkeypatch):
    monkeypatch.setattr(
        tc_mod,
        "get_model_metadata",
        lambda dsn, model: {"mode": "chat", "tokenizer_model": "o200k_base"},
    )
    counter = TokenCounter("postgresql://x")
    assert counter.get_tiktoken_name("some-deployment") == "o200k_base"


def test_count_batch_tokens_aggregates(fake_pg):
    counter = TokenCounter("postgresql://x")
    requests = [
        BatchRequest(user_prompt="one two", model="gpt-4o", system_prompt="sys"),
        BatchRequest(user_prompt="a b c", model="gpt-4o"),
    ]
    stats = counter.count_batch_tokens(requests)
    # req1: system 1 + user 2 = 3; req2: user 3 = 3
    assert stats["total_tokens"] == 6
    assert stats["request_count"] == 2
    assert stats["total_system_tokens"] == 1


def test_count_batch_tokens_enforces_limit(fake_pg):
    counter = TokenCounter("postgresql://x")
    counter.effective_limit = 2
    requests = [BatchRequest(user_prompt="a b c d", model="gpt-4o")]
    with pytest.raises(TokenLimitExceededError):
        counter.count_batch_tokens(requests)


def test_split_oversized_batch(fake_pg):
    counter = TokenCounter("postgresql://x")
    counter.effective_limit = 3
    counter.MAX_REQUESTS_PER_INTERNAL_BATCH = 100
    requests = [
        BatchRequest(user_prompt="a b", model="m"),  # 2
        BatchRequest(user_prompt="c d", model="m"),  # 2 -> new batch
        BatchRequest(user_prompt="e", model="m"),    # 1 -> fits with prev
    ]
    batches = counter.split_oversized_batch(requests)
    assert len(batches) == 2
    assert [len(b) for b in batches] == [1, 2]


def test_batch_accumulator_would_exceed_and_drain(fake_pg):
    counter = TokenCounter("postgresql://x")
    acc = BatchAccumulator(counter, "gpt-4o", max_records=2, max_bytes=10_000)
    acc.add_entry("r1", '{"a":1}', tokens=5, byte_size=8)
    assert acc.would_exceed(1, 1) is False  # 1 record, under max_records
    acc.add_entry("r2", '{"b":2}', tokens=5, byte_size=8)
    assert acc.would_exceed(1, 1) is True  # would be 3rd record > max_records=2
    drained = acc.drain()
    assert drained["record_count"] == 2
    assert drained["request_ids"] == ["r1", "r2"]
    assert acc.record_count == 0  # reset after drain


def test_empty_batches_and_oversized_single_request(fake_pg):
    counter = TokenCounter("postgresql://x")
    assert counter.count_batch_tokens([]) == {
        "total_tokens": 0,
        "total_system_tokens": 0,
        "total_user_tokens": 0,
        "request_count": 0,
        "average_tokens_per_request": 0,
        "max_tokens_per_request": 0,
        "min_tokens_per_request": 0,
        "token_breakdown": [],
    }
    assert counter.split_oversized_batch([]) == []
    counter.effective_limit = 1
    with pytest.raises(TokenLimitExceededError, match="oversized_request"):
        counter.split_oversized_batch([BatchRequest(user_prompt="two tokens", model="m")])


def test_config_resolution_buffer_validation_and_encoder_cache(fake_pg, monkeypatch):
    class Config:
        def __init__(self, values=None, error=False):
            self.values = values or {}
            self.error = error

        def get(self, category, key, default):
            if self.error:
                raise RuntimeError("config unavailable")
            return self.values.get((category, key), default)

    counter = TokenCounter(
        "postgresql://x",
        config=Config({("token_limits", "buffer_percentage"): None}),
    )
    assert counter.buffer_percentage == counter.DEFAULT_BUFFER_PERCENTAGE
    assert counter._resolve_config_value("x", "y", 7) == 7
    counter.config = Config(error=True)
    assert counter._resolve_config_value("x", "y", 8) == 8

    for invalid in (-1, 51):
        with pytest.raises(ValidationError, match="between 0 and 50"):
            TokenCounter("postgresql://x", buffer_percentage=invalid)

    calls = []
    monkeypatch.setattr(
        counter,
        "get_tiktoken_name",
        lambda model: calls.append(model) or "o200k_base",
    )
    assert counter.get_encoder("deployment") is counter.get_encoder("deployment")
    assert calls == ["deployment"]


def test_count_tokens_fails_closed_when_extension_disappears(fake_pg, monkeypatch):
    counter = TokenCounter("postgresql://x")
    monkeypatch.setattr(
        counter,
        "_count_tokens_postgres",
        lambda _text, _model: (_ for _ in ()).throw(fake_pg.errors.UndefinedFunction()),
    )
    with pytest.raises(RuntimeError, match="requires pg_tiktoken"):
        counter.count_tokens("hello", "gpt-4o")
    assert counter._pg_available is False

    monkeypatch.setattr(tc_mod, "psycopg", None)
    unavailable = TokenCounter("postgresql://x")
    with pytest.raises(RuntimeError, match="requires pg_tiktoken"):
        unavailable.count_tokens("hello", "gpt-4o")
    with pytest.raises(RuntimeError, match="integration is unavailable"):
        unavailable._count_tokens_postgres("hello", "gpt-4o")


def test_pg_tiktoken_probe_failure_closes_connection(monkeypatch):
    class Connection:
        closed = False

        def close(self):
            self.closed = True

    counter = object.__new__(TokenCounter)
    counter._pg_conn = Connection()
    monkeypatch.setattr(tc_mod, "psycopg", object())
    monkeypatch.setattr(
        counter,
        "_get_pg_conn",
        lambda: (_ for _ in ()).throw(OSError("database unavailable")),
    )
    assert counter._ensure_pg_tiktoken() is False
    assert counter._pg_conn is None
    monkeypatch.setattr(tc_mod, "psycopg", None)
    assert counter._ensure_pg_tiktoken() is False

    monkeypatch.setattr(tc_mod, "psycopg", object())
    counter._pg_conn = None
    assert counter._ensure_pg_tiktoken() is False


def test_postgres_count_falls_back_to_encode(fake_pg):
    class Cursor:
        def __init__(self):
            self.calls = 0

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def execute(self, sql, _params):
            self.calls += 1
            if "tiktoken_count" in sql:
                raise fake_pg.errors.UndefinedFunction()

        def fetchone(self):
            return (4,)

    cursor = Cursor()

    class Connection:
        closed = False

        def cursor(self):
            return cursor

    counter = TokenCounter("postgresql://x")
    counter._pg_conn = Connection()
    assert counter._count_tokens_postgres("one two three four", "gpt-4o") == 4
    assert cursor.calls == 2


def test_postgres_count_handles_empty_driver_rows(fake_pg):
    class Cursor:
        def __init__(self, *, fallback):
            self.fallback = fallback

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def execute(self, sql, _params):
            if self.fallback and "tiktoken_count" in sql:
                raise fake_pg.errors.UndefinedFunction()

        def fetchone(self):
            return None

    class Connection:
        closed = False

        def __init__(self, cursor):
            self._cursor = cursor

        def cursor(self):
            return self._cursor

    counter = TokenCounter("postgresql://x")
    counter._pg_conn = Connection(Cursor(fallback=False))
    assert counter._count_tokens_postgres("text", "model") == 0
    counter._pg_conn = Connection(Cursor(fallback=True))
    with pytest.raises(fake_pg.errors.UndefinedFunction):
        counter._count_tokens_postgres("text", "model")


def test_accumulator_all_limits_and_jsonl(fake_pg):
    counter = TokenCounter("postgresql://x")
    counter.effective_limit = 5
    acc = BatchAccumulator(counter, "gpt-4o", max_records=2, max_bytes=10)
    assert acc.compute_tokens("system", "two words") == (3, 1, 2)
    assert BatchAccumulator.compute_byte_size("é") == 3
    assert acc.drain() == {}
    acc.add_entry("r1", '{"a":1}', tokens=4, byte_size=8)
    assert acc.would_exceed(tokens=2, byte_size=1) is True
    acc.token_limit = 100
    assert acc.would_exceed(tokens=1, byte_size=3) is True
    acc.max_bytes = 100
    acc.max_records = 1
    assert acc.would_exceed(tokens=1, byte_size=1) is True
    acc.max_records = 2
    assert acc.would_exceed(tokens=1, byte_size=1) is False
    assert acc.to_jsonl() == '{"a":1}\n'
