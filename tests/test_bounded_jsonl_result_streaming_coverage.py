# SPDX-License-Identifier: Apache-2.0
"""Coverage and security edges for bounded provider-result streaming."""

from __future__ import annotations

import asyncio
import json
from collections import deque
from typing import Any

import pytest

from pg_llm_batch import StreamingBatchAPIClient
from pg_llm_batch.batch_api_client import DOWNLOAD_CHUNK_BYTES, GatewayCredentials
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
        self.exit_count = 0

    async def __aenter__(self):
        """Enter the fake response context."""
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        """Leave the fake response context and record deterministic cleanup."""
        self.exit_count += 1
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


def client_and_response_for_file(
    file_chunks: list[bytes],
    *,
    max_jsonl_line_bytes: int = 1024,
) -> tuple[StreamingBatchAPIClient, Response]:
    """Build a client and expose its provider-file response for lifecycle checks."""
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
    file_response = Response(file_chunks)
    client._session = Session(
        {
            "https://gw.example/v1/batches/batch-1": [Response([status])],
            "https://gw.example/v1/files/out-1/content": [file_response],
        }
    )
    return client, file_response


def client_for_file(
    file_chunks: list[bytes],
    *,
    max_jsonl_line_bytes: int = 1024,
) -> StreamingBatchAPIClient:
    """Build a client with one completed result file."""
    client, _response = client_and_response_for_file(
        file_chunks,
        max_jsonl_line_bytes=max_jsonl_line_bytes,
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


async def test_adapter_chunk_larger_than_requested_bound_fails_closed():
    """A custom adapter cannot ignore the requested transport chunk ceiling."""
    oversized_chunk = b"x" * (DOWNLOAD_CHUNK_BYTES + 1)
    client = client_for_file([oversized_chunk], max_jsonl_line_bytes=DOWNLOAD_CHUNK_BYTES * 2)

    with pytest.raises(GatewayError, match="chunk exceeded byte limit") as exc_info:
        _ = [record async for record in client.iter_batch_records("batch-1", "default")]

    assert exc_info.value.response_data == {
        "error_type": "OversizedByteChunk",
        "limit_bytes": DOWNLOAD_CHUNK_BYTES,
        "chunk_bytes": DOWNLOAD_CHUNK_BYTES + 1,
    }


@pytest.mark.parametrize(
    "payload",
    [
        b'{"value":NaN}\n',
        b'{"value":Infinity}\n',
        b'{"value":-Infinity}\n',
        b'{"duplicate":1,"duplicate":2}\n',
    ],
)
async def test_non_finite_numbers_and_duplicate_object_names_are_rejected(payload: bytes):
    """Provider lines must be interoperable JSON objects without ambiguous names."""
    client = client_for_file([payload])

    with pytest.raises(GatewayError, match="Malformed result line 1") as exc_info:
        _ = [record async for record in client.iter_batch_records("batch-1", "default")]

    assert exc_info.value.response_data == {
        "file_kind": "result",
        "line_number": 1,
    }
    assert "batch-1" not in str(exc_info.value)


async def test_malformed_line_error_does_not_disclose_provider_batch_identifier():
    """Parser diagnostics exclude otherwise valid provider identifiers."""
    client = client_for_file([b"{not-json}\n"])

    with pytest.raises(GatewayError, match="Malformed result line 1") as exc_info:
        _ = [record async for record in client.iter_batch_records("batch-1", "default")]

    assert "batch-1" not in str(exc_info.value)


async def test_context_managed_records_close_active_response_after_early_exit():
    """The supported context manager closes a provider response after loop break."""
    client, response = client_and_response_for_file([b'{"id":1}\n{"id":2}\n'])

    async with client.open_batch_records("batch-1", "default") as records:
        async for record in records:
            assert record.record == {"id": 1}
            assert response.exit_count == 0
            break

    assert response.exit_count == 1


async def test_explicit_outer_close_closes_nested_response_exactly_once():
    """Closing the public iterator owns and closes its nested file iterator."""
    client, response = client_and_response_for_file([b'{"id":1}\n{"id":2}\n'])
    records = client.iter_batch_records("batch-1", "default")

    assert (await anext(records)).record == {"id": 1}
    assert response.exit_count == 0
    await records.aclose()
    assert response.exit_count == 1
    await records.aclose()
    assert response.exit_count == 1


async def test_context_managed_records_preserve_consumer_exception_and_close():
    """Consumer failures propagate unchanged while the active response closes."""
    client, response = client_and_response_for_file([b'{"id":1}\n{"id":2}\n'])
    consumer_error = RuntimeError("consumer failed")

    with pytest.raises(RuntimeError) as exc_info:
        async with client.open_batch_records("batch-1", "default") as records:
            async for _record in records:
                raise consumer_error

    assert exc_info.value is consumer_error
    assert response.exit_count == 1


async def test_context_managed_records_preserve_cancellation_and_close():
    """Cancellation propagates while deterministic cleanup closes the response."""
    client, response = client_and_response_for_file([b'{"id":1}\n{"id":2}\n'])

    with pytest.raises(asyncio.CancelledError):
        async with client.open_batch_records("batch-1", "default") as records:
            async for _record in records:
                raise asyncio.CancelledError

    assert response.exit_count == 1


async def test_empty_stream_chunk_fails_closed_without_spinning():
    """A custom adapter must make positive byte progress on every yielded chunk."""
    client = client_for_file([b"", b'{"id":1}\n'])

    with pytest.raises(GatewayError, match="empty stream chunk") as exc_info:
        _ = [record async for record in client.iter_batch_records("batch-1", "default")]

    assert exc_info.value.response_data == {"error_type": "NoForwardProgress"}


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        (b"\xff\n", "invalid UTF-8"),
        (b'{"secret":"distinctive-value"\n', "Malformed result line 1"),
    ],
)
async def test_parser_errors_do_not_retain_provider_exception_context(
    payload: bytes,
    message: str,
):
    """Sanitized parser errors do not retain provider bytes through exception links."""
    client = client_for_file([payload])

    with pytest.raises(GatewayError, match=message) as exc_info:
        _ = [record async for record in client.iter_batch_records("batch-1", "default")]

    assert exc_info.value.__cause__ is None
    assert exc_info.value.__context__ is None
