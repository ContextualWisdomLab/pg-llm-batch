# SPDX-License-Identifier: Apache-2.0
"""Provider file deletion lifecycle regressions."""

from __future__ import annotations

import json

import pytest

from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.exceptions import GatewayError, ValidationError


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
    """Capture the exact provider file deletion request."""

    def __init__(self, response: _Response) -> None:
        self.response = response
        self.calls: list[tuple[str, str, dict[str, object]]] = []

    def delete(self, url: str, **kwargs):
        """Record one DELETE and return the configured response."""
        self.calls.append(("DELETE", url, kwargs))
        return self.response


def _credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic test-only provider credentials."""
    return GatewayCredentials(url="https://gateway.example.test/v1", api_key="secret")


async def test_delete_file_uses_validated_provider_file_authority() -> None:
    """Explicit file deletion must use the existing gateway and resource-id boundary."""
    session = _Session(_Response(200, {"id": "file-input", "deleted": True}))
    client = BatchAPIClient("postgresql://test", _credentials)
    client._session = session

    result = await client.delete_file("file-input", "default")

    assert result == {"id": "file-input", "deleted": True}
    assert session.calls == [
        (
            "DELETE",
            "https://gateway.example.test/v1/files/file-input",
            {"headers": client._headers("secret")},
        )
    ]


@pytest.mark.parametrize("invalid_file_id", ["", "bad/id", "bad id", True, 1, b"file"])
async def test_delete_file_rejects_invalid_identifiers_before_credentials(
    invalid_file_id: object,
) -> None:
    """Malformed file identities must not trigger credential or provider access."""
    credential_calls: list[str] = []

    def credentials(endpoint_alias: str) -> GatewayCredentials:
        credential_calls.append(endpoint_alias)
        return GatewayCredentials(
            url="https://gateway.example.test/v1",
            api_key="must-not-be-resolved",
        )

    client = BatchAPIClient("postgresql://test", credentials)

    with pytest.raises(ValidationError):
        await client.delete_file(invalid_file_id, "default")  # type: ignore[arg-type]

    assert credential_calls == []


async def test_delete_file_requires_provider_confirmed_identity_and_state() -> None:
    """A successful HTTP status is not deletion proof without exact bounded evidence."""
    session = _Session(_Response(200, {"id": "other-file", "deleted": True}))
    client = BatchAPIClient("postgresql://test", _credentials)
    client._session = session

    with pytest.raises(GatewayError, match="File deletion returned invalid evidence"):
        await client.delete_file("file-input", "default")
