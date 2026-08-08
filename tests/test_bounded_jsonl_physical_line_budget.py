# SPDX-License-Identifier: Apache-2.0
"""Regression tests for the batch-wide physical JSONL line budget."""

from __future__ import annotations

import json
from collections import deque
from typing import Any

import pytest

from pg_llm_batch import BatchResultRecord, StreamingBatchAPIClient
from pg_llm_batch.batch_api_client import GatewayCredentials
from pg_llm_batch.exceptions import GatewayError, ValidationError


class _ByteStream:
    """Yield deterministic provider-controlled chunks."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int):
        """Yield configured chunks without whole-body materialization."""
        for chunk in self._chunks:
            yield chunk


class _Response:
    """Minimal async response for one control-plane or file request."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.status = 200
        self.headers: dict[str, str] = {}
        self.content_length = None
        self.content = _ByteStream(chunks)

    async def __aenter__(self):
        """Enter the fake response context."""
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        """Leave the fake response context."""
        return None


class _Session:
    """Serve queued responses for exact request URLs."""

    def __init__(self, routes: dict[str, list[_Response]]) -> None:
        self._routes = {url: deque(items) for url, items in routes.items()}

    def get(self, url: str, **_kwargs: Any) -> _Response:
        """Return the next response for one exact URL."""
        return self._routes[url].popleft()

    async def close(self) -> None:
        """Satisfy the parent session lifecycle contract."""
        return None


def _credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic HTTPS credentials."""
    return GatewayCredentials(url="https://gw.example/v1", api_key="secret")


def _client(
    *,
    output_chunks: list[bytes],
    error_chunks: list[bytes] | None = None,
    max_jsonl_physical_lines: int,
) -> StreamingBatchAPIClient:
    """Build a completed batch with one or two provider JSONL files."""
    status = {
        "id": "batch-1",
        "status": "completed",
        "output_file_id": "out-1",
        "request_counts": {"total": 2, "completed": 1, "failed": 1},
    }
    routes = {
        "https://gw.example/v1/files/out-1/content": [_Response(output_chunks)]
    }
    if error_chunks is not None:
        status["error_file_id"] = "err-1"
        routes["https://gw.example/v1/files/err-1/content"] = [_Response(error_chunks)]
    status_bytes = json.dumps(status).encode("utf-8")
    routes["https://gw.example/v1/batches/batch-1"] = [_Response([status_bytes])]
    client = StreamingBatchAPIClient(
        "postgresql://unit",
        _credentials,
        max_jsonl_physical_lines=max_jsonl_physical_lines,
    )
    client._session = _Session(routes)
    return client


@pytest.mark.parametrize("value", [0, -1, True, 1.5, "10"])
def test_streaming_client_rejects_invalid_physical_line_limit(value: Any):
    """The physical-line ceiling is a strict positive integer."""
    with pytest.raises(ValidationError) as exc_info:
        StreamingBatchAPIClient(
            "postgresql://unit",
            _credentials,
            max_jsonl_physical_lines=value,
        )

    assert exc_info.value.field == "max_jsonl_physical_lines"


async def test_blank_lines_consume_the_physical_line_budget_before_record_parsing():
    """Blank-line amplification stops at the batch line ceiling."""
    client = _client(
        output_chunks=[b"\n\n{\"id\":1}\n"],
        max_jsonl_physical_lines=2,
    )

    with pytest.raises(GatewayError, match="physical line limit") as exc_info:
        _ = [
            record
            async for record in client.iter_batch_records("batch-1", "default")
        ]

    assert exc_info.value.response_data == {
        "file_kind": "result",
        "file_line_number": 3,
        "batch_line_count": 3,
        "limit_lines": 2,
    }


async def test_physical_line_budget_is_shared_across_result_and_error_files():
    """Result and error files consume one batch-wide processing budget."""
    client = _client(
        output_chunks=[b'{"id":1}\n'],
        error_chunks=[b'{"id":2}\n'],
        max_jsonl_physical_lines=1,
    )
    records = client.iter_batch_records("batch-1", "default")

    assert await anext(records) == BatchResultRecord(
        "batch-1", "result", {"id": 1}
    )
    with pytest.raises(GatewayError, match="physical line limit") as exc_info:
        await anext(records)

    assert exc_info.value.response_data == {
        "file_kind": "error",
        "file_line_number": 1,
        "batch_line_count": 2,
        "limit_lines": 1,
    }
