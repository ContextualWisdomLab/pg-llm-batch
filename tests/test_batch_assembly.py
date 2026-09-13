# SPDX-License-Identifier: Apache-2.0
"""Unit tests for in-memory JSONL batch assembly."""

from __future__ import annotations

import json

import pytest

from pg_llm_batch import db as db_mod
from pg_llm_batch import orchestrator as orch_mod
from pg_llm_batch import token_counter as tc_mod
from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.orchestrator import BatchPayload, PostgresBatchOrchestrator
from pg_llm_batch.token_counter import TokenCounter
from tests.conftest import FakePsycopg
from tests.fake_postgres_driver_port import FakePsycopgDriverPort


@pytest.fixture()
def fake_pg(monkeypatch):
    """Route assembly tests through one shared driver-port fake."""
    fake = FakePsycopg()
    driver = FakePsycopgDriverPort(fake)
    fake.driver = driver
    monkeypatch.setattr(tc_mod, "retained_postgres_driver", lambda: driver)
    monkeypatch.setattr(db_mod, "retained_postgres_driver", lambda: driver)
    monkeypatch.setattr(orch_mod, "retained_postgres_driver", lambda: driver)
    monkeypatch.setattr(
        db_mod,
        "get_model_metadata",
        lambda dsn, model, *, postgres_driver=None: None,
    )
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
    assert meta["total_tokens"] == 7
    parsed = [json.loads(line) for line in meta["lines"]]
    assert [p["custom_id"] for p in parsed] == [rows[0][0], rows[1][0]]


def test_assemble_payloads_splits_on_token_limit(fake_pg):
    orch = PostgresBatchOrchestrator("postgresql://x")
    counter = TokenCounter("postgresql://x")
    counter.effective_limit = 4
    rows = [
        ("11111111-1111-1111-1111-111111111111", "", "a b c", "gpt-4o"),
        ("22222222-2222-2222-2222-222222222222", "", "d e f", "gpt-4o"),
    ]
    payloads = orch._assemble_payloads(counter, rows)
    assert len(payloads) == 2
    assert payloads[0]["part_index"] == 0
    assert payloads[1]["part_index"] == 1
    assert all(p["record_count"] == 1 for p in payloads)


def test_orchestrator_requires_dsn(fake_pg):
    with pytest.raises(RuntimeError, match="Postgres DSN"):
        PostgresBatchOrchestrator("")


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


def test_prepare_batches_rejects_unknown_lookup_key(monkeypatch, fake_pg):
    orch = PostgresBatchOrchestrator("postgresql://x")
    connect_calls = []
    monkeypatch.setattr(orch, "_resolve_batch_uuid", lambda _key: None)
    monkeypatch.setattr(fake_pg, "connect", lambda dsn: connect_calls.append(dsn))

    with pytest.raises(
        ValidationError, match=r"existing llm_batches\.input_file_path"
    ) as exc_info:
        orch.prepare_batches(batch_uuid="missing-input.jsonl")

    assert exc_info.value.details["field"] == "batch_uuid"
    assert exc_info.value.details["value"] == "missing-input.jsonl"
    assert connect_calls == []


def test_prepare_batches_applies_stricter_runtime_limit(monkeypatch, fake_pg):
    rows = [("r1", "system", "prompt", "gpt-4o")]
    close_calls = {"config": 0, "counter": 0}

    class Cursor:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def execute(self, sql, params):
            assert "batch_file_uuid IS NULL" in sql
            assert "batch_uuid = %s::uuid" in sql
            assert params == ("resolved",)

        def fetchall(self):
            return rows

    class Connection:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def cursor(self):
            return Cursor()

    class Config:
        def close(self):
            close_calls["config"] += 1

    config = Config()

    class Counter:
        def __init__(self, dsn, config, *, postgres_driver=None):
            assert (dsn, config) == ("postgresql://x", globals_config)
            assert postgres_driver is fake_pg.driver
            self.effective_limit = 100

        def close(self):
            close_calls["counter"] += 1

    globals_config = config
    orch = PostgresBatchOrchestrator("postgresql://x")
    monkeypatch.setattr(fake_pg, "connect", lambda _dsn: Connection())
    monkeypatch.setattr(
        orch_mod,
        "PostgresConfigStore",
        lambda _dsn, *, postgres_driver=None: globals_config,
    )
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
    assert result["ready"] == [BatchPayload("resolved", 1, 50)]
    result = orch.prepare_batches(batch_uuid="source-key")
    assert result["ready"] == [BatchPayload("resolved", 0, 100)]
    assert close_calls == {"config": 2, "counter": 2}


