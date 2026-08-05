# SPDX-License-Identifier: Apache-2.0
"""Tests for the required-scope tenant durable Batch API client."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.durable_client import (
    DurableBatchAPIClient,
    TenantDurableBatchAPIClient,
)
from pg_llm_batch.exceptions import GatewayError, ValidationError


def _credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic provider credentials for inherited client paths."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


def test_tenant_client_requires_a_valid_scope_at_construction() -> None:
    """Invalid tenant context fails before reservation, credentials, or provider I/O."""
    calls: list[str] = []

    def credentials(_alias: str) -> GatewayCredentials:
        calls.append("credentials")
        raise AssertionError("credentials must not be resolved")

    def reserver(_dsn: str) -> int:
        calls.append("reservation")
        raise AssertionError("observation order must not be reserved")

    with pytest.raises(ValidationError) as exc_info:
        TenantDurableBatchAPIClient(
            "postgresql://tenant-test",
            credentials,
            tenant_scope=" tenant-a",
            observation_reserver=reserver,
        )

    assert exc_info.value.details["field"] == "tenant_scope"
    assert calls == []


def test_tenant_scope_is_exposed_as_exact_read_only_identity() -> None:
    """The tenant client preserves the host-authorized scope without coercion."""
    client = TenantDurableBatchAPIClient(
        "postgresql://tenant-test",
        _credentials,
        tenant_scope="Tenant_01",
    )

    assert client.tenant_scope == "Tenant_01"
    with pytest.raises(AttributeError):
        client.tenant_scope = "tenant-other"  # type: ignore[misc]


async def test_tenant_client_propagates_scope_for_batch_creation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful creation records one ordered snapshot under the trusted tenant."""
    recorded: list[tuple[Any, ...]] = []

    async def fake_create(
        _self: BatchAPIClient,
        input_file_id: str,
        endpoint_alias: str,
        endpoint: str = "/v1/chat/completions",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        assert input_file_id == "file-input"
        assert endpoint_alias == "primary"
        return {"id": "batch-1", "status": "validating"}

    monkeypatch.setattr(BatchAPIClient, "create_batch_job", fake_create)
    client = TenantDurableBatchAPIClient(
        "postgresql://tenant-test",
        _credentials,
        tenant_scope="tenant-a",
        observation_reserver=lambda _dsn: 17,
        tenant_lifecycle_recorder=lambda *args: recorded.append(args),
    )

    result = await client.create_batch_job(
        "file-input",
        "primary",
        endpoint="/v1/responses",
        metadata={"job_name": "nightly"},
    )

    assert result["id"] == "batch-1"
    assert recorded == [
        (
            "postgresql://tenant-test",
            "tenant-a",
            "primary",
            {
                "id": "batch-1",
                "status": "validating",
                "input_file_id": "file-input",
                "endpoint": "/v1/responses",
                "output_file_id": None,
                "error_file_id": None,
                "metadata": {"job_name": "nightly"},
            },
            17,
        )
    ]


async def test_tenant_client_propagates_scope_for_status_and_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Poll and accepted cancellation retain the same tenant recorder boundary."""
    recorded: list[tuple[Any, ...]] = []
    orders = iter([21, 22])

    async def fake_status(
        _self: BatchAPIClient,
        batch_id: str,
        endpoint_alias: str,
    ) -> dict[str, Any]:
        assert (batch_id, endpoint_alias) == ("batch-1", "primary")
        return {
            "id": "batch-1",
            "status": "in_progress",
            "request_counts": {"total": 2, "completed": 1, "failed": 0},
        }

    async def fake_cancel(
        _self: BatchAPIClient,
        batch_id: str,
        endpoint_alias: str,
    ) -> dict[str, Any]:
        assert (batch_id, endpoint_alias) == ("batch-1", "primary")
        return {"success": True, "batch_id": "batch-1", "status": "cancelling"}

    monkeypatch.setattr(BatchAPIClient, "get_batch_status", fake_status)
    monkeypatch.setattr(BatchAPIClient, "cancel_batch", fake_cancel)
    client = TenantDurableBatchAPIClient(
        "postgresql://tenant-test",
        _credentials,
        tenant_scope="tenant-a",
        observation_reserver=lambda _dsn: next(orders),
        tenant_lifecycle_recorder=lambda *args: recorded.append(args),
    )

    await client.get_batch_status("batch-1", "primary")
    await client.cancel_batch("batch-1", "primary")

    assert [call[1] for call in recorded] == ["tenant-a", "tenant-a"]
    assert [call[4] for call in recorded] == [21, 22]
    assert recorded[0][3]["status"] == "in_progress"
    assert recorded[1][3] == {
        "id": "batch-1",
        "status": "cancelling",
        "input_file_id": None,
        "output_file_id": None,
        "error_file_id": None,
        "endpoint": None,
    }


async def test_existing_durable_client_keeps_four_argument_recorder_seam(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Tenant support does not silently change existing embedded recorders."""
    recorded: list[tuple[Any, ...]] = []

    async def fake_create(
        _self: BatchAPIClient,
        _input_file_id: str,
        _endpoint_alias: str,
        endpoint: str = "/v1/chat/completions",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return {"id": "batch-legacy", "status": "validating"}

    monkeypatch.setattr(BatchAPIClient, "create_batch_job", fake_create)
    client = DurableBatchAPIClient(
        "postgresql://tenant-test",
        _credentials,
        observation_reserver=lambda _dsn: 31,
        lifecycle_recorder=lambda *args: recorded.append(args),
    )

    await client.create_batch_job("file-input", "primary")

    assert len(recorded) == 1
    assert len(recorded[0]) == 4
    assert recorded[0][0] == "postgresql://tenant-test"
    assert recorded[0][1] == "primary"
    assert recorded[0][3] == 31


async def test_tenant_reservation_failure_includes_only_trusted_scope_context() -> None:
    """Reservation recovery evidence includes tenant scope without provider data."""
    client = TenantDurableBatchAPIClient(
        "postgresql://tenant-test",
        _credentials,
        tenant_scope="tenant-a",
        observation_reserver=lambda _dsn: (_ for _ in ()).throw(RuntimeError("db")),
    )

    with pytest.raises(GatewayError) as exc_info:
        await client.get_batch_status("batch-1", "primary")

    assert exc_info.value.response_data == {
        "operation": "Batch status",
        "phase": "reservation",
        "endpoint_alias": "primary",
        "batch_id": "batch-1",
        "error_type": "RuntimeError",
        "tenant_scope": "tenant-a",
    }


async def test_tenant_persistence_failure_exposes_no_provider_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Persistence recovery includes trusted scope but no provider metadata or body."""

    async def fake_status(
        _self: BatchAPIClient,
        _batch_id: str,
        _endpoint_alias: str,
    ) -> dict[str, Any]:
        return {
            "id": "batch-1",
            "status": "completed",
            "metadata": {"secret_note": "must-not-leak"},
        }

    def fail_recorder(*_args: Any) -> None:
        raise RuntimeError("persistence unavailable")

    monkeypatch.setattr(BatchAPIClient, "get_batch_status", fake_status)
    client = TenantDurableBatchAPIClient(
        "postgresql://tenant-test",
        _credentials,
        tenant_scope="tenant-a",
        observation_reserver=lambda _dsn: 41,
        tenant_lifecycle_recorder=fail_recorder,
    )

    with pytest.raises(GatewayError) as exc_info:
        await client.get_batch_status("batch-1", "primary")

    assert exc_info.value.response_data == {
        "operation": "Batch status",
        "phase": "persistence",
        "endpoint_alias": "primary",
        "batch_id": "batch-1",
        "observation_order": 41,
        "error_type": "RuntimeError",
        "tenant_scope": "tenant-a",
    }
    assert "must-not-leak" not in str(exc_info.value)
    assert "must-not-leak" not in repr(exc_info.value.response_data)
