# SPDX-License-Identifier: Apache-2.0
"""Provider-side retention policy regressions."""

from __future__ import annotations

import json

import pytest

from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.exceptions import ValidationError


class _Content:
    """Expose one JSON response through the bounded-stream interface."""

    def __init__(self, payload: dict[str, object]) -> None:
        self._encoded = json.dumps(payload).encode("utf-8")

    async def iter_chunked(self, size: int):
        """Yield the encoded response in bounded chunks."""
        for index in range(0, len(self._encoded), size):
            yield self._encoded[index : index + size]


class _Response:
    """Minimal asynchronous provider response double."""

    def __init__(self, status: int, payload: dict[str, object]) -> None:
        self.status = status
        self.content = _Content(payload)
        self.content_length = len(json.dumps(payload).encode("utf-8"))

    async def __aenter__(self):
        """Return this response from the request context."""
        return self

    async def __aexit__(self, *_exc):
        """Close the no-resource response context."""
        return None


class _Session:
    """Capture the exact JSON body sent to batch creation."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, object]]] = []

    def post(self, url: str, **kwargs):
        """Record one POST and return a successful batch response."""
        self.calls.append((url, kwargs))
        return _Response(201, {"id": "batch-retention", "status": "validating"})


def _credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic test-only provider credentials."""
    return GatewayCredentials(url="https://gateway.example.test/v1", api_key="secret")


async def test_batch_creation_serializes_output_file_expiration_policy() -> None:
    """A caller-selected output lifetime must reach the provider explicitly."""
    session = _Session()
    client = BatchAPIClient("postgresql://test", _credentials)
    client._session = session

    result = await client.create_batch_job(
        "file-input",
        "default",
        output_expires_after_seconds=3600,
    )

    assert result["id"] == "batch-retention"
    assert session.calls[0][1]["json"]["output_expires_after"] == {
        "anchor": "created_at",
        "seconds": 3600,
    }


async def test_batch_creation_serializes_maximum_output_file_lifetime() -> None:
    """The documented 30-day provider maximum must remain accepted."""
    session = _Session()
    client = BatchAPIClient("postgresql://test", _credentials)
    client._session = session

    await client.create_batch_job(
        "file-input",
        "default",
        output_expires_after_seconds=2_592_000,
    )

    assert session.calls[0][1]["json"]["output_expires_after"] == {
        "anchor": "created_at",
        "seconds": 2_592_000,
    }


@pytest.mark.parametrize(
    "invalid_lifetime",
    [True, False, 3599, 2_592_001, 3600.0, "3600"],
)
async def test_output_file_lifetime_rejects_invalid_values_before_credentials(
    invalid_lifetime: object,
) -> None:
    """Invalid retention values must fail locally before credential/provider I/O."""
    credential_calls: list[str] = []

    def credentials(endpoint_alias: str) -> GatewayCredentials:
        credential_calls.append(endpoint_alias)
        return GatewayCredentials(
            url="https://gateway.example.test/v1",
            api_key="must-not-be-resolved",
        )

    client = BatchAPIClient("postgresql://test", credentials)

    with pytest.raises(ValidationError) as caught:
        await client.create_batch_job(
            "file-input",
            "default",
            output_expires_after_seconds=invalid_lifetime,  # type: ignore[arg-type]
        )

    assert caught.value.field == "output_expires_after_seconds"
    assert credential_calls == []


async def test_batch_creation_omits_output_expiry_when_not_requested() -> None:
    """Provider-neutral callers must preserve the historical payload by default."""
    session = _Session()
    client = BatchAPIClient("postgresql://test", _credentials)
    client._session = session

    await client.create_batch_job("file-input", "default")

    assert "output_expires_after" not in session.calls[0][1]["json"]
