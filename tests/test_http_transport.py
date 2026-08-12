# SPDX-License-Identifier: Apache-2.0
"""HTTP transport boundary tests for the Batch API client."""

from __future__ import annotations

import asyncio
import json

import aiohttp
import pytest

from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.exceptions import GatewayError, ValidationError


def _credentials(_alias: str) -> GatewayCredentials:
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")



class ResponseContent:
    """Expose deterministic response bytes through a bounded stream."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    async def iter_chunked(self, size: int):
        """Yield bytes in chunks no larger than the requested size."""
        for index in range(0, len(self.payload), size):
            yield self.payload[index : index + size]


class Response:
    """Minimal asynchronous response used by transport boundary tests."""

    def __init__(self, payload, *, status: int = 200) -> None:
        self.payload = payload
        self.status = status
        encoded = (
            b"{"
            if isinstance(payload, json.JSONDecodeError)
            else json.dumps(payload).encode("utf-8")
        )
        self.content_length = len(encoded)
        self.content = ResponseContent(encoded)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def json(self):
        if isinstance(self.payload, BaseException):
            raise self.payload
        return self.payload


class RecordingSession:
    """Record request policy while returning one canned response."""

    def __init__(self, response: Response) -> None:
        self.response = response
        self.calls = []

    def get(self, url, **kwargs):
        self.calls.append(("GET", url, kwargs))
        return self.response


@pytest.mark.parametrize(
    "value",
    [0, -1, float("inf"), float("nan"), True, "invalid", None],
)
def test_request_timeout_requires_a_positive_finite_number(value):
    """Disabled, nonsensical, and unbounded timeouts fail closed."""
    with pytest.raises(ValidationError, match="request_timeout_seconds"):
        BatchAPIClient(
            "postgresql://x",
            _credentials,
            request_timeout_seconds=value,
        )


async def test_requests_are_bounded_and_redirects_are_disabled():
    """Every gateway request carries the configured total timeout policy."""
    session = RecordingSession(
        Response({"status": "completed", "request_counts": {}})
    )
    client = BatchAPIClient(
        "postgresql://x",
        _credentials,
        request_timeout_seconds=12.5,
    )
    client._session = session

    status = await client.get_batch_status("batch-1", "default")

    assert status["is_complete"] is True
    method, url, kwargs = session.calls[0]
    assert method == "GET"
    assert url.endswith("/batches/batch-1")
    assert kwargs["timeout"].total == 12.5
    assert kwargs["allow_redirects"] is False


@pytest.mark.parametrize(
    ("error", "expected_error_type"),
    [
        (aiohttp.ClientConnectionError("offline"), "ClientError"),
        (asyncio.TimeoutError(), "TimeoutError"),
    ],
)
async def test_transport_errors_are_converted_to_structured_gateway_errors(
    error, expected_error_type
):
    """Network and request timeout failures never leak aiohttp exceptions."""

    class FailingSession:
        def get(self, _url, **_kwargs):
            raise error

    client = BatchAPIClient(
        "postgresql://x",
        _credentials,
        request_timeout_seconds=7,
        max_retry_attempts=1,
    )
    client._session = FailingSession()

    with pytest.raises(GatewayError, match="Batch status transport failed") as exc_info:
        await client.get_batch_status("batch-1", "default")

    assert exc_info.value.response_data == {
        "error_type": expected_error_type,
        "timeout_seconds": 7.0,
    }


@pytest.mark.parametrize(
    ("payload", "message", "details"),
    [
        (
            json.JSONDecodeError("invalid", "{", 0),
            "invalid JSON",
            {"error_type": "JSONDecodeError"},
        ),
        (["not", "an", "object"], "non-object JSON", {"response_type": "list"}),
    ],
)
async def test_invalid_gateway_payload_shapes_raise_typed_errors(
    payload, message, details
):
    """Malformed or non-object provider responses fail at the HTTP boundary."""
    client = BatchAPIClient("postgresql://x", _credentials)
    client._session = RecordingSession(Response(payload))

    with pytest.raises(GatewayError, match=message) as exc_info:
        await client.get_batch_status("batch-1", "default")

    assert exc_info.value.status_code == 200
    assert exc_info.value.response_data == details
