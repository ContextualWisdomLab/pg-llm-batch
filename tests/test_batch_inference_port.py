# SPDX-License-Identifier: Apache-2.0
"""Provider-neutral lifecycle contract tests for BatchInferencePort."""

from __future__ import annotations

from typing import Any

from pg_llm_batch import BatchAPIClient, BatchInferencePort


class _ProviderNeutralAdapter:
    """Minimal non-HTTP adapter proving the port is not tied to BatchAPIClient."""

    async def upload_jsonl(
        self,
        file_path: str,
        endpoint_alias: str,
        purpose: str = "batch",
        expires_after_seconds: int | None = None,
    ) -> dict[str, Any]:
        return {"id": file_path, "endpoint_alias": endpoint_alias, "purpose": purpose}

    async def create_batch_job(
        self,
        input_file_id: str,
        endpoint_alias: str,
        endpoint: str = "/v1/chat/completions",
        metadata: dict[str, Any] | None = None,
        output_expires_after_seconds: int | None = None,
    ) -> dict[str, Any]:
        return {"id": input_file_id, "endpoint": endpoint, "metadata": metadata}

    async def get_batch_status(
        self, batch_id: str, endpoint_alias: str
    ) -> dict[str, Any]:
        return {"id": batch_id, "endpoint_alias": endpoint_alias, "status": "running"}

    async def cancel_batch(
        self, batch_id: str, endpoint_alias: str
    ) -> dict[str, Any]:
        return {"id": batch_id, "endpoint_alias": endpoint_alias, "status": "cancelling"}

    async def download_results(
        self, batch_id: str, endpoint_alias: str
    ) -> dict[str, Any]:
        return {"batch_id": batch_id, "endpoint_alias": endpoint_alias, "responses": []}

    async def delete_file(
        self, file_id: str, endpoint_alias: str
    ) -> dict[str, Any]:
        return {"id": file_id, "endpoint_alias": endpoint_alias, "deleted": True}


def test_batch_api_client_satisfies_provider_neutral_batch_inference_port() -> None:
    """The shipped HTTP adapter must satisfy the public lifecycle port structurally."""
    assert issubclass(BatchAPIClient, BatchInferencePort)


def test_batch_inference_port_accepts_non_http_adapter_without_routing_authority() -> None:
    """A provider adapter needs lifecycle operations, not discovery or routing APIs."""
    assert isinstance(_ProviderNeutralAdapter(), BatchInferencePort)
    assert not hasattr(_ProviderNeutralAdapter(), "discover_models")
    assert not hasattr(_ProviderNeutralAdapter(), "route_model")
