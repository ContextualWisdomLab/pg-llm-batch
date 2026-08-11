# SPDX-License-Identifier: Apache-2.0
"""Regression tests for the request-context response handoff boundary."""

from __future__ import annotations

import asyncio
from typing import Any

import aiohttp
import pytest

from pg_llm_batch import batch_api_client as client_mod
from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials


class _Response:
    """Minimal successful asynchronous response context."""

    status = 200
    headers: dict[str, str] = {}

    async def __aenter__(self) -> "_Response":
        """Return this response when request acquisition succeeds."""
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        """Release the response without suppressing consumer failures."""


class _Session:
    """Return successful responses while recording request attempts."""

    def __init__(self) -> None:
        self.calls = 0

    def get(self, _url: str, **_kwargs: Any) -> _Response:
        """Return one successful response context per attempt."""
        self.calls += 1
        return _Response()


def _credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic credentials without external access."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


@pytest.mark.parametrize(
    "consumer_error",
    [
        aiohttp.ClientPayloadError("response-body-read-failed"),
        asyncio.TimeoutError("response-body-read-timed-out"),
    ],
)
async def test_transport_errors_after_response_handoff_are_not_retried(
    monkeypatch: pytest.MonkeyPatch,
    consumer_error: BaseException,
) -> None:
    """Once a response is handed off, consumer errors cannot replay the request."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    session = _Session()
    client = BatchAPIClient("postgresql://example", _credentials)
    client._session = session

    with pytest.raises(type(consumer_error), match="response-body-read"):
        async with client._request(
            "get",
            "https://gateway.example/v1/batches/batch-1",
            operation="Batch status",
        ):
            raise consumer_error

    assert session.calls == 1
    assert sleeps == []