def test_assemble_payloads_handles_empty_model_switch_and_null_user(fake_pg, monkeypatch):
    orch = PostgresBatchOrchestrator("postgresql://x")
    counter = TokenCounter("postgresql://x")
    assert orch._assemble_payloads(counter, []) == []
    monkeypatch.setattr(
        db_mod,
        "get_model_metadata",
        lambda _dsn, model, *, postgres_driver=None: (
            {"mode": "embedding"} if model == "embed" else None
        ),
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


def test_lock_key_and_existing_payload_categorization(fake_pg):
    batch_uuid = "11111111-1111-1111-1111-111111111111"
    lock_key = PostgresBatchOrchestrator._batch_lock_key(batch_uuid)
    assert lock_key == PostgresBatchOrchestrator._batch_lock_key(batch_uuid)
    assert 0 <= lock_key <= 0x7FFF_FFFF_FFFF_FFFF

    result = PostgresBatchOrchestrator._categorize_existing_payloads(
        [
            ("memory://a", 1, 2, 0),
            ("memory://b", 3, 4, 1),
        ],
        immediate_limit=1,
    )
    assert result == {
        "ready": [BatchPayload("memory://a", 1, 2)],
        "overflow": [BatchPayload("memory://b", 3, 4)],
    }


def _persistence_connection(existing_rows=None, has_unassigned=False):
    executions = []
    many = []

    class Cursor:
        rowcount = 0
        next_one = None
        next_all = []
        file_index = 0

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return None

        def execute(self, sql, params):
            executions.append((sql, params))
            self.rowcount = 0
            if "SELECT queue_uuid" in sql:
                self.next_one = ("33333333-3333-3333-3333-333333333333",)
            elif "SELECT file_path" in sql:
                self.next_all = list(existing_rows or [])
            elif "SELECT EXISTS" in sql:
                self.next_one = (has_unassigned,)
            elif "RETURNING file_uuid" in sql:
                self.file_index += 1
                self.next_one = (
                    f"44444444-4444-4444-4444-{self.file_index:012d}",
                )
            elif "UPDATE llm_requests" in sql:
                self.rowcount = len(params[2])

        def executemany(self, sql, params):
            many.append((sql, list(params)))

        def fetchone(self):
            return self.next_one

        def fetchall(self):
            return self.next_all

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

    return Connection(), executions, many


def test_persist_payloads_separates_ready_and_overflow(monkeypatch, fake_pg):
    connection, executions, many = _persistence_connection()
    monkeypatch.setattr(fake_pg, "connect", lambda _dsn: connection)
    monkeypatch.setattr(fake_pg.driver, "jsonb", lambda value: ("jsonb", value))
    counter = TokenCounter("postgresql://x")
    counter.azure_max_files_per_job = 1
    batch_uuid = "11111111-1111-1111-1111-111111111111"
    payloads = [
        {
            "part_index": 0,
            "record_count": 1,
            "total_tokens": 2,
            "request_ids": ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"],
            "lines": ['{"custom_id":"r1"}'],
        },
        {
            "part_index": 1,
            "record_count": 1,
            "total_tokens": 3,
            "request_ids": ["bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb"],
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
        payloads, batch_uuid, counter
    )
    assert len(result["ready"]) == 1
    assert len(result["overflow"]) == 2
    assert result["ready"][0].file_path.startswith("memory://file_")
    assert result["overflow"][0].total_tokens == 3
    assert connection.autocommit is False
    assert connection.commits == 1
    assert len(many) == 2
    assert many[0][1][0][0] == "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"
    assert any("pg_advisory_xact_lock" in sql for sql, _params in executions)
    assert sum("UPDATE llm_requests" in sql for sql, _params in executions) == 2
    assert any(params[1][0] == "jsonb" for _sql, params in executions if len(params) == 2)
    batch_updates = [item for item in executions if "UPDATE llm_batches" in item[0]]
    assert batch_updates[0][1] == (2, 5, batch_uuid)


def test_persist_payloads_returns_existing_preparation(monkeypatch, fake_pg):
    existing = [
        ("memory://existing-0", 2, 10, 0),
        ("memory://existing-1", 1, 7, 1),
    ]
    connection, executions, many = _persistence_connection(existing_rows=existing)
    monkeypatch.setattr(fake_pg, "connect", lambda _dsn: connection)
    counter = TokenCounter("postgresql://x")
    counter.azure_max_files_per_job = 1
    batch_uuid = "11111111-1111-1111-1111-111111111111"

    result = PostgresBatchOrchestrator("postgresql://x")._persist_payloads(
        [], batch_uuid, counter
    )

    assert result == {
        "ready": [BatchPayload("memory://existing-0", 2, 10)],
        "overflow": [BatchPayload("memory://existing-1", 1, 7)],
    }
    assert connection.commits == 1
    assert many == []
    assert not any("INSERT INTO llm_batch_files" in sql for sql, _ in executions)


def test_existing_preparation_rejects_new_unassigned_requests(monkeypatch, fake_pg):
    connection, _executions, many = _persistence_connection(
        existing_rows=[("memory://existing", 1, 2, 0)],
        has_unassigned=True,
    )
    monkeypatch.setattr(fake_pg, "connect", lambda _dsn: connection)
    counter = TokenCounter("postgresql://x")
    batch_uuid = "11111111-1111-1111-1111-111111111111"

    with pytest.raises(ValidationError, match="additional queued requests"):
        PostgresBatchOrchestrator("postgresql://x")._persist_payloads(
            [], batch_uuid, counter
        )

    assert connection.commits == 0
    assert many == []
