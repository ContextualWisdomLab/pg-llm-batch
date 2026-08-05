# SPDX-License-Identifier: Apache-2.0
"""Tests for bounded Files and Batches control-plane JSON responses."""

from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any

import pytest

from pg_llm_batch import batch_api_client as client_mod
from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.exceptions import GatewayError, ValidationError


class ByteStream:
    """Yield deterministic response bytes while recording stream use."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.iterated = False
        self.requested_sizes: list[int] = []

    async def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
        """Yield configured chunks using the requested bounded chunk size."""
        self.iterated = True
        self.requested_sizes.append(size)
        for chunk in self.chunks:
            yield chunk


class ControlResponse:
    """Provide a bounded byte stream and reject whole-body convenience reads."""

    def __init__(
        self,
        status: int,
        chunks: list[bytes],
        *,
        content_length: Any = None,
    ) -> None:
        self.status = status
        self.headers: dict[str, str] = {}
        self.content = ByteStream(chunks)
        self.content_length = content_length
        self.json_called = False
        self.text_called = False
        self.exit_count = 0

    async def __aenter__(self) -> "ControlResponse":
        """Enter the asynchronous response context."""
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        """Record release of the response context."""
        self.exit_count += 1

    async def json(self) -> Any:
        """Fail if production code bypasses the bounded byte stream."""
        self.json_called = True
        raise AssertionError("response.json() must not read control-plane bodies")

    async def text(self) -> str:
        """Fail if production code buffers the complete body through text()."""
        self.text_called = True
        raise AssertionError("response.text() must not read control-plane bodies")


class MissingStreamResponse:
    """Represent an adapter that cannot provide bounded response bytes."""

    status = 200
    content_length = None
    content = object()


class RouteSession:
    """Route HTTP methods and URL fragments to deterministic responses."""

    def __init__(self, routes: dict[tuple[str, str], ControlResponse]) -> None:
        self.routes = routes
        self.calls: list[tuple[str, str, dict[str, Any]]] = []

    def _match(self, method: str, url: str, kwargs: dict[str, Any]) -> ControlResponse:
        """Record one request and return its configured response context."""
        self.calls.append((method, url, kwargs))
        matches = [
            (fragment, response)
            for (route_method, fragment), response in self.routes.items()
            if method == route_method and fragment in url
        ]
        if not matches:
            raise AssertionError(f"no response route for {method} {url}")
        return max(matches, key=lambda match: len(match[0]))[1]

    def get(self, url: str, **kwargs: Any) -> ControlResponse:
        """Return a configured GET response."""
        return self._match("GET", url, kwargs)

    def post(self, url: str, **kwargs: Any) -> ControlResponse:
        """Return a configured POST response."""
        return self._match("POST", url, kwargs)


def credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic provider credentials for response tests."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, "1048576", None])
def test_control_response_limit_requires_a_positive_integer(value: Any) -> None:
    """Control-plane byte limits reject booleans, non-integers, and non-positive values."""
    with pytest.raises(ValidationError, match="max_control_response_bytes"):
        BatchAPIClient(
            "postgresql://example",
            credentials,
            max_control_response_bytes=value,
        )


def test_control_response_limit_defaults_to_one_mibibyte() -> None:
    """The public control-plane resource budget remains exactly one MiB."""
    client = BatchAPIClient("postgresql://example", credentials)
    assert client.max_control_response_bytes == 1 * 1024 * 1024


async def test_declared_oversize_fails_before_stream_iteration() -> None:
    """An excessive declared length is rejected before provider bytes are consumed."""
    response = ControlResponse(200, [b'{"ok":true}'], content_length=12)
    client = BatchAPIClient(
        "postgresql://example",
        credentials,
        max_control_response_bytes=11,
    )

    with pytest.raises(GatewayError, match="exceeded download limit") as exc_info:
        await client._read_json_object(response, "Batch status")

    assert response.content.iterated is False
    assert response.json_called is False
    assert response.text_called is False
    assert exc_info.value.response_data == {
        "limit_bytes": 11,
        "declared_bytes": 12,
        "bytes_read": 0,
    }


async def test_actual_decoded_bytes_are_authoritative() -> None:
    """Streamed bytes enforce the limit even when Content-Length understates them."""
    response = ControlResponse(
        200,
        [b'{"ok":', b'true}'],
        content_length=1,
    )
    client = BatchAPIClient(
        "postgresql://example",
        credentials,
        max_control_response_bytes=10,
    )

    with pytest.raises(GatewayError, match="exceeded download limit") as exc_info:
        await client._read_json_object(response, "Batch status")

    assert exc_info.value.response_data == {
        "limit_bytes": 10,
        "declared_bytes": 1,
        "bytes_read": 6,
    }
    assert response.json_called is False
    assert response.text_called is False


async def test_exact_limit_object_is_parsed_once_after_bounded_read(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A valid exact-limit object is decoded once after the bounded stream completes."""
    decoded: list[str] = []
    original_loads = client_mod.json.loads

    def record_loads(value: str) -> Any:
        decoded.append(value)
        return original_loads(value)

    monkeypatch.setattr(client_mod.json, "loads", record_loads)
    response = ControlResponse(200, [b'{"ok":', b'true}'], content_length=11)
    client = BatchAPIClient(
        "postgresql://example",
        credentials,
        max_control_response_bytes=11,
    )

    result = await client._read_json_object(response, "Batch status")

    assert result == {"ok": True}
    assert decoded == ['{"ok":true}']
    assert response.content.requested_sizes == [64 * 1024]
    assert response.json_called is False
    assert response.text_called is False


