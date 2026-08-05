# SPDX-License-Identifier: Apache-2.0
"""Security regressions for durable lifecycle recovery evidence."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.batch_api_client import GatewayCredentials
from pg_llm_batch.durable_client import DurableBatchAPIClient
from pg_llm_batch.exceptions import GatewayError


def credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic credentials for lifecycle redaction tests."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


async def test_invalid_provider_identifier_is_redacted_from_recovery_error() -> None:
    """An unsupported provider ID cannot escape through metadata or exception chains."""
    sentinel = "tenant-private/prompt-bearing-provider-id"
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
        credentials,
        lifecycle_recorder=recorder,
        observation_reserver=lambda _dsn: 1,
    )

    with pytest.raises(GatewayError, match="persistence failed") as exc_info:
        await client._persist_snapshot(
            "primary",
            {"id": sentinel, "status": "validating"},
            1,
            operation="Batch creation",
        )

    assert exc_info.value.response_data == {
        "operation": "Batch creation",
        "phase": "persistence",
        "endpoint_alias": "primary",
        "batch_id": None,
        "observation_order": 1,
        "error_type": "ValidationError",
    }
    assert exc_info.value.__cause__ is None
    assert sentinel not in repr(exc_info.value.response_data)
    assert sentinel not in repr(exc_info.value)
    assert recorded == []
