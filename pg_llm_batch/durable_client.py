# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Durable Batch API client that records provider lifecycle observations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any, Dict, Optional

from .batch_api_client import BatchAPIClient, CredentialsProvider
from .db import persist_remote_batch_state
from .exceptions import GatewayError

LifecycleRecorder = Callable[[str, str, Mapping[str, Any]], Any]


class DurableBatchAPIClient(BatchAPIClient):
    """Batch API client with fail-closed PostgreSQL lifecycle persistence.

    The base client remains available for hosts that already own lifecycle
    persistence. This subclass records every successful create, poll, and cancel
    transition through an injectable recorder. The default recorder uses the
    packaged ``llm_remote_batch_jobs`` table.
    """

    def __init__(
        self,
        postgres_dsn: str,
        credentials: CredentialsProvider,
        *,
        lifecycle_recorder: LifecycleRecorder = persist_remote_batch_state,
        **client_options: Any,
    ) -> None:
        """Initialize HTTP behavior and the durable lifecycle recorder."""
        super().__init__(postgres_dsn, credentials, **client_options)
        self._lifecycle_recorder = lifecycle_recorder

    async def _persist_snapshot(
        self,
        endpoint_alias: str,
        provider_batch: Mapping[str, Any],
        *,
        operation: str,
    ) -> None:
        """Persist one observation or raise a typed recovery-oriented error."""
        try:
            await asyncio.to_thread(
                self._lifecycle_recorder,
                self.postgres_dsn,
                endpoint_alias,
                provider_batch,
            )
        except Exception as exc:
            batch_id = provider_batch.get("id")
            raise GatewayError(
                f"{operation} succeeded but lifecycle persistence failed",
                response_data={
                    "operation": operation,
                    "endpoint_alias": endpoint_alias,
                    "batch_id": batch_id,
                    "error_type": type(exc).__name__,
                },
            ) from exc

    async def create_batch_job(
        self,
        input_file_id: str,
        endpoint_alias: str,
        endpoint: str = "/v1/chat/completions",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a remote job and durably record its initial provider state."""
        result = await super().create_batch_job(
            input_file_id,
            endpoint_alias,
            endpoint=endpoint,
            metadata=metadata,
        )
        snapshot = dict(result)
        snapshot.setdefault("input_file_id", input_file_id)
        snapshot.setdefault("endpoint", endpoint)
        if metadata is not None:
            snapshot.setdefault("metadata", metadata)
        await self._persist_snapshot(
            endpoint_alias,
            snapshot,
            operation="Batch creation",
        )
        return result

    async def get_batch_status(
        self, batch_id: str, endpoint_alias: str
    ) -> Dict[str, Any]:
        """Poll a remote job and durably record the normalized observation."""
        result = await super().get_batch_status(batch_id, endpoint_alias)
        snapshot = dict(result)
        snapshot.setdefault("id", batch_id)
        await self._persist_snapshot(
            endpoint_alias,
            snapshot,
            operation="Batch status",
        )
        return result

    async def cancel_batch(
        self, batch_id: str, endpoint_alias: str
    ) -> Dict[str, Any]:
        """Cancel a remote job and record only an accepted cancellation."""
        result = await super().cancel_batch(batch_id, endpoint_alias)
        if result.get("success"):
            snapshot = {
                "id": batch_id,
                "status": result.get("status", "cancelling"),
            }
            await self._persist_snapshot(
                endpoint_alias,
                snapshot,
                operation="Batch cancellation",
            )
        return result
