# SPDX-License-Identifier: Apache-2.0
"""Regression tests for package-owned Batch API HTTP session lifecycle."""

from __future__ import annotations

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

    assert session.close_calls == 1
    assert client._session is None
