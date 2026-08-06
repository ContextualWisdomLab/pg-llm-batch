# SPDX-License-Identifier: Apache-2.0
"""Regression contract for post-handoff streaming transport failures."""

from __future__ import annotations

from collections import deque
from typing import Any

import aiohttp
import pytest

import pg_llm_batch.batch_api_client as batch_api_client_module
from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.exceptions import GatewayError


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

    with pytest.raises(GatewayError, match="transport failed") as exc_info:
        async with client._request(
            "get",
            "https://gw.example/v1/files/out-1/content",
            operation="Result file download",
            headers={"Authorization": "Bearer secret"},
        ):
            raise aiohttp.ClientPayloadError("mid-stream payload failure")

    assert exc_info.value.response_data == {
        "error_type": "ClientPayloadError",
        "timeout_seconds": client.request_timeout_seconds,
    }
    assert len(session.calls) == 1
    assert sleeps == []
    assert first_response.enter_count == 1
    assert first_response.exit_count == 1
    assert second_response.enter_count == 0
    assert second_response.exit_count == 0
