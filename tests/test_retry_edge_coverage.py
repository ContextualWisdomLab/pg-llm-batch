# SPDX-License-Identifier: Apache-2.0
"""Coverage tests for bounded idempotent retry edge paths."""

from __future__ import annotations

from typing import Any

import aiohttp
import pytest

from pg_llm_batch import batch_api_client as client_mod
from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.exceptions import GatewayError
from tests.test_idempotent_get_retries import Response, SequenceSession


def credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic provider credentials for retry edge tests."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


async def test_retryable_response_without_header_mapping_uses_fallback(
    monkeypatch: Any,
) -> None:
    """A response lacking ``headers.get`` still uses bounded fallback jitter."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(client_mod.random, "uniform", lambda _low, high: high)
    transient = Response(503, {"error": "busy"})
    transient.headers = object()
    session = SequenceSession(
        [
            transient,
            Response(200, {"status": "completed", "request_counts": {}}),
        ]
    )
    client = BatchAPIClient("postgresql://x", credentials)
    client._session = session

    result = await client.get_batch_status("batch-1", "default")

    assert result["status"] == "completed"
    assert sleeps == [0.5]
    assert len(session.calls) == 2


async def test_excessive_retry_after_passes_response_without_sleeping(
    monkeypatch: Any,
) -> None:
    """Excessive guidance yields the response without retry-loop delay or replay."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    response = Response(
        429,
        {"error": "rate-limited"},
        headers={"Retry-After": "31"},
    )
    session = SequenceSession([response])
    client = BatchAPIClient(
        "postgresql://x",
        credentials,
        retry_max_delay_seconds=30,
    )
    client._session = session

    async with client._request(
        "get",
        "https://gateway.example/v1/batches/batch-1",
        operation="Batch status",
    ) as returned:
        assert returned is response

    assert response.exit_count == 1
    assert sleeps == []
    assert len(session.calls) == 1


async def test_persistent_get_transport_failure_raises_after_retry_budget(
    monkeypatch: Any,
) -> None:
    """The final GET transport failure preserves the structured error contract."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(client_mod.random, "uniform", lambda _low, high: high)
    session = SequenceSession(
        [
            aiohttp.ClientConnectionError("offline-1"),
            aiohttp.ClientConnectionError("offline-2"),
            aiohttp.ClientConnectionError("offline-3"),
        ]
    )
    client = BatchAPIClient(
        "postgresql://x",
        credentials,
        request_timeout_seconds=9,
        max_retry_attempts=3,
    )
    client._session = session

    with pytest.raises(GatewayError, match="Batch status transport failed") as exc_info:
        await client.get_batch_status("batch-1", "default")

    assert exc_info.value.response_data == {
        "error_type": "ClientConnectionError",
        "timeout_seconds": 9.0,
    }
    assert sleeps == [0.5, 1.0]
    assert len(session.calls) == 3
