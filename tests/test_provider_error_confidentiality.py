# SPDX-License-Identifier: Apache-2.0
"""Provider-error confidentiality regressions for the HTTP boundary."""

from __future__ import annotations

import json

import pytest

from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.exceptions import GatewayError

SENSITIVE_PROVIDER_TEXT = "customer-email@example.test secret-provider-diagnostic"
BOUNDED_HTTP_ERROR = {"error_type": "ProviderHTTPError"}


def _credentials(_alias: str) -> GatewayCredentials:
    """Return one deterministic credential pair for HTTP-boundary tests."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


class _Content:
    """Stream one deterministic response body."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def iter_chunked(self, size: int):
        """Yield the response body in bounded chunks."""
        for index in range(0, len(self._payload), size):
            yield self._payload[index : index + size]


class _Response:
    """Minimal asynchronous provider response."""

    def __init__(self, *, status: int, payload: bytes) -> None:
        self.status = status
        self.headers = {}
        self.content_length = len(payload)
        self.content = _Content(payload)

    async def __aenter__(self):
        """Enter the canned response context."""
        return self

    async def __aexit__(self, *_exc):
        """Exit the canned response context."""
        return None


class _Session:
    """Return one canned response for GET and POST requests."""

    def __init__(self, response: _Response) -> None:
        self._response = response
        self.calls: list[tuple[str, str]] = []

    def get(self, url: str, **_kwargs):
        """Return the canned response for a GET."""
        self.calls.append(("GET", url))
        return self._response

    def post(self, url: str, **_kwargs):
        """Return the canned response for a POST."""
        self.calls.append(("POST", url))
        return self._response


def _json_response(status: int = 400) -> _Response:
    """Build one provider error object containing sensitive text."""
    return _Response(
        status=status,
        payload=json.dumps(
            {
                "error": {
                    "message": SENSITIVE_PROVIDER_TEXT,
                    "type": "provider_specific_internal_type",
                },
                "debug": SENSITIVE_PROVIDER_TEXT,
            }
        ).encode("utf-8"),
    )


def _client(response: _Response) -> BatchAPIClient:
    """Build a single-attempt client bound to one canned response."""
    client = BatchAPIClient(
        "postgresql://x",
        _credentials,
        max_retry_attempts=1,
    )
    client._session = _Session(response)
    return client


async def test_batch_status_http_error_does_not_export_provider_payload() -> None:
    """Status failures expose fixed diagnostics rather than provider JSON."""
    client = _client(_json_response(status=400))

    with pytest.raises(GatewayError, match="Batch status failed: 400") as exc_info:
        await client.get_batch_status("batch-1", "default")

    assert exc_info.value.response_data == BOUNDED_HTTP_ERROR
    assert SENSITIVE_PROVIDER_TEXT not in str(exc_info.value.details)


async def test_file_upload_http_error_does_not_export_provider_payload() -> None:
    """Upload failures expose fixed diagnostics rather than provider JSON."""
    client = _client(_json_response(status=400))

    async def _payload(_file_id: str) -> bytes:
        return b"{}\n"

    client._load_payload_bytes = _payload

    with pytest.raises(GatewayError, match="Files API upload failed: 400") as exc_info:
        await client.upload_jsonl("memory://file-1", "default")

    assert exc_info.value.response_data == BOUNDED_HTTP_ERROR
    assert SENSITIVE_PROVIDER_TEXT not in str(exc_info.value.details)


async def test_batch_creation_http_error_does_not_export_provider_payload() -> None:
    """Create failures expose fixed diagnostics rather than provider JSON."""
    client = _client(_json_response(status=400))

    with pytest.raises(GatewayError, match="Batch creation failed: 400") as exc_info:
        await client.create_batch_job("file-1", "default")

    assert exc_info.value.response_data == BOUNDED_HTTP_ERROR
    assert SENSITIVE_PROVIDER_TEXT not in str(exc_info.value.details)


async def test_file_download_http_error_does_not_export_provider_body() -> None:
    """File failures do not copy raw provider response text into exceptions."""
    client = _client(
        _Response(status=400, payload=SENSITIVE_PROVIDER_TEXT.encode("utf-8"))
    )

    with pytest.raises(GatewayError, match="Error file download failed: 400") as exc_info:
        await client._download_jsonl_file(
            "file-1",
            "default",
            batch_id="batch-1",
            file_kind="error",
        )

    assert exc_info.value.response_data == BOUNDED_HTTP_ERROR
    assert SENSITIVE_PROVIDER_TEXT not in str(exc_info.value.details)


async def test_cancellation_rejection_does_not_return_provider_message() -> None:
    """Cancellation failures return a bounded reason without provider text."""
    client = _client(_json_response(status=400))

    result = await client.cancel_batch("batch-1", "default")

    assert result == {
        "success": False,
        "reason": "Batch cancellation rejected by provider",
        "status_code": 400,
    }
    assert SENSITIVE_PROVIDER_TEXT not in str(result)
