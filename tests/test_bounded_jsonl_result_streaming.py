# SPDX-License-Identifier: Apache-2.0
"""Contract tests for bounded incremental provider-result streaming."""

from __future__ import annotations

import json
from collections import deque
from typing import Any

import pytest

from pg_llm_batch import BatchResultRecord, StreamingBatchAPIClient
from pg_llm_batch.batch_api_client import GatewayCredentials
from pg_llm_batch.exceptions import GatewayError, ValidationError


class ChunkStream:
    """Expose caller-controlled chunks without whole-body materialization."""

    def __init__(self, chunks: list[Any]) -> None:
        self.chunks = chunks
        self.requested_sizes: list[int] = []

    async def iter_chunked(self, size: int):
        """Yield the configured chunks and record the requested bound."""
        self.requested_sizes.append(size)
        for chunk in self.chunks:
            yield chunk


class StreamResponse:
    """Minimal asynchronous response with a bounded byte stream."""

    def __init__(
        self,
        status: int,
        chunks: list[Any],
        *,
        content_length: int | None = None,
    ) -> None:
        self.status = status
        self.headers: dict[str, str] = {}
        self.content = ChunkStream(chunks)
        self.content_length = content_length

    async def json(self):
        """Reject accidental whole-body JSON parsing."""
        raise AssertionError("whole-body json() must not be used")

    async def text(self):
        """Reject accidental whole-body text parsing."""
        raise AssertionError("whole-body text() must not be used")

    async def __aenter__(self):
        """Enter the fake response context."""
        return self

    async def __aexit__(self, *_exc):
        """Leave the fake response context."""
        return None


class MissingStreamResponse(StreamResponse):
    """Response whose content object lacks ``iter_chunked``."""

    def __init__(self, status: int = 200) -> None:
        super().__init__(status, [])
        self.content = object()


class RouteSession:
    """Return queued responses for exact GET URLs."""

    def __init__(self, routes: dict[str, list[StreamResponse]]) -> None:
        self.routes = {url: deque(responses) for url, responses in routes.items()}
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> StreamResponse:
        """Return the next configured response for ``url``."""
        self.calls.append((url, kwargs))
        queue = self.routes.get(url)
        if not queue:
            raise AssertionError(f"no response left for GET {url}")
        return queue.popleft()

    async def close(self) -> None:
        """Satisfy the parent client session contract."""
        return None


