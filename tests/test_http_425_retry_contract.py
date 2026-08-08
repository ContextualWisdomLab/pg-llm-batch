# SPDX-License-Identifier: Apache-2.0
"""Regression tests for the HTTP 425 Too Early retry contract."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch import batch_api_client as client_mod
from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.exceptions import GatewayError


class _Response:
    """Minimal asynchronous response that records deterministic cleanup."""

    def __init__(self, status: int) -> None:
        self.status = status
        self.headers: dict[str, str] = {}
        self.exit_count = 0

    async def __aenter__(self) -> "_Response":
        """Return this response when a request context is entered."""
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        """Record that the response context released its resources."""
        self.exit_count += 1


class _SequenceSession:
    """Return one response per GET call while recording request count."""

    def __init__(self, responses: list[_Response]) -> None:
        self.responses = list(responses)
        self.calls = 0

    def get(self, _url: str, **_kwargs: Any) -> _Response:
        """Return the next configured GET response."""
        self.calls += 1
        if not self.responses:
            raise AssertionError("no response left for GET")
        return self.responses.pop(0)


def _credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic credentials without touching external services."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


async def test_too_early_get_is_released_and_retried_once(monkeypatch: pytest.MonkeyPatch) -> None:
    """HTTP 425 retries one safe GET after releasing the first response."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    monkeypatch.setattr(client_mod.random, "uniform", lambda _low, high: high)
    first = _Response(425)
    session = _SequenceSession([first, _Response(200)])
    client = BatchAPIClient("postgresql://example", _credentials)
    client._session = session

    async with client._request(
        "get",
        "https://gateway.example/v1/batches/batch-1",
        operation="Batch status",
    ) as response:
        assert response.status == 200

    assert first.exit_count == 1
    assert session.calls == 2
    assert sleeps == [0.5]


async def test_internal_server_error_remains_outside_closed_retry_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """HTTP 500 remains single-attempt because it is not inherently temporary."""
    sleeps: list[float] = []

    async def record_sleep(delay: float) -> None:
        sleeps.append(delay)

    monkeypatch.setattr(client_mod.asyncio, "sleep", record_sleep)
    first = _Response(500)
    session = _SequenceSession([first, _Response(200)])
    client = BatchAPIClient("postgresql://example", _credentials)
    client._session = session

    async with client._request(
        "get",
        "https://gateway.example/v1/batches/batch-1",
        operation="Batch status",
    ) as response:
        assert response.status == 500

    assert first.exit_count == 1
    assert session.calls == 1
    assert sleeps == []


def test_retryable_get_status_set_is_closed_and_reviewable() -> None:
    """The default HTTP retry set exactly matches the reviewed safe contract."""
    assert client_mod.RETRYABLE_GET_STATUSES == frozenset({408, 425, 429, 502, 503, 504})
