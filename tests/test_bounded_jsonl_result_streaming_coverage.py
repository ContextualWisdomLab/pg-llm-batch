# SPDX-License-Identifier: Apache-2.0
"""Coverage edges for bounded incremental provider-result streaming."""

from __future__ import annotations

import json
from collections import deque
from typing import Any

import pytest

from pg_llm_batch import StreamingBatchAPIClient
from pg_llm_batch.batch_api_client import GatewayCredentials
from pg_llm_batch.exceptions import GatewayError


class ByteStream:
    """Yield deterministic byte chunks through the bounded stream contract."""

    def __init__(self, chunks: list[bytes]) -> None:
        self._chunks = chunks

    async def iter_chunked(self, _size: int):
        """Yield every configured chunk once."""
        for chunk in self._chunks:
            yield chunk


class Response:
    """Minimal asynchronous HTTP response for control and file routes."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.status = 200
        self.headers: dict[str, str] = {}
        self.content_length = None
        self.content = ByteStream(chunks)

    async def __aenter__(self):
        """Enter the fake response context."""
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        """Leave the fake response context."""
        return None


class Session:
    """Serve queued exact-URL responses."""

    def __init__(self, routes: dict[str, list[Response]]) -> None:
        self._routes = {url: deque(items) for url, items in routes.items()}

    def get(self, url: str, **_kwargs: Any) -> Response:
        """Return the next response for an exact URL."""
        return self._routes[url].popleft()

    async def close(self) -> None:
        """Satisfy the parent client's session lifecycle contract."""
        return None


def credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic HTTPS credentials."""
    return GatewayCredentials(url="https://gw.example/v1", api_key="secret")


def client_for_file(
    file_chunks: list[bytes],
    *,
    max_jsonl_line_bytes: int = 1024,
) -> StreamingBatchAPIClient:
    """Build a client with one completed result file."""
    status = json.dumps(
        {
            "id": "batch-1",
            "status": "completed",
            "output_file_id": "out-1",
            "request_counts": {"total": 1, "completed": 1, "failed": 0},
        }
    ).encode("utf-8")
    client = StreamingBatchAPIClient(
        "postgresql://unit",
        credentials,
        max_jsonl_line_bytes=max_jsonl_line_bytes,
    )
    client._session = Session(
        {
            "https://gw.example/v1/batches/batch-1": [Response([status])],
            "https://gw.example/v1/files/out-1/content": [Response(file_chunks)],
        }
    )
    return client


async def test_complete_newline_terminated_line_enforces_byte_limit():
    """A complete oversized line is rejected even when a newline bounds it."""
    client = client_for_file([b'{"long":"value"}\n'], max_jsonl_line_bytes=8)

    with pytest.raises(GatewayError, match="line exceeded byte limit") as exc_info:
        _ = [record async for record in client.iter_batch_records("batch-1", "default")]

    assert exc_info.value.response_data == {
        "file_kind": "result",
        "line_number": 1,
        "limit_bytes": 8,
        "bytes_buffered": 16,
    }


async def test_final_carriage_return_is_an_ignored_blank_line():
    """A final CR-only physical line exits without yielding a record."""
    client = client_for_file([b"\r"])

    records = [record async for record in client.iter_batch_records("batch-1", "default")]

    assert records == []
