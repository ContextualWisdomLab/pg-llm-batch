# SPDX-License-Identifier: Apache-2.0
"""Regression tests for persisted virtual JSONL payload integrity."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch import batch_api_client as client_mod
from pg_llm_batch import db
from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials


class _Cursor:
    """Minimal cursor double for one payload row."""

    def __init__(self, driver: "_Psycopg") -> None:
        self.driver = driver

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.driver.executions.append((sql, params))

    def fetchone(self) -> Any:
        return self.driver.row


class _Connection:
    """Minimal connection double for payload reads."""

    def __init__(self, driver: "_Psycopg") -> None:
        self.driver = driver

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *exc: Any) -> None:
        return None

    def cursor(self) -> _Cursor:
        return _Cursor(self.driver)


class _Psycopg:
    """Psycopg double returning one configured JSONB value."""

    def __init__(self, content: Any) -> None:
        self.row = (content,)
        self.executions: list[tuple[str, Any]] = []

    def connect(self, dsn: str) -> _Connection:
        del dsn
        return _Connection(self)


@pytest.mark.parametrize(
    "content",
    [
        None,
        [],
        "{\"custom_id\":\"r1\"}\n",
        7,
        {},
        {"text": "{\"custom_id\":\"r1\"}\n"},
        {"line_count": 1},
        {"text": 7, "line_count": 1},
        {"text": "{\"custom_id\":\"r1\"}\n", "line_count": True},
        {"text": "{\"custom_id\":\"r1\"}\n", "line_count": -1},
        {"text": "nonempty", "line_count": 0},
        {"text": "{\"custom_id\":\"r1\"}\n", "line_count": 2},
        {
            "text": "{\"custom_id\":\"r1\"}\n",
            "line_count": 1,
            "unexpected": "field",
        },
        {"text": "{\"custom_id\":\"r1\"}", "line_count": 1},
        {"text": "\n", "line_count": 1},
        {"text": "[1, 2, 3]\n", "line_count": 1},
        {"text": "{\"value\":NaN}\n", "line_count": 1},
        {"text": "{\"value\":1e999}\n", "line_count": 1},
        {"text": "{\"a\":1,\"a\":2}\n", "line_count": 1},
    ],
)
def test_load_virtual_payload_rejects_malformed_persisted_state(
    monkeypatch: pytest.MonkeyPatch,
    content: Any,
) -> None:
    """Malformed package-owned JSONB must fail closed instead of being coerced."""
    monkeypatch.setattr(db, "psycopg", _Psycopg(content))

    with pytest.raises(db.VirtualPayloadIntegrityError) as captured:
        db.load_virtual_payload("postgresql://example", "file-1")

    assert str(captured.value) == "Stored virtual payload failed integrity validation"
    assert captured.value.__cause__ is None
    assert captured.value.__context__ is None


def test_load_virtual_payload_preserves_valid_multiline_jsonl(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Valid canonical payloads retain exact persisted UTF-8 text and framing."""
    payload = '{"custom_id":"r1","score":1.5,"body":{"input":"one"}}\n' \
        '{"custom_id":"r2","body":{"input":"two"}}\n'
    monkeypatch.setattr(
        db,
        "psycopg",
        _Psycopg({"text": payload, "line_count": 2}),
    )

    assert db.load_virtual_payload("postgresql://example", "file-1") == payload


def test_upload_validates_local_payload_before_credential_resolution(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Corrupt durable payloads must fail before secret lookup or provider I/O."""
    credential_calls: list[str] = []

    def credentials(alias: str) -> GatewayCredentials:
        credential_calls.append(alias)
        return GatewayCredentials(url="https://gw.example/v1", api_key="secret")

    def corrupt_payload(_dsn: str, _file_id: str) -> str:
        raise RuntimeError("stored payload failed integrity validation")

    monkeypatch.setattr(client_mod, "load_virtual_payload", corrupt_payload)
    client = BatchAPIClient("postgresql://example", credentials)

    async def invoke() -> None:
        with pytest.raises(RuntimeError, match="stored payload failed integrity"):
            await client.upload_jsonl("memory://file-1", "default")

    import asyncio

    asyncio.run(invoke())
    assert credential_calls == []
