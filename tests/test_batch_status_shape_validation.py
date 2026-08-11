# SPDX-License-Identifier: Apache-2.0
"""Fail-closed provider batch-status shape contracts."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.exceptions import GatewayError


class _ChunkStream:
    """Expose one bounded byte chunk through the aiohttp-like stream seam."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def iter_chunked(self, _size: int):
        """Yield the configured payload exactly once."""
        yield self._payload


class _Response:
    """Minimal successful response carrying one JSON object payload."""

    status = 200
    headers: dict[str, str] = {}
    content_length = None

    def __init__(self, payload: dict[str, Any]) -> None:
        import json

        self.content = _ChunkStream(json.dumps(payload).encode("utf-8"))

    async def __aenter__(self) -> "_Response":
        """Return this response from the asynchronous request context."""
        return self

    async def __aexit__(self, *_args: Any) -> None:
        """Close the response context without side effects."""
        return None


class _Session:
    """Return one predetermined response for the status GET."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self._payload = payload

    def get(self, *_args: Any, **_kwargs: Any) -> _Response:
        """Return a successful response containing the configured JSON object."""
        return _Response(self._payload)


def _client(payload: dict[str, Any]) -> BatchAPIClient:
    """Build a client whose status request returns ``payload``."""
    client = BatchAPIClient(
        "postgresql://x",
        lambda _alias: GatewayCredentials("https://provider.example", "secret"),
    )
    client._session = _Session(payload)  # type: ignore[assignment]
    return client


@pytest.mark.parametrize("request_counts", [[], "counts", 1, True])
async def test_batch_status_rejects_non_object_request_counts(
    request_counts: Any,
) -> None:
    """Provider request-count evidence must be an object when present."""
    client = _client({"status": "in_progress", "request_counts": request_counts})

    with pytest.raises(GatewayError, match="invalid request_counts") as exc_info:
        await client.get_batch_status("batch-1", "default")

    assert exc_info.value.response_data == {
        "error_type": "InvalidBatchStatusPayload",
        "field": "request_counts",
    }


@pytest.mark.parametrize(
    "request_counts",
    [
        {"total": True, "completed": 0, "failed": 0},
        {"total": "1", "completed": 0, "failed": 0},
        {"total": -1, "completed": 0, "failed": 0},
        {"total": 1, "completed": 2, "failed": 0},
        {"total": 1, "completed": 1, "failed": 1},
    ],
)
async def test_batch_status_rejects_invalid_request_count_values(
    request_counts: dict[str, Any],
) -> None:
    """Request counts must be non-negative integers consistent with total."""
    client = _client({"status": "in_progress", "request_counts": request_counts})

    with pytest.raises(GatewayError, match="invalid request_counts") as exc_info:
        await client.get_batch_status("batch-1", "default")

    assert exc_info.value.response_data == {
        "error_type": "InvalidBatchStatusPayload",
        "field": "request_counts",
    }


@pytest.mark.parametrize("status", [[], {}, True, 7, None, ""])
async def test_batch_status_rejects_non_string_or_empty_status(status: Any) -> None:
    """Provider status evidence must be a non-empty string before classification."""
    client = _client(
        {
            "status": status,
            "request_counts": {"total": 0, "completed": 0, "failed": 0},
        }
    )

    with pytest.raises(GatewayError, match="invalid status") as exc_info:
        await client.get_batch_status("batch-1", "default")

    assert exc_info.value.response_data == {
        "error_type": "InvalidBatchStatusPayload",
        "field": "status",
    }