async def test_invalid_utf8_is_body_free() -> None:
    """Strict UTF-8 failures expose only exception category and byte offset."""
    response = ControlResponse(200, [b'{"value":"', b'\xff"}'])
    client = BatchAPIClient("postgresql://example", credentials)

    with pytest.raises(GatewayError, match="invalid UTF-8") as exc_info:
        await client._read_json_object(response, "Batch status")

    assert exc_info.value.response_data == {
        "error_type": "UnicodeDecodeError",
        "byte_offset": 10,
    }
    assert response.json_called is False
    assert response.text_called is False


@pytest.mark.parametrize(
    ("chunks", "message", "details"),
    [
        ([b"{"], "invalid JSON", {"error_type": "JSONDecodeError"}),
        ([b"[]"], "non-object JSON", {"response_type": "list"}),
    ],
)
async def test_bounded_json_preserves_shape_errors(
    chunks: list[bytes],
    message: str,
    details: dict[str, str],
) -> None:
    """Malformed and non-object JSON retain bounded, content-free diagnostics."""
    response = ControlResponse(200, chunks)
    client = BatchAPIClient("postgresql://example", credentials)

    with pytest.raises(GatewayError, match=message) as exc_info:
        await client._read_json_object(response, "Batch status")

    assert exc_info.value.status_code == 200
    assert exc_info.value.response_data == details
    assert response.json_called is False
    assert response.text_called is False


async def test_missing_bounded_stream_fails_closed() -> None:
    """Custom adapters cannot fall back to whole-body response helpers."""
    client = BatchAPIClient("postgresql://example", credentials)

    with pytest.raises(GatewayError, match="bounded byte stream") as exc_info:
        await client._read_json_object(MissingStreamResponse(), "Batch status")

    assert exc_info.value.response_data == {
        "error_type": "MissingBoundedStream"
    }


async def test_all_control_plane_endpoints_use_bounded_streams(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Upload, create, status, and cancellation all share the bounded JSON boundary."""
    monkeypatch.setattr(
        client_mod,
        "load_virtual_payload",
        lambda _dsn, _file_id: '{"custom_id":"request-1"}\n',
    )
    responses = {
        ("POST", "/files"): ControlResponse(200, [b'{"id":"file-1"}']),
        ("POST", "/batches"): ControlResponse(201, [b'{"id":"batch-1"}']),
        ("GET", "/batches/batch-1"): ControlResponse(
            200,
            [b'{"status":"completed","request_counts":{}}'],
        ),
        ("POST", "/batches/batch-1/cancel"): ControlResponse(
            202,
            [b'{"status":"cancelling"}'],
        ),
    }
    session = RouteSession(responses)
    client = BatchAPIClient("postgresql://example", credentials)
    client._session = session

    assert (await client.upload_jsonl("memory://payload-1", "default"))["id"] == "file-1"
    assert (await client.create_batch_job("file-1", "default"))["id"] == "batch-1"
    status = await client.get_batch_status("batch-1", "default")
    assert status["status"] == "completed"
    assert status["is_complete"] is True
    assert (await client.cancel_batch("batch-1", "default"))["success"] is True

    assert len(session.calls) == 4
    for response in responses.values():
        assert response.content.iterated is True
        assert response.json_called is False
        assert response.text_called is False
        assert response.exit_count == 1


async def test_provider_file_keeps_independent_download_limit() -> None:
    """Provider files may exceed the control limit while staying within their file budget."""
    response = ControlResponse(200, [b'{"ok":1}\n'], content_length=9)
    client = BatchAPIClient(
        "postgresql://example",
        credentials,
        max_control_response_bytes=8,
        max_download_bytes=9,
    )
    client._session = RouteSession({("GET", "/files/output-1/content"): response})

    result = await client._download_jsonl_file(
        "output-1",
        "default",
        batch_id="batch-1",
        file_kind="result",
    )

    assert result == [{"ok": 1}]
    assert response.content.iterated is True
