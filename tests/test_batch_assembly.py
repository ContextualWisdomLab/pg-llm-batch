# SPDX-License-Identifier: Apache-2.0
"""Unit tests for in-memory JSONL batch assembly."""

from __future__ import annotations

import json

import pytest

from pg_llm_batch import db as db_mod
from pg_llm_batch import orchestrator as orch_mod
from pg_llm_batch import token_counter as tc_mod
from pg_llm_batch.orchestrator import PostgresBatchOrchestrator
from pg_llm_batch.token_counter import TokenCounter
from tests.conftest import FakePsycopg


@pytest.fixture()
def fake_pg(monkeypatch):
    fake = FakePsycopg()
    monkeypatch.setattr(tc_mod, "psycopg", fake)
    monkeypatch.setattr(tc_mod, "UndefinedFunction", fake.errors.UndefinedFunction)
    monkeypatch.setattr(db_mod, "psycopg", fake)
    monkeypatch.setattr(orch_mod, "psycopg", fake)
    # no per-model metadata (chat mode default, no tokenizer override)
    monkeypatch.setattr(db_mod, "get_model_metadata", lambda dsn, model: None)
    return fake


def test_build_json_entry_chat():
    entry = PostgresBatchOrchestrator._build_json_entry(
        "req-1", "gpt-4o", "chat", "you are helpful", "hi there"
    )
    assert entry["custom_id"] == "req-1"
    assert entry["url"] == "/v1/chat/completions"
    assert entry["body"]["messages"] == [
        {"role": "system", "content": "you are helpful"},
        {"role": "user", "content": "hi there"},
    ]


def test_build_json_entry_embedding():
    entry = PostgresBatchOrchestrator._build_json_entry(
        "req-2", "text-embed", "embedding", "", "vectorize me"
    )
    assert entry["url"] == "/v1/embeddings"
    assert entry["body"] == {"model": "text-embed", "input": "vectorize me"}


def test_assemble_payloads_single_file(fake_pg):
    orch = PostgresBatchOrchestrator("postgresql://x")
    counter = TokenCounter("postgresql://x")
    rows = [
        ("11111111-1111-1111-1111-111111111111", "sys", "hello world", "gpt-4o"),
        ("22222222-2222-2222-2222-222222222222", "sys", "foo bar baz", "gpt-4o"),
    ]
    payloads = orch._assemble_payloads(counter, rows)
    assert len(payloads) == 1
    meta = payloads[0]
    assert meta["record_count"] == 2
    # tokens: r1 sys(1)+user(2)=3 ; r2 sys(1)+user(3)=4 -> total 7
    assert meta["total_tokens"] == 7
    # each line is valid JSON with the right custom_id
    parsed = [json.loads(line) for line in meta["lines"]]
    assert [p["custom_id"] for p in parsed] == [rows[0][0], rows[1][0]]


def test_assemble_payloads_splits_on_token_limit(fake_pg):
    orch = PostgresBatchOrchestrator("postgresql://x")
    counter = TokenCounter("postgresql://x")
    counter.effective_limit = 4  # force a split
    rows = [
        ("11111111-1111-1111-1111-111111111111", "", "a b c", "gpt-4o"),  # 3
        ("22222222-2222-2222-2222-222222222222", "", "d e f", "gpt-4o"),  # 3 -> new
    ]
    payloads = orch._assemble_payloads(counter, rows)
    assert len(payloads) == 2
    assert payloads[0]["part_index"] == 0
    assert payloads[1]["part_index"] == 1
    assert all(p["record_count"] == 1 for p in payloads)
