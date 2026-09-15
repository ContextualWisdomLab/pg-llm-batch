# SPDX-License-Identifier: Apache-2.0
"""Authority regressions for provider resource identifiers used in Batch API I/O."""

from __future__ import annotations

import pytest

from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.exceptions import ValidationError


class _BehaviorBearingResourceId(str):
    """Expose formatting behavior that must never survive resource-id admission."""

    def __format__(self, format_spec: str) -> str:
        """Fail if authenticated URL construction reaches caller-defined behavior."""
        raise AssertionError("resource-id formatting behavior must not execute")


async def test_batch_status_rejects_string_subclass_before_credentials() -> None:
    """Reject behavior-bearing batch identifiers before credential or URL authority."""
    credential_calls: list[str] = []

    def _credentials(alias: str) -> GatewayCredentials:
        credential_calls.append(alias)
        return GatewayCredentials(url="https://gateway.example.test/v1", api_key="test-key")

    client = BatchAPIClient("postgresql://test", _credentials)
    hostile_batch_id = _BehaviorBearingResourceId("batch-1")

    with pytest.raises(ValidationError) as raised:
        await client.get_batch_status(hostile_batch_id, "default")

    assert raised.value.details["value"] == "<redacted>"
    assert credential_calls == []
