# SPDX-License-Identifier: Apache-2.0
"""Regression tests for package-owned Batch API HTTP session lifecycle."""

from __future__ import annotations

import asyncio
import json

import pytest

from pg_llm_batch import batch_api_client as client_mod
from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials


class _Content:
    """Expose one JSON payload through the bounded response-stream contract."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    async def iter_chunked(self, size: int):
        """Yield response bytes in chunks no larger than ``size``."""
        for offset in range(0, len(self.payload), size):
            yield self.payload[offset : offset + size]


class _Response:
    """Provide one successful batch-status response."""

    status = 200

    def __init__(self) -> None:
        payload = json.dumps(
            {
                "id": "batch-1",
                "status": "completed",
                "request_counts": {"total": 1, "completed": 1, "failed": 0},
            }
        ).encode("utf-8")
        self.content_length = len(payload)
        self.content = _Content(payload)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None


class _Session:
    """Record deterministic package-owned session cleanup."""

    def __init__(self) -> None:
        self.close_calls = 0

    def get(self, _url: str, **_kwargs):
        return _Response()

    async def close(self) -> None:
        self.close_calls += 1


class _SuspendingSession(_Session):
    """Suspend close so concurrent cleanup can cross the ownership boundary."""

    def __init__(self) -> None:
        super().__init__()
        self.close_started = asyncio.Event()
        self.release_close = asyncio.Event()

    async def close(self) -> None:
        self.close_calls += 1
        self.close_started.set()
        await self.release_close.wait()


def _credentials(_endpoint_alias: str) -> GatewayCredentials:
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


@pytest.mark.asyncio
async def test_public_aclose_releases_lazily_created_session(monkeypatch) -> None:
    """Allow direct API users to deterministically release package-owned HTTP I/O."""
    session = _Session()
    monkeypatch.setattr(client_mod.aiohttp, "ClientSession", lambda: session)
    client = BatchAPIClient("postgresql://database", _credentials)

    result = await client.get_batch_status("batch-1", "default")
    assert result["status"] == "completed"

    await client.aclose()
    await client.aclose()

    assert session.close_calls == 1
    assert client._session is None


@pytest.mark.asyncio
async def test_concurrent_aclose_claims_owned_session_once() -> None:
    """Concurrent cleanup must never invoke close twice on one owned session."""
    session = _SuspendingSession()
    client = BatchAPIClient("postgresql://database", _credentials)
    client._session = session

    first_cleanup = asyncio.create_task(client.aclose())
    await session.close_started.wait()
    second_cleanup = asyncio.create_task(client.aclose())
    await asyncio.sleep(0)
    session.release_close.set()
    await asyncio.gather(first_cleanup, second_cleanup)

    assert session.close_calls == 1
    assert client._session is None
