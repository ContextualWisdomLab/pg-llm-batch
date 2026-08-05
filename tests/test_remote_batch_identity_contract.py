# SPDX-License-Identifier: Apache-2.0
"""Security regressions for remote batch identity reconciliation."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.batch_api_client import GatewayCredentials
from pg_llm_batch.durable_client import DurableBatchAPIClient
from pg_llm_batch.exceptions import GatewayError


class _Response:
    """Expose one successful provider response through the aiohttp contract."""

    status = 200
    headers: dict[str, str] = {}

    async def json(self) -> dict[str, Any]:
        """Return a syntactically valid but identity-mismatched provider payload."""
        return {
            "id": "batch-other",
            "status": "in_progress",
            "request_counts": {"total": 2, "completed": 1, "failed": 0},
        }

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

    client = DurableBatchAPIClient(
        "postgresql://example",
        _credentials,
        lifecycle_recorder=recorder,
        observation_reserver=lambda _dsn: 106,
    )
    client._session = _Session()

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
