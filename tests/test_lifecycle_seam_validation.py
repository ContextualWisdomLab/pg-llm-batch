# SPDX-License-Identifier: Apache-2.0
"""Construction-time validation for durable lifecycle callables."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.batch_api_client import GatewayCredentials
from pg_llm_batch.durable_client import (
    DurableBatchAPIClient,
    TenantDurableBatchAPIClient,
)
from pg_llm_batch.exceptions import ValidationError


def _credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic credentials without network or database effects."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


@pytest.mark.parametrize(
    ("option_name", "expected_reason"),
    [
        ("lifecycle_recorder", "must be callable"),
        ("observation_reserver", "must be callable"),
    ],
)
def test_standalone_client_rejects_non_callable_lifecycle_seams(
    option_name: str,
    expected_reason: str,
) -> None:
    """Misconfigured standalone seams fail during construction, before provider I/O."""
    options: dict[str, Any] = {option_name: None}

    with pytest.raises(ValidationError) as exc_info:
        DurableBatchAPIClient(
            "postgresql://tenant-test",
            _credentials,
            **options,
        )

    assert exc_info.value.details == {
        "field": option_name,
        "value": None,
        "reason": expected_reason,
    }


def test_tenant_client_rejects_a_non_callable_tenant_recorder() -> None:
    """A tenant job cannot succeed remotely before discovering an invalid recorder."""
    with pytest.raises(ValidationError) as exc_info:
        TenantDurableBatchAPIClient(
            "postgresql://tenant-test",
            _credentials,
            tenant_scope="tenant-a",
            tenant_lifecycle_recorder=None,  # type: ignore[arg-type]
        )

    assert exc_info.value.details == {
        "field": "tenant_lifecycle_recorder",
        "value": None,
        "reason": "must be callable",
    }
