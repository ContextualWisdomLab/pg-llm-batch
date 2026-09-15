# SPDX-License-Identifier: Apache-2.0
"""Privacy regressions for ordinary Batch API client logging."""

from __future__ import annotations

import json
import logging

from pg_llm_batch import batch_api_client as client_mod
from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials


class _FakeContent:
    """Expose deterministic response bytes through a bounded stream."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def iter_chunked(self, size: int):
        """Yield the payload in chunks no larger than ``size``."""
        for index in range(0, len(self._payload), size):
            yield self._payload[index : index + size]


class _FakeResponse:
    """Provide one bounded JSON response to the client."""

    def __init__(self, status: int, payload: dict[str, object]) -> None:
        encoded = json.dumps(payload).encode("utf-8")
        self.status = status
        self.content_length = len(encoded)
        self.content = _FakeContent(encoded)

    async def __aenter__(self):
        """Enter the asynchronous response context."""
        return self

    async def __aexit__(self, *_exc):
        """Leave the asynchronous response context."""
        return None


class _FakeSession:
    """Route provider POST operations to deterministic responses."""

    def __init__(self, file_id: str, batch_id: str) -> None:
        self._file_response = _FakeResponse(200, {"id": file_id})
        self._batch_response = _FakeResponse(
            201, {"id": batch_id, "status": "validating"}
        )

    def post(self, url: str, **_kwargs):
        """Return the response matching one Files or Batches endpoint."""
        if url.endswith("/files"):
            return self._file_response
        if url.endswith("/batches"):
            return self._batch_response
        raise AssertionError(f"unexpected POST URL: {url}")


def _credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic HTTPS credentials for the focused regression."""
    return GatewayCredentials(url="https://gw.example/v1", api_key="sk-test")


async def test_success_info_logs_omit_provider_resource_ids(caplog) -> None:
    """Keep provider IDs in API results while excluding them from routine INFO logs."""
    provider_file_id = "provider-file-id-sensitive"
    provider_batch_id = "provider-batch-id-sensitive"
    client = BatchAPIClient("postgresql://x", _credentials)
    client._session = _FakeSession(provider_file_id, provider_batch_id)

    async def _payload(_file_id: str) -> bytes:
        return b'{"custom_id":"r1"}\n'

    client._load_payload_bytes = _payload  # type: ignore[method-assign]

    with caplog.at_level(logging.INFO, logger=client_mod.__name__):
        uploaded = await client.upload_jsonl("memory://local-file", "default")
        created = await client.create_batch_job(provider_file_id, "default")

    assert uploaded["id"] == provider_file_id
    assert created["id"] == provider_batch_id

    messages = [
        record.getMessage()
        for record in caplog.records
        if record.name == client_mod.__name__ and record.levelno == logging.INFO
    ]
    assert messages == ["Uploaded JSONL file", "Created batch job"]
    assert all(provider_file_id not in message for message in messages)
    assert all(provider_batch_id not in message for message in messages)
