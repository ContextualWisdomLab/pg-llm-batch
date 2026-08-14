# SPDX-License-Identifier: Apache-2.0
"""Regressions for observability parity with current provider lifecycle APIs."""

from __future__ import annotations

from typing import Any, Awaitable, Callable

import pytest

from pg_llm_batch.batch_api_client import BatchAPIClient
from pg_llm_batch.observability import OpenTelemetryBatchAPIClient


@pytest.fixture
def observed_client(monkeypatch: pytest.MonkeyPatch):
    """Build an uninitialized client with only the observation wrapper active."""
    observed: list[str] = []

    async def run_observed(
        _self: OpenTelemetryBatchAPIClient,
        operation_name: str,
        operation: Callable[[], Awaitable[Any]],
    ) -> Any:
        observed.append(operation_name)
        return await operation()

    monkeypatch.setattr(OpenTelemetryBatchAPIClient, "_run_observed", run_observed)
    return object.__new__(OpenTelemetryBatchAPIClient), observed


async def test_observed_upload_preserves_input_retention_control(
    observed_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward the base upload expiry option through the instrumented subclass."""
    client, observed = observed_client
    captured: dict[str, Any] = {}

    async def upload_jsonl(
        _self: BatchAPIClient,
        file_path: str,
        endpoint_alias: str,
        purpose: str = "batch",
        expires_after_seconds: int | None = None,
    ) -> dict[str, Any]:
        captured.update(
            file_path=file_path,
            endpoint_alias=endpoint_alias,
            purpose=purpose,
            expires_after_seconds=expires_after_seconds,
        )
        return {"id": "file-1"}

    monkeypatch.setattr(BatchAPIClient, "upload_jsonl", upload_jsonl)

    result = await client.upload_jsonl(
        "memory://input-1",
        "private-alias",
        expires_after_seconds=3600,
    )

    assert result == {"id": "file-1"}
    assert captured["expires_after_seconds"] == 3600
    assert observed == ["upload_jsonl"]


async def test_observed_create_preserves_output_retention_control(
    observed_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Forward the base output expiry option through the instrumented subclass."""
    client, observed = observed_client
    captured: dict[str, Any] = {}

    async def create_batch_job(
        _self: BatchAPIClient,
        input_file_id: str,
        endpoint_alias: str,
        endpoint: str = "/v1/chat/completions",
        metadata: dict[str, Any] | None = None,
        output_expires_after_seconds: int | None = None,
    ) -> dict[str, Any]:
        captured.update(
            input_file_id=input_file_id,
            endpoint_alias=endpoint_alias,
            endpoint=endpoint,
            metadata=metadata,
            output_expires_after_seconds=output_expires_after_seconds,
        )
        return {"id": "batch-1"}

    monkeypatch.setattr(BatchAPIClient, "create_batch_job", create_batch_job)

    result = await client.create_batch_job(
        "file-1",
        "private-alias",
        output_expires_after_seconds=7200,
    )

    assert result == {"id": "batch-1"}
    assert captured["output_expires_after_seconds"] == 7200
    assert observed == ["create_batch_job"]


async def test_provider_file_deletion_remains_observed(
    observed_client,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the newer public delete operation inside the telemetry boundary."""
    client, observed = observed_client

    async def delete_file(
        _self: BatchAPIClient,
        file_id: str,
        endpoint_alias: str,
    ) -> dict[str, Any]:
        assert file_id == "file-1"
        assert endpoint_alias == "private-alias"
        return {"id": file_id, "deleted": True}

    monkeypatch.setattr(BatchAPIClient, "delete_file", delete_file)

    result = await client.delete_file("file-1", "private-alias")

    assert result == {"id": "file-1", "deleted": True}
    assert observed == ["delete_file"]
