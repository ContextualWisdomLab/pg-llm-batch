# SPDX-License-Identifier: Apache-2.0
"""Regression contract for post-handoff streaming transport failures."""

from __future__ import annotations

from collections import deque
from typing import Any, AsyncIterator

import aiohttp
import pytest

import pg_llm_batch.batch_api_client as batch_api_client_module
from pg_llm_batch import BatchResultRecord, StreamingBatchAPIClient
from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials


class _ResponseContext:
    """Track deterministic response-context entry and exit counts."""

    status = 200
    headers: dict[str, str] = {}

    def __init__(self) -> None:
        self.enter_count = 0
        self.exit_count = 0

    async def __aenter__(self) -> "_ResponseContext":
        """Enter the fake response context exactly once per request handoff."""
        self.enter_count += 1
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        """Record closure of the fake response context."""
        self.exit_count += 1


class _ClosingFailureResponse(_ResponseContext):
    """Raise one transport failure while closing a handed-off response."""

    async def __aexit__(self, *_exc: Any) -> None:
        """Record closure and raise one deterministic transport failure."""
        self.exit_count += 1
        raise aiohttp.ClientPayloadError("response close failure")


class _FailingChunkStream:
    """Yield one record and then fail the active response body."""

    def __init__(self) -> None:
        self.requested_sizes: list[int] = []

    async def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
        """Yield one valid line before a deterministic payload failure."""
        self.requested_sizes.append(size)
        yield b'{"id":1}\n'
        raise aiohttp.ClientPayloadError("mid-stream payload failure")


class _FailingStreamingResponse(_ResponseContext):
    """Response whose bounded content fails after one valid record."""

    content_length = None

    def __init__(self) -> None:
        super().__init__()
        self.content = _FailingChunkStream()


class _QueuedSession:
    """Return queued response contexts and record every GET attempt."""

    def __init__(self, responses: list[_ResponseContext]) -> None:
        self.responses = deque(responses)
        self.calls: list[tuple[str, dict[str, Any]]] = []

    def get(self, url: str, **kwargs: Any) -> _ResponseContext:
        """Return the next response context for one exact request attempt."""
        self.calls.append((url, kwargs))
        if not self.responses:
            raise AssertionError("post-handoff failure unexpectedly retried the GET")
        return self.responses.popleft()

    async def close(self) -> None:
        """Satisfy the batch client's session lifecycle contract."""
        return None


def _credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic HTTPS credentials for the transport contract."""
    return GatewayCredentials(url="https://gw.example/v1", api_key="secret")


async def test_post_handoff_payload_failure_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A body-stream failure after response handoff performs no second GET."""
    first_response = _ResponseContext()
    second_response = _ResponseContext()
    session = _QueuedSession([first_response, second_response])
    client = BatchAPIClient(
        "postgresql://unit",
        _credentials,
        max_retry_attempts=3,
        retry_base_delay_seconds=0,
        retry_max_delay_seconds=0,
    )
    client._session = session
    sleeps: list[float] = []

    async def _record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(batch_api_client_module.asyncio, "sleep", _record_sleep)
    payload_failure = aiohttp.ClientPayloadError("mid-stream payload failure")

    with pytest.raises(aiohttp.ClientPayloadError, match="mid-stream payload failure") as exc_info:
        async with client._request(
            "get",
            "https://gw.example/v1/files/out-1/content",
            operation="Result file download",
            headers={"Authorization": "Bearer secret"},
        ):
            raise payload_failure

    assert exc_info.value is payload_failure
    assert len(session.calls) == 1
    assert sleeps == []
    assert first_response.enter_count == 1
    assert first_response.exit_count == 1
    assert second_response.enter_count == 0
    assert second_response.exit_count == 0


async def test_post_handoff_close_failure_is_not_retried(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A response-close transport failure cannot reopen the handed-off GET."""
    first_response = _ClosingFailureResponse()
    second_response = _ResponseContext()
    session = _QueuedSession([first_response, second_response])
    client = BatchAPIClient(
        "postgresql://unit",
        _credentials,
        max_retry_attempts=3,
        retry_base_delay_seconds=0,
        retry_max_delay_seconds=0,
    )
    client._session = session
    sleeps: list[float] = []

    async def _record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(batch_api_client_module.asyncio, "sleep", _record_sleep)

    with pytest.raises(aiohttp.ClientPayloadError, match="response close failure"):
        async with client._request(
            "get",
            "https://gw.example/v1/files/out-1/content",
            operation="Result file download",
            headers={"Authorization": "Bearer secret"},
        ):
            pass

    assert len(session.calls) == 1
    assert sleeps == []
    assert first_response.enter_count == 1
    assert first_response.exit_count == 1
    assert second_response.enter_count == 0
    assert second_response.exit_count == 0


async def test_streaming_payload_failure_never_restarts_or_duplicates(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A mid-file payload failure closes once without restarting byte zero."""
    first_response = _FailingStreamingResponse()
    second_response = _FailingStreamingResponse()
    session = _QueuedSession([first_response, second_response])
    client = StreamingBatchAPIClient(
        "postgresql://unit",
        _credentials,
        max_retry_attempts=3,
        retry_base_delay_seconds=0,
        retry_max_delay_seconds=0,
    )
    client._session = session
    sleeps: list[float] = []

    async def _record_sleep(delay: float) -> None:
        sleeps.append(delay)

    async def _terminal_status(
        _batch_id: str,
        _endpoint_alias: str,
    ) -> dict[str, Any]:
        return {
            "id": "batch-1",
            "status": "completed",
            "is_complete": True,
            "output_file_id": "out-1",
            "error_file_id": None,
        }

    monkeypatch.setattr(batch_api_client_module.asyncio, "sleep", _record_sleep)
    monkeypatch.setattr(client, "get_batch_status", _terminal_status)

    async with client.open_batch_records("batch-1", "default") as records:
        assert await anext(records) == BatchResultRecord(
            "batch-1", "result", {"id": 1}
        )
        with pytest.raises(aiohttp.ClientPayloadError, match="mid-stream payload failure"):
            await anext(records)

    assert len(session.calls) == 1
    assert sleeps == []
    assert first_response.enter_count == 1
    assert first_response.exit_count == 1
    assert second_response.enter_count == 0
    assert second_response.exit_count == 0
