# SPDX-License-Identifier: Apache-2.0
"""Driver-port regressions for PostgreSQL batch assembly and persistence."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch import db
from pg_llm_batch import orchestrator as orchestrator_module
from pg_llm_batch.orchestrator import PostgresBatchOrchestrator


class _Cursor:
    """Expose deterministic rows for orchestrator driver-port acceptance."""

    def __init__(self, driver: _Driver) -> None:
        self.driver = driver
        self.next_one: tuple[object, ...] | None = None
        self.next_all: list[tuple[object, ...]] = []
        self._row_count = 0

    def __enter__(self) -> _Cursor:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def execute(self, query: str, params: object | None = None) -> _Cursor:
        self.driver.executions.append((query, params))
        self._row_count = 0
        if "input_file_path" in query:
            self.next_one = ("22222222-2222-2222-2222-222222222222",)
        elif "FROM llm_requests" in query and "ORDER BY created_at" in query:
            self.next_all = list(self.driver.request_rows)
        elif "SELECT queue_uuid" in query:
            self.next_one = ("33333333-3333-3333-3333-333333333333",)
        elif "SELECT file_path" in query:
            self.next_all = []
        elif "RETURNING file_uuid" in query:
            self.next_one = ("44444444-4444-4444-4444-444444444444",)
        elif "UPDATE llm_requests" in query:
            assert isinstance(params, tuple)
            self._row_count = len(params[2])
        return self

    def executemany(self, query: str, params_seq: object) -> _Cursor:
        self.driver.many.append((query, list(params_seq)))  # type: ignore[arg-type]
        return self

    def fetchone(self) -> tuple[object, ...] | None:
        return self.next_one

    def fetchall(self) -> list[tuple[object, ...]]:
        return list(self.next_all)

    def row_count(self) -> int:
        return self._row_count


class _Connection:
    """Retain one fake transaction and explicit autocommit state."""

    def __init__(self, driver: _Driver) -> None:
        self.driver = driver
        self.autocommit_values: list[bool] = []
        self.commits = 0
        self.closed = False

    def __enter__(self) -> _Connection:
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def cursor(self) -> _Cursor:
        return _Cursor(self.driver)

    def set_autocommit(self, enabled: bool) -> None:
        self.autocommit_values.append(enabled)

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        return None

    def is_closed(self) -> bool:
        return self.closed

    def close(self) -> None:
        self.closed = True


class _Driver:
    """Minimal Psycopg-free driver for the orchestrator's database boundary."""

    def __init__(self) -> None:
        self.executions: list[tuple[str, object | None]] = []
        self.many: list[tuple[str, list[object]]] = []
        self.connections: list[_Connection] = []
        self.request_rows: list[tuple[object, ...]] = []
        self.jsonb_values: list[object] = []

    def connect(
        self,
        dsn: str,
        *,
        connect_timeout_seconds: int | None = None,
    ) -> _Connection:
        assert dsn == "postgresql://x"
        assert connect_timeout_seconds is None
        connection = _Connection(self)
        self.connections.append(connection)
        return connection

    def jsonb(self, value: object) -> object:
        self.jsonb_values.append(value)
        return ("jsonb", value)


def test_orchestrator_accepts_injected_driver_without_psycopg(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Batch lookup must remain usable after the Psycopg runtime is removed."""
    driver = _Driver()
    monkeypatch.setattr(orchestrator_module, "psycopg", None)

    orchestrator = PostgresBatchOrchestrator(
        "postgresql://x",
        postgres_driver=driver,
    )

    assert orchestrator._resolve_batch_uuid("input.jsonl") == (
        "22222222-2222-2222-2222-222222222222"
    )
    assert len(driver.connections) == 1


def test_assemble_payloads_passes_driver_to_model_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Model metadata reads must not silently reacquire the legacy driver."""
    driver = _Driver()
    monkeypatch.setattr(orchestrator_module, "psycopg", None)
    metadata_calls: list[tuple[str, str, object]] = []

    def _metadata(
        dsn: str,
        model: str,
        *,
        postgres_driver: object = None,
    ) -> dict[str, str]:
        metadata_calls.append((dsn, model, postgres_driver))
        return {"mode": "embedding"}

    monkeypatch.setattr(db, "get_model_metadata", _metadata)

    class _Counter:
        effective_limit = 100
        azure_max_records_per_file = 10
        azure_max_bytes_per_file = 10_000

        def count_tokens(self, text: str, model: str) -> int:
            return 1 if text else 0

    orchestrator = PostgresBatchOrchestrator(
        "postgresql://x",
        postgres_driver=driver,
    )
    payloads = orchestrator._assemble_payloads(
        _Counter(),  # type: ignore[arg-type]
        [("req-1", "ignored", "content", "embed-model")],
    )

    assert metadata_calls == [("postgresql://x", "embed-model", driver)]
    assert payloads[0]["record_count"] == 1


def test_persist_payloads_uses_driver_jsonb_transaction_and_row_count(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persistence must not leak Psycopg JSONB or rowcount semantics past the port."""
    driver = _Driver()
    monkeypatch.setattr(orchestrator_module, "psycopg", None)
    monkeypatch.setattr(orchestrator_module, "Jsonb", None)
    orchestrator = PostgresBatchOrchestrator(
        "postgresql://x",
        postgres_driver=driver,
    )

    class _Counter:
        azure_max_files_per_job = 1

    result = orchestrator._persist_payloads(
        [
            {
                "part_index": 0,
                "record_count": 1,
                "total_tokens": 2,
                "request_ids": ["aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"],
                "lines": ['{"custom_id":"req-1"}'],
            }
        ],
        "11111111-1111-1111-1111-111111111111",
        _Counter(),  # type: ignore[arg-type]
    )

    assert len(result["ready"]) == 1
    assert result["overflow"] == []
    assert driver.jsonb_values == [
        {"text": '{"custom_id":"req-1"}\n', "line_count": 1}
    ]
    assert driver.connections[0].autocommit_values == [False]
    assert driver.connections[0].commits == 1
    assert len(driver.many) == 1
