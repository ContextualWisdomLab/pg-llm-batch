# SPDX-License-Identifier: Apache-2.0
"""Provider-neutral batch lifecycle port owned by pg-llm-batch.

The port describes only provider-facing batch transport and lifecycle operations.
It deliberately excludes model discovery, provider selection, routing, fallback,
and credential discovery; those authorities remain outside pg-llm-batch and may be
supplied by contextual-orchestrator or another host through an adapter.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Protocol, runtime_checkable


@runtime_checkable
class BatchInferencePort(Protocol):
    """Expose the provider-neutral asynchronous batch lifecycle boundary.

    Implementations may speak an OpenAI-compatible API or another provider batch
    wire contract. Callers provide an already-authorized endpoint alias and exact
    batch endpoint; the port never discovers models/providers or decides routing.
    Returned mappings are provider transport evidence and must be validated by the
    owning lifecycle/result-ingestion boundary before becoming durable truth.
    """

    async def upload_jsonl(
        self,
        file_path: str,
        endpoint_alias: str,
        purpose: str = "batch",
        expires_after_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Upload one prepared memory-backed JSONL payload to the selected adapter."""
        ...

    async def create_batch_job(
        self,
        input_file_id: str,
        endpoint_alias: str,
        endpoint: str = "/v1/chat/completions",
        metadata: Optional[Dict[str, Any]] = None,
        output_expires_after_seconds: Optional[int] = None,
    ) -> Dict[str, Any]:
        """Create one provider batch for an already selected endpoint contract."""
        ...

    async def get_batch_status(
        self,
        batch_id: str,
        endpoint_alias: str,
    ) -> Dict[str, Any]:
        """Retrieve current provider lifecycle evidence for one remote batch."""
        ...

    async def cancel_batch(
        self,
        batch_id: str,
        endpoint_alias: str,
    ) -> Dict[str, Any]:
        """Request provider cancellation for one validated remote batch identity."""
        ...

    async def download_results(
        self,
        batch_id: str,
        endpoint_alias: str,
    ) -> Dict[str, Any]:
        """Retrieve bounded terminal provider output and error evidence."""
        ...

    async def delete_file(
        self,
        file_id: str,
        endpoint_alias: str,
    ) -> Dict[str, Any]:
        """Delete one provider file through the adapter's authorized cleanup path."""
        ...
