# SPDX-License-Identifier: Apache-2.0
"""Tests for bounded, streamed provider result downloads."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.exceptions import GatewayError, ValidationError


class ChunkStream:
    """Yield configured byte chunks while recording stream consumption."""

    def __init__(self, chunks: list[bytes]) -> None:
        self.chunks = chunks
        self.requested_sizes: list[int] = []
        self.iterated = False

    async def iter_chunked(self, size: int):
        """Yield chunks and record the requested maximum chunk size."""
        self.requested_sizes.append(size)
        self.iterated = True
        for chunk in self.chunks:
            yield chunk


class StreamResponse:
    """Minimal aiohttp-style response exposing a streamed body."""

    def __init__(
        self,
        chunks: list[bytes],
        *,
        content_length: Any,
        status: int = 200,
    ) -> None:
        self.status = status
        self.content_length = content_length
        self.content = ChunkStream(chunks)

    async def __aenter__(self):
        """Enter the asynchronous response context."""
        return self

    async def __aexit__(self, *exc: Any):
        """Leave the asynchronous response context."""
        return None


class TextResponse:
    """Response adapter that deliberately lacks a bounded byte stream."""

    def __init__(self, text: str, *, status: int = 200) -> None:
        self.status = status
        self.content_length = None
        self._text = text
        self.text_called = False

    async def text(self) -> str:
        """Record any unsafe whole-body fallback attempt."""
        self.text_called = True
        return self._text

    async def __aenter__(self):
        """Enter the asynchronous response context."""
        return self

    async def __aexit__(self, *exc: Any):
        """Leave the asynchronous response context."""
        return None


class Session:
    """Return one configured response for every GET request."""

    def __init__(self, response: Any) -> None:
        self.response = response
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> Any:
        """Record a GET call and return the configured response context."""
        self.calls.append((url, kwargs))
        return self.response


def credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic credentials for download tests."""
    return GatewayCredentials(
        url="https://gateway.example/v1",
        api_key="secret",
    )


@pytest.mark.parametrize("value", [True, 0, -1, 1.5, "1024"])
def test_client_rejects_invalid_max_download_bytes(value: Any) -> None:
    """Download limits must be positive non-boolean integers."""
    with pytest.raises(ValidationError, match="max_download_bytes"):
        BatchAPIClient(
            "postgresql://x",
            credentials,
            max_download_bytes=value,
        )


def test_client_uses_documented_default_download_limit() -> None:
    """The public default remains the documented 128 MiB safety boundary."""
    client = BatchAPIClient("postgresql://x", credentials)
    assert client.max_download_bytes == 128 * 1024 * 1024


async def test_declared_oversize_is_rejected_before_streaming() -> None:
    """An excessive Content-Length fails before response chunks are consumed."""
    response = StreamResponse([b'{"ok":1}\n'], content_length=10)
    client = BatchAPIClient(
        "postgresql://x",
        credentials,
        max_download_bytes=9,
    )
    client._session = Session(response)

    with pytest.raises(GatewayError, match="exceeded download limit") as exc_info:
        await client._download_jsonl_file(
            "output-1",
            "default",
            batch_id="batch-1",
            file_kind="result",
        )

    assert response.content.iterated is False
    assert exc_info.value.response_data == {
        "limit_bytes": 9,
        "declared_bytes": 10,
        "bytes_read": 0,
    }


@pytest.mark.parametrize("declared_length", [True, -1, "9"])
async def test_invalid_declared_lengths_do_not_override_actual_bytes(
    declared_length: Any,
) -> None:
    """Malformed length metadata is ignored while actual bytes stay bounded."""
    response = StreamResponse(
        [b'{"ok":1}\n'],
        content_length=declared_length,
    )
    client = BatchAPIClient(
        "postgresql://x",
        credentials,
        max_download_bytes=9,
    )
    client._session = Session(response)

    result = await client._download_jsonl_file(
        "output-1",
        "default",
        batch_id="batch-1",
        file_kind="result",
    )

    assert result == [{"ok": 1}]


async def test_streamed_body_exactly_at_limit_is_accepted() -> None:
    """A valid UTF-8 JSONL body equal to the byte limit remains usable."""
    response = StreamResponse([b'{"ok":', b'1}\n'], content_length=9)
    client = BatchAPIClient(
        "postgresql://x",
        credentials,
        max_download_bytes=9,
    )
    client._session = Session(response)

    result = await client._download_jsonl_file(
        "output-1",
        "default",
        batch_id="batch-1",
        file_kind="result",
    )

    assert result == [{"ok": 1}]
    assert response.content.requested_sizes == [64 * 1024]


async def test_actual_decoded_bytes_enforce_limit_beyond_declared_length() -> None:
    """Streamed decoded bytes remain authoritative when headers understate size."""
    response = StreamResponse([b'{"ok":', b'1}\n'], content_length=1)
    client = BatchAPIClient(
        "postgresql://x",
        credentials,
        max_download_bytes=8,
    )
    client._session = Session(response)

    with pytest.raises(GatewayError, match="exceeded download limit") as exc_info:
        await client._download_jsonl_file(
            "output-1",
            "default",
            batch_id="batch-1",
            file_kind="result",
        )

    assert exc_info.value.response_data == {
        "limit_bytes": 8,
        "declared_bytes": 1,
        "bytes_read": 6,
    }


async def test_streamed_body_rejects_invalid_utf8_without_content_leakage() -> None:
    """Invalid UTF-8 becomes a typed boundary error without returning bytes."""
    response = StreamResponse([b'{"ok":"', b'\xff"}\n'], content_length=None)
    client = BatchAPIClient(
        "postgresql://x",
        credentials,
        max_download_bytes=32,
    )
    client._session = Session(response)

    with pytest.raises(GatewayError, match="invalid UTF-8") as exc_info:
        await client._download_jsonl_file(
            "output-1",
            "default",
            batch_id="batch-1",
            file_kind="result",
        )

    assert exc_info.value.response_data == {
        "error_type": "UnicodeDecodeError",
        "byte_offset": 7,
    }
    assert "xff" not in repr(exc_info.value.response_data).lower()


async def test_response_without_stream_fails_closed_before_text_buffering() -> None:
    """Adapters without a byte stream fail before whole-body buffering."""
    response = TextResponse('{"ok":1}\n')
    client = BatchAPIClient(
        "postgresql://x",
        credentials,
        max_download_bytes=9,
    )
    client._session = Session(response)

    with pytest.raises(GatewayError, match="bounded byte stream") as exc_info:
        await client._download_jsonl_file(
            "output-1",
            "default",
            batch_id="batch-1",
            file_kind="result",
        )

    assert response.text_called is False
    assert exc_info.value.response_data == {
        "error_type": "MissingBoundedStream",
    }
