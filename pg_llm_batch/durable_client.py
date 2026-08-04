# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Durable Batch API client that records provider lifecycle observations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any, Dict, Optional

from .batch_api_client import BatchAPIClient, CredentialsProvider
from .db import (
    persist_remote_batch_state,
    reserve_remote_batch_observation_order,
)
from .exceptions import GatewayError

LifecycleRecorder = Callable[[str, str, Mapping[str, Any], int], Any]
ObservationReserver = Callable[[str], int]


class DurableBatchAPIClient(BatchAPIClient):
    """Batch API client with fail-closed PostgreSQL lifecycle persistence.

    The base client remains available for hosts that already own lifecycle
    persistence. This subclass reserves a database-owned observation order
    before every provider request and records successful create, poll, and
    accepted-cancel transitions through injectable persistence seams.
    """

    def __init__(
        self,
        postgres_dsn: str,
        credentials: CredentialsProvider,
        *,
        lifecycle_recorder: LifecycleRecorder = persist_remote_batch_state,
        observation_reserver: ObservationReserver = (
            reserve_remote_batch_observation_order
        ),
        **client_options: Any,
    ) -> None:
        """Initialize HTTP behavior and durable ordering/persistence seams."""
        super().__init__(postgres_dsn, credentials, **client_options)
        self._lifecycle_recorder = lifecycle_recorder
        self._observation_reserver = observation_reserver

    async def _reserve_observation_order(
        self,
        endpoint_alias: str,
        *,
        operation: str,
        batch_id: Optional[str],
    ) -> int:
        """Reserve one global order or fail before provider I/O begins."""
        try:
            observation_order = await asyncio.to_thread(
                self._observation_reserver,
                self.postgres_dsn,
            )
            if (
                isinstance(observation_order, bool)
                or not isinstance(observation_order, int)
                or observation_order <= 0
            ):
                raise ValueError(
                    "observation reserver must return a positive integer"
                )
            return observation_order
        except Exception as exc:
            raise GatewayError(
                f"{operation} lifecycle reservation failed",
                response_data={
                    "operation": operation,
                    "phase": "reservation",
                    "endpoint_alias": endpoint_alias,
                    "batch_id": batch_id,
                    "error_type": type(exc).__name__,
                },
            ) from exc

    async def _persist_snapshot(
        self,
        endpoint_alias: str,
        provider_batch: Mapping[str, Any],
        observation_order: int,
        *,
        operation: str,
    ) -> None:
        """Persist one ordered observation or raise recovery-oriented evidence."""
        try:
            await asyncio.to_thread(
                self._lifecycle_recorder,
                self.postgres_dsn,
                endpoint_alias,
                provider_batch,
                observation_order,
            )
        except Exception as exc:
            batch_id = provider_batch.get("id")
            raise GatewayError(
                f"{operation} succeeded but lifecycle persistence failed",
                response_data={
                    "operation": operation,
                    "phase": "persistence",
                    "endpoint_alias": endpoint_alias,
                    "batch_id": batch_id,
                    "observation_order": observation_order,
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
        """Reserve order, create a remote job, and persist its initial state."""
        observation_order = await self._reserve_observation_order(
            endpoint_alias,
            operation="Batch creation",
            batch_id=None,
        )
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
            observation_order,
            operation="Batch creation",
        )
        return result

    async def get_batch_status(
        self, batch_id: str, endpoint_alias: str
    ) -> Dict[str, Any]:
        """Reserve order, poll a remote job, and persist the observation."""
        observation_order = await self._reserve_observation_order(
            endpoint_alias,
            operation="Batch status",
            batch_id=batch_id,
        )
        result = await super().get_batch_status(batch_id, endpoint_alias)
        snapshot = dict(result)
        snapshot.setdefault("id", batch_id)
        await self._persist_snapshot(
            endpoint_alias,
            snapshot,
            observation_order,
            operation="Batch status",
        )
        return result

    async def cancel_batch(
        self, batch_id: str, endpoint_alias: str
    ) -> Dict[str, Any]:
        """Reserve order, cancel remotely, and persist accepted cancellation."""
        observation_order = await self._reserve_observation_order(
            endpoint_alias,
            operation="Batch cancellation",
            batch_id=batch_id,
        )
        result = await super().cancel_batch(batch_id, endpoint_alias)
        if result.get("success"):
            snapshot = {
                "id": batch_id,
                "status": result.get("status", "cancelling"),
            }
            await self._persist_snapshot(
                endpoint_alias,
                snapshot,
                observation_order,
                operation="Batch cancellation",
            )
        return result
