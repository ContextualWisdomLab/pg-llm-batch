# SPDX-License-Identifier: Apache-2.0
"""Security regressions for remote batch identity reconciliation."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import pytest

from pg_llm_batch import durable_client as durable_client_module
from pg_llm_batch.batch_api_client import GatewayCredentials
from pg_llm_batch.durable_client import DurableBatchAPIClient
from pg_llm_batch.exceptions import GatewayError


class _ByteStream:
    """Expose deterministic JSON bytes through aiohttp's bounded stream seam."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    async def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
        """Yield the encoded body in chunks no larger than the requested size."""
        for offset in range(0, len(self.body), size):
            yield self.body[offset : offset + size]


class _Response:
    """Expose one successful provider response through the aiohttp contract."""

    status = 200
    headers: dict[str, str] = {}

    def __init__(self) -> None:
        payload = {
            "id": "batch-other",
            "status": "in_progress",
            "request_counts": {"total": 2, "completed": 1, "failed": 0},
        }
        self.content = _ByteStream(payload)
        self.content_length = len(self.content.body)

    async def json(self) -> dict[str, Any]:
        """Reject whole-body convenience reads outside the bounded stream."""
        raise AssertionError("response.json() must not bypass bounded streaming")

    async def __aenter__(self) -> "_Response":
        """Enter the response context."""
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        """Leave the response context without suppressing failures."""
        return None


class _Session:
    """Return the mismatched response for the requested remote batch URL."""

    def get(self, _url: str, **_kwargs: Any) -> _Response:
        """Return one deterministic provider response."""
        return _Response()


def _credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic credentials for the provider request."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


def _client(*, recorder: Any = None) -> DurableBatchAPIClient:
    """Build a deterministic durable client for mismatch regressions."""
    client = DurableBatchAPIClient(
        "postgresql://example",
        _credentials,
        lifecycle_recorder=recorder or (lambda *_args: None),
        observation_reserver=lambda _dsn: 106,
    )
    client._session = _Session()
    return client


async def test_poll_rejects_mismatched_provider_batch_identity() -> None:
    """A poll response cannot be persisted under a different batch identity."""
    recorded: list[dict[str, Any]] = []

    def recorder(
        _dsn: str,
        _alias: str,
        provider_batch: Any,
        _observation_order: int,
    ) -> None:
        recorded.append(dict(provider_batch))

    client = _client(recorder=recorder)

    with pytest.raises(GatewayError, match="lifecycle persistence failed") as exc_info:
        await client.get_batch_status("batch-requested", "primary")

    assert exc_info.value.response_data == {
        "operation": "Batch status",
        "phase": "persistence",
        "endpoint_alias": "primary",
        "batch_id": "batch-requested",
        "observation_order": 106,
        "error_type": "ValidationError",
    }
    assert exc_info.value.__cause__ is None
    assert "batch-other" not in repr(exc_info.value)
    assert "batch-other" not in repr(exc_info.value.response_data)
    assert recorded == []


async def test_mismatch_validation_uses_bounded_structured_diagnostics(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Mismatch diagnostics keep a stable message without storing provider data."""
    real_validation_error = durable_client_module.ValidationError
    calls: list[tuple[tuple[Any, ...], dict[str, Any]]] = []

    class CapturingValidationError(real_validation_error):
        """Capture constructor arguments while preserving exception semantics."""

        def __init__(self, *args: Any, **kwargs: Any) -> None:
            calls.append((args, kwargs))
            super().__init__(*args, **kwargs)

    monkeypatch.setattr(
        durable_client_module,
        "ValidationError",
        CapturingValidationError,
    )
    client = _client()

    with pytest.raises(GatewayError, match="lifecycle persistence failed"):
        await client.get_batch_status("batch-requested", "primary")

    assert calls == [
        (
            (),
            {
                "field": "remote_batch_id",
                "value": "<redacted>",
                "reason": "does not match requested batch id",
                "message": "provider batch id does not match requested batch id",
            },
        )
    ]
