# SPDX-License-Identifier: Apache-2.0
"""Regression tests for bounded durable lifecycle failure evidence."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.batch_api_client import GatewayCredentials
from pg_llm_batch.durable_client import (
    DurableBatchAPIClient,
    TenantDurableBatchAPIClient,
)
from pg_llm_batch.exceptions import GatewayError


_SECRET_CLASS_SENTINEL = "SecretLifecycleFailureClass_7f9d"
_SECRET_MESSAGE_SENTINEL = "secret-lifecycle-message-21c4"


def _credentials(_alias: str) -> GatewayCredentials:
    """Return inert credentials; focused tests perform no provider request."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


def _secret_exception() -> Exception:
    """Create an exception whose type and text must never escape recovery evidence."""
    exception_type = type(_SECRET_CLASS_SENTINEL, (RuntimeError,), {})
    return exception_type(_SECRET_MESSAGE_SENTINEL)


def _assert_bounded_failure(
    error: GatewayError,
    *,
    expected_category: str,
    tenant_scope: str | None,
) -> None:
    """Assert exported recovery evidence retains no implementation exception state."""
    assert error.response_data["error_type"] == expected_category
    assert error.__cause__ is None
    assert error.__context__ is None
    rendered = "\n".join(
        (
            str(error),
            repr(error),
            repr(error.response_data),
        )
    )
    assert _SECRET_CLASS_SENTINEL not in rendered
    assert _SECRET_MESSAGE_SENTINEL not in rendered
    if tenant_scope is None:
        assert "tenant_scope" not in error.response_data
    else:
        assert error.response_data["tenant_scope"] == tenant_scope


@pytest.mark.parametrize("tenant_scope", [None, "tenant-a"])
async def test_reservation_failure_uses_fixed_evidence_without_exception_chain(
    tenant_scope: str | None,
) -> None:
    """Reservation failures expose one finite category before provider I/O."""

    def fail_reservation(_dsn: str) -> int:
        raise _secret_exception()

    if tenant_scope is None:
        client: DurableBatchAPIClient = DurableBatchAPIClient(
            "postgresql://test",
            _credentials,
            observation_reserver=fail_reservation,
        )
    else:
        client = TenantDurableBatchAPIClient(
            "postgresql://test",
            _credentials,
            tenant_scope=tenant_scope,
            observation_reserver=fail_reservation,
        )

    with pytest.raises(GatewayError) as exc_info:
        await client._reserve_observation_order(
            "primary",
            operation="Batch status",
            batch_id="batch-1",
        )

    assert exc_info.value.response_data["phase"] == "reservation"
    assert exc_info.value.response_data["endpoint_alias"] == "primary"
    assert exc_info.value.response_data["batch_id"] == "batch-1"
    _assert_bounded_failure(
        exc_info.value,
        expected_category="lifecycle_reservation_failure",
        tenant_scope=tenant_scope,
    )


@pytest.mark.parametrize("tenant_scope", [None, "tenant-a"])
async def test_persistence_failure_uses_fixed_evidence_without_exception_chain(
    tenant_scope: str | None,
) -> None:
    """Persistence failures keep trusted recovery fields but no recorder exception."""

    def fail_persistence(*_args: Any) -> None:
        raise _secret_exception()

    if tenant_scope is None:
        client: DurableBatchAPIClient = DurableBatchAPIClient(
            "postgresql://test",
            _credentials,
            lifecycle_recorder=fail_persistence,
            observation_reserver=lambda _dsn: 7,
        )
    else:
        client = TenantDurableBatchAPIClient(
            "postgresql://test",
            _credentials,
            tenant_scope=tenant_scope,
            tenant_lifecycle_recorder=fail_persistence,
            observation_reserver=lambda _dsn: 7,
        )

    with pytest.raises(GatewayError) as exc_info:
        await client._persist_snapshot(
            "primary",
            {"id": "batch-1", "status": "completed"},
            7,
            operation="Batch status",
            expected_batch_id="batch-1",
        )

    assert exc_info.value.response_data["phase"] == "persistence"
    assert exc_info.value.response_data["endpoint_alias"] == "primary"
    assert exc_info.value.response_data["batch_id"] == "batch-1"
    assert exc_info.value.response_data["observation_order"] == 7
    _assert_bounded_failure(
        exc_info.value,
        expected_category="lifecycle_persistence_failure",
        tenant_scope=tenant_scope,
    )