def _credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic HTTPS credentials for unit tests."""
    return GatewayCredentials(url="https://gw.example/v1", api_key="secret")


def _json_response(payload: dict[str, Any], status: int = 200) -> StreamResponse:
    """Build a control-plane response encoded as one byte chunk."""
    encoded = json.dumps(payload).encode("utf-8")
    return StreamResponse(status, [encoded], content_length=len(encoded))


def _client(
    status_payload: dict[str, Any],
    file_responses: dict[str, StreamResponse],
    **kwargs: Any,
) -> StreamingBatchAPIClient:
    """Build a streaming client with one status response and file routes."""
    batch_id = str(status_payload.get("id") or "batch-1")
    routes: dict[str, list[StreamResponse]] = {
        f"https://gw.example/v1/batches/{batch_id}": [_json_response(status_payload)]
    }
    routes.update(
        {
            f"https://gw.example/v1/files/{file_id}/content": [response]
            for file_id, response in file_responses.items()
        }
    )
    client = StreamingBatchAPIClient("postgresql://unit", _credentials, **kwargs)
    client._session = RouteSession(routes)
    return client


@pytest.mark.parametrize("field", ["max_jsonl_line_bytes", "max_jsonl_records"])
@pytest.mark.parametrize("value", [0, -1, True, 1.5, "10"])
def test_streaming_client_rejects_non_positive_integer_bounds(field: str, value: Any):
    """Constructor bounds are strict positive integers, not coercible values."""
    with pytest.raises(ValidationError) as exc_info:
        StreamingBatchAPIClient(
            "postgresql://unit",
            _credentials,
            **{field: value},
        )
    assert exc_info.value.field == field


async def test_iter_batch_records_streams_result_and_error_files_across_chunks():
    """Chunk boundaries, CRLF, blanks, and split UTF-8 never require a full body."""
    result_payload = (
        b'\r\n{"custom_id":"r1","text":"caf\xc3'
        b'\xa9"}\r\n\n{"custom_id":"r2"}'
    )
    error_payload = b'{"custom_id":"e1","error":{"code":"bad"}}\n'
    client = _client(
        {
            "id": "batch-1",
            "status": "completed",
            "output_file_id": "out-1",
            "error_file_id": "err-1",
            "request_counts": {"total": 3, "completed": 2, "failed": 1},
        },
        {
            "out-1": StreamResponse(200, [result_payload[:7], result_payload[7:31], result_payload[31:]]),
            "err-1": StreamResponse(200, [memoryview(error_payload)]),
        },
    )

    records = [record async for record in client.iter_batch_records("batch-1", "default")]

    assert records == [
        BatchResultRecord("batch-1", "result", {"custom_id": "r1", "text": "café"}),
        BatchResultRecord("batch-1", "result", {"custom_id": "r2"}),
        BatchResultRecord(
            "batch-1", "error", {"custom_id": "e1", "error": {"code": "bad"}}
        ),
    ]
    assert all(call[1]["allow_redirects"] is False for call in client._session.calls)


async def test_iter_batch_records_supports_error_only_terminal_batches():
    """Failed batches can stream a provider error file without an output file."""
    client = _client(
        {
            "id": "batch-1",
            "status": "failed",
            "error_file_id": "err-1",
            "request_counts": {"total": 1, "completed": 0, "failed": 1},
        },
        {"err-1": StreamResponse(200, [b'{"custom_id":"e1"}'])},
    )

    records = [record async for record in client.iter_batch_records("batch-1", "default")]

    assert records == [BatchResultRecord("batch-1", "error", {"custom_id": "e1"})]


async def test_iter_batch_records_rejects_incomplete_and_missing_file_identifiers():
    """Iteration fails closed when the batch is not terminal or exposes no files."""
    incomplete = _client(
        {
            "id": "batch-1",
            "status": "in_progress",
            "request_counts": {"total": 1, "completed": 0, "failed": 0},
        },
        {},
    )
    with pytest.raises(GatewayError, match="not complete") as incomplete_error:
        _ = [record async for record in incomplete.iter_batch_records("batch-1", "default")]
    assert incomplete_error.value.response_data == {
        "batch_id": "batch-1",
        "batch_status": "in_progress",
    }

    no_files = _client(
        {
            "id": "batch-1",
            "status": "completed",
            "request_counts": {"total": 0, "completed": 0, "failed": 0},
        },
        {},
    )
    with pytest.raises(GatewayError, match="no output or error file") as no_file_error:
        _ = [record async for record in no_files.iter_batch_records("batch-1", "default")]
    assert no_file_error.value.response_data == {"batch_id": "batch-1"}


async def test_streaming_parser_enforces_record_limit_during_iteration():
    """A second record fails before it is yielded when the record cap is one."""
    client = _client(
        {
            "id": "batch-1",
            "status": "completed",
            "output_file_id": "out-1",
            "request_counts": {"total": 2, "completed": 2, "failed": 0},
        },
        {"out-1": StreamResponse(200, [b'{"id":1}\n{"id":2}\n'])},
        max_jsonl_records=1,
    )
    iterator = client.iter_batch_records("batch-1", "default")

    assert await anext(iterator) == BatchResultRecord("batch-1", "result", {"id": 1})
    with pytest.raises(GatewayError, match="record limit") as exc_info:
        await anext(iterator)
    assert exc_info.value.response_data == {
        "file_kind": "result",
        "limit_records": 1,
        "record_count": 2,
    }


async def test_streaming_parser_enforces_line_limit_before_unbounded_buffering():
    """A newline-free line fails as soon as its byte buffer exceeds the cap."""
    client = _client(
        {
            "id": "batch-1",
            "status": "completed",
            "output_file_id": "out-1",
            "request_counts": {"total": 1, "completed": 1, "failed": 0},
        },
        {"out-1": StreamResponse(200, [b'{"long":', b'"value"}'])},
        max_jsonl_line_bytes=8,
    )

    with pytest.raises(GatewayError, match="line exceeded byte limit") as exc_info:
        _ = [record async for record in client.iter_batch_records("batch-1", "default")]
    assert exc_info.value.response_data == {
        "file_kind": "result",
        "line_number": 1,
        "limit_bytes": 8,
        "bytes_buffered": 16,
    }


async def test_streaming_parser_enforces_declared_and_observed_download_limits():
    """Declared and streamed byte overages use body-free bounded diagnostics."""
    status = {
        "id": "batch-1",
        "status": "completed",
        "output_file_id": "out-1",
        "request_counts": {"total": 1, "completed": 1, "failed": 0},
    }
    declared = _client(
        status,
        {"out-1": StreamResponse(200, [b"{}"], content_length=9)},
        max_download_bytes=8,
    )
    with pytest.raises(GatewayError, match="exceeded download limit") as declared_error:
        _ = [record async for record in declared.iter_batch_records("batch-1", "default")]
    assert declared_error.value.response_data == {
        "limit_bytes": 8,
        "declared_bytes": 9,
        "bytes_read": 0,
    }

    observed = _client(
        status,
        {"out-1": StreamResponse(200, [b'{"a":1}', b"\n"])},
        max_download_bytes=7,
    )
    with pytest.raises(GatewayError, match="exceeded download limit") as observed_error:
        _ = [record async for record in observed.iter_batch_records("batch-1", "default")]
    assert observed_error.value.response_data == {
        "limit_bytes": 7,
        "declared_bytes": None,
        "bytes_read": 7,
    }


@pytest.mark.parametrize(
    ("response", "message", "error_type"),
    [
        (MissingStreamResponse(), "bounded byte stream", "MissingBoundedStream"),
        (StreamResponse(200, [object()]), "non-byte stream chunk", "InvalidByteChunk"),
    ],
)
async def test_streaming_parser_rejects_missing_or_non_byte_streams(
    response: StreamResponse,
    message: str,
    error_type: str,
):
    """Custom adapters must provide a byte-only bounded chunk iterator."""
    client = _client(
        {
            "id": "batch-1",
            "status": "completed",
            "output_file_id": "out-1",
            "request_counts": {"total": 1, "completed": 1, "failed": 0},
        },
        {"out-1": response},
    )

    with pytest.raises(GatewayError, match=message) as exc_info:
        _ = [record async for record in client.iter_batch_records("batch-1", "default")]
    assert exc_info.value.response_data == {"error_type": error_type}


@pytest.mark.parametrize(
    ("payload", "message", "response_data"),
    [
        (
            b"\xff\n",
            "invalid UTF-8",
            {
                "file_kind": "result",
                "line_number": 1,
                "error_type": "UnicodeDecodeError",
                "byte_offset": 0,
            },
        ),
        (
            b"{not-json}\n",
            "Malformed result line 1",
            {"file_kind": "result", "line_number": 1},
        ),
        (
            b"[]\n",
            "Non-object result line 1",
            {
                "file_kind": "result",
                "line_number": 1,
                "response_type": "list",
            },
        ),
    ],
)
async def test_streaming_parser_rejects_invalid_utf8_json_and_non_objects(
    payload: bytes,
    message: str,
    response_data: dict[str, Any],
):
    """Provider-controlled line content never escapes typed bounded errors."""
    client = _client(
        {
            "id": "batch-1",
            "status": "completed",
            "output_file_id": "out-1",
            "request_counts": {"total": 1, "completed": 1, "failed": 0},
        },
        {"out-1": StreamResponse(200, [payload])},
    )

    with pytest.raises(GatewayError, match=message) as exc_info:
        _ = [record async for record in client.iter_batch_records("batch-1", "default")]
    assert exc_info.value.response_data == response_data


async def test_streaming_parser_rejects_non_success_file_response_without_body():
    """A final non-success file response is reported without reading its body."""
    response = StreamResponse(404, [b'sensitive provider body'])
    client = _client(
        {
            "id": "batch-1",
            "status": "completed",
            "output_file_id": "out-1",
            "request_counts": {"total": 1, "completed": 1, "failed": 0},
        },
        {"out-1": response},
    )

    with pytest.raises(GatewayError, match="Result file download failed: 404") as exc_info:
        _ = [record async for record in client.iter_batch_records("batch-1", "default")]
    assert exc_info.value.status_code == 404
    assert exc_info.value.response_data == {"file_kind": "result"}
    assert response.content.requested_sizes == []
