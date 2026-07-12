# SPDX-License-Identifier: Apache-2.0
"""Unit tests for in-memory JSONL batch assembly."""

from __future__ import annotations

import json

import pytest

from pg_llm_batch import db as db_mod
from pg_llm_batch import orchestrator as orch_mod
from pg_llm_batch import token_counter as tc_mod
from pg_llm_batch.orchestrator import BatchPayload, PostgresBatchOrchestrator
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


def test_orchestrator_requires_dsn_and_driver(monkeypatch, fake_pg):
    with pytest.raises(RuntimeError, match="DSN and psycopg"):
        PostgresBatchOrchestrator("")
    monkeypatch.setattr(orch_mod, "psycopg", None)
    with pytest.raises(RuntimeError, match="DSN and psycopg"):
        PostgresBatchOrchestrator("postgresql://x")


def test_resolve_batch_uuid_direct_and_lookup(monkeypatch, fake_pg):
    orch = PostgresBatchOrchestrator("postgresql://x")
    direct = "11111111-1111-1111-1111-111111111111"
    assert orch._resolve_batch_uuid(direct) == direct

    class Cursor:
        row = ("22222222-2222-2222-2222-222222222222",)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def execute(self, sql, params):
            assert "input_file_path" in sql
            assert params == ("input.jsonl",)

        def fetchone(self):
            return self.row

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def cursor(self):
            return Cursor()

    monkeypatch.setattr(fake_pg, "connect", lambda _dsn: Connection())
    assert orch._resolve_batch_uuid("input.jsonl") == Cursor.row[0]
    Cursor.row = None
    assert orch._resolve_batch_uuid("input.jsonl") is None


def test_prepare_batches_applies_stricter_runtime_limit(monkeypatch, fake_pg):
    rows = [("r1", "system", "prompt", "gpt-4o")]

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def execute(self, _sql, params):
            assert params == ("resolved", "source-key", "source-key")

        def fetchall(self):
            return rows

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def cursor(self):
            return Cursor()

    class Counter:
        def __init__(self, dsn, config):
            assert (dsn, config) == ("postgresql://x", "config")
            self.effective_limit = 100

    orch = PostgresBatchOrchestrator("postgresql://x")
    monkeypatch.setattr(fake_pg, "connect", lambda _dsn: Connection())
    monkeypatch.setattr(orch_mod, "PostgresConfigStore", lambda _dsn: "config")
    monkeypatch.setattr(orch_mod, "TokenCounter", Counter)
    monkeypatch.setattr(orch, "_resolve_batch_uuid", lambda _key: "resolved")
    monkeypatch.setattr(
        orch,
        "_assemble_payloads",
        lambda counter, received: [
            {"part_index": 0, "record_count": len(received), "total_tokens": 1}
        ]
        if counter.effective_limit == 50
        else [],
    )
    monkeypatch.setattr(
        orch,
        "_persist_payloads",
        lambda payloads, batch_key, counter: {
            "ready": [BatchPayload(batch_key, len(payloads), counter.effective_limit)],
            "overflow": [],
        },
    )
    result = orch.prepare_batches(batch_uuid="source-key", effective_token_limit=50)
    assert result["ready"] == [BatchPayload("source-key", 1, 50)]
    result = orch.prepare_batches(batch_uuid="source-key")
    assert result["ready"] == [BatchPayload("source-key", 0, 100)]


def test_assemble_payloads_handles_empty_model_switch_and_null_user(fake_pg, monkeypatch):
    orch = PostgresBatchOrchestrator("postgresql://x")
    counter = TokenCounter("postgresql://x")
    assert orch._assemble_payloads(counter, []) == []
    monkeypatch.setattr(
        db_mod,
        "get_model_metadata",
        lambda _dsn, model: {"mode": "embedding"} if model == "embed" else None,
    )
    rows = [
        ("r1", "ignored system", "vector", "embed"),
        ("r2", "", None, "chat"),
    ]
    payloads = orch._assemble_payloads(counter, rows)
    assert len(payloads) == 2
    parsed = [json.loads(line) for payload in payloads for line in payload["lines"]]
    assert parsed[0]["body"] == {"model": "embed", "input": "vector"}
    assert parsed[1]["body"]["messages"] == [{"role": "user", "content": ""}]


def test_persist_payloads_separates_ready_and_overflow(monkeypatch, fake_pg):
    executions = []
    many = []

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def execute(self, sql, params):
            executions.append((sql, params))

        def executemany(self, sql, params):
            many.append((sql, list(params)))

    class Connection:
        autocommit = True
        commits = 0

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def cursor(self):
            return Cursor()

        def commit(self):
            self.commits += 1

    connection = Connection()
    monkeypatch.setattr(fake_pg, "connect", lambda _dsn: connection)
    monkeypatch.setattr(orch_mod, "Jsonb", lambda value: ("jsonb", value))
    counter = TokenCounter("postgresql://x")
    counter.azure_max_files_per_job = 1
    payloads = [
        {
            "part_index": 0,
            "record_count": 1,
            "total_tokens": 2,
            "request_ids": ["r1"],
            "lines": ['{"custom_id":"r1"}'],
        },
        {
            "part_index": 1,
            "record_count": 1,
            "total_tokens": 3,
            "request_ids": ["r2"],
            "lines": ['{"custom_id":"r2"}'],
        },
        {
            "part_index": 2,
            "record_count": 0,
            "total_tokens": 0,
            "request_ids": [],
            "lines": [],
        },
    ]
    result = PostgresBatchOrchestrator("postgresql://x")._persist_payloads(
        payloads, "batch-key", counter
    )
    assert len(result["ready"]) == 1
    assert len(result["overflow"]) == 2
    assert result["ready"][0].file_path.startswith("memory://file_")
    assert result["overflow"][0].total_tokens == 3
    assert connection.autocommit is False
    assert connection.commits == 1
    assert len(many) == 2
    assert many[0][1][0][0] == "r1"
    assert any(params[1][0] == "jsonb" for _sql, params in executions if len(params) == 2)
