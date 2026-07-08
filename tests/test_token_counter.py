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
