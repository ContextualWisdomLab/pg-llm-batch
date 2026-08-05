# SPDX-License-Identifier: Apache-2.0
"""Security tests for provider identifiers embedded in URL paths."""

from __future__ import annotations

import json

import pytest

from pg_llm_batch.batch_api_client import (
    BatchAPIClient,
    GatewayCredentials,
    _validate_resource_id,
)
from pg_llm_batch.exceptions import ValidationError


@pytest.mark.parametrize(
    "value",
    [
        "file-abc123",
        "batch_abc123",
        "11111111-1111-1111-1111-111111111111",
        "provider.region:model-v1",
    ],
)
def test_valid_resource_identifiers_are_preserved(value):
    """Common provider and UUID identifier forms remain byte-for-byte stable."""
    assert _validate_resource_id(value, "resource_id") == value


@pytest.mark.parametrize(
    "value",
    [
        "",
        "../secret",
        "file/path",
        "file?query",
        "file#fragment",
        "file%2Fpath",
        "file value",
        "file\nvalue",
        "파일-1",
        "a" * 257,
        None,
        123,
        True,
    ],
)
def test_invalid_resource_identifiers_are_rejected(value):
    """Path syntax, controls, Unicode, oversize, and non-string IDs fail closed."""
    with pytest.raises(ValidationError, match="resource_id"):
        _validate_resource_id(value, "resource_id")


class Credentials:
    """Record every secret-bearing credential resolution."""

    def __init__(self) -> None:
        self.calls = []

    def __call__(self, alias: str) -> GatewayCredentials:
        self.calls.append(alias)
        return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")



class ResponseContent:
    """Expose deterministic JSON bytes through a bounded stream."""

    def __init__(self, payload: bytes) -> None:
        self.payload = payload

    async def iter_chunked(self, size: int):
        """Yield bytes in chunks no larger than the requested size."""
        for index in range(0, len(self.payload), size):
            yield self.payload[index : index + size]


class Response:
    """Minimal asynchronous JSON response."""

    status = 200

    def __init__(self, payload) -> None:
        self.payload = payload
        encoded = json.dumps(payload).encode("utf-8")
        self.content_length = len(encoded)
        self.content = ResponseContent(encoded)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_exc):
        return None

    async def json(self):
        return self.payload


class Session:
    """Return one status payload and record requested URLs."""

    def __init__(self, payload) -> None:
        self.payload = payload
        self.urls = []

    def get(self, url, **_kwargs):
        self.urls.append(url)
        return Response(self.payload)


async def test_invalid_caller_ids_do_not_resolve_credentials():
    """Caller-controlled invalid IDs are rejected before secret retrieval."""
    credentials = Credentials()
    client = BatchAPIClient("postgresql://x", credentials)

    with pytest.raises(ValidationError, match="batch_id"):
        await client.get_batch_status("../admin", "default")
    with pytest.raises(ValidationError, match="batch_id"):
        await client.cancel_batch("batch?redirect", "default")
    with pytest.raises(ValidationError, match="input_file_id"):
        await client.create_batch_job("file/path", "default")
    with pytest.raises(ValidationError, match="file_id"):
        await client.upload_jsonl("memory://file/path", "default")

    assert credentials.calls == []


async def test_provider_file_ids_are_validated_before_follow_up_credentials():
    """A malicious status payload cannot steer a second authenticated request."""
    credentials = Credentials()
    session = Session(
        {
            "status": "completed",
            "output_file_id": "../internal",
            "request_counts": {},
        }
    )
    client = BatchAPIClient("postgresql://x", credentials)
    client._session = session

    with pytest.raises(ValidationError, match="result_file_id"):
        await client.download_results("batch-safe", "default")

    assert credentials.calls == ["default"]
    assert session.urls == ["https://gateway.example/v1/batches/batch-safe"]
