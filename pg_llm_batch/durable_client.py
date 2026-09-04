# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Durable Batch API clients that record provider lifecycle observations."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any, Dict, NoReturn, Optional

from .batch_api_client import BatchAPIClient, CredentialsProvider
from .db import (
    normalize_optional_provider_text,
    normalize_provider_metadata,
    persist_remote_batch_state,
    persist_tenant_remote_batch_state,
    reserve_remote_batch_observation_order,
    validate_endpoint_alias,
    validate_optional_remote_resource_id,
    validate_remote_resource_id,
    validate_tenant_scope,
)
from .exceptions import GatewayError, ValidationError

LifecycleRecorder = Callable[[str, str, Mapping[str, Any], int], Any]
TenantLifecycleRecorder = Callable[[str, str, str, Mapping[str, Any], int], Any]
ObservationReserver = Callable[[str], int]


def _validate_callable_seam(field: str, value: Any) -> None:
    """Reject one non-callable lifecycle dependency during construction.

    Args:
        field: Public constructor field used in structured diagnostics.
        value: Candidate recorder or observation-reservation callable.

    Raises:
        ValidationError: If the supplied dependency cannot be called.
    """
    if not callable(value):
        raise ValidationError(
            field=field,
            value=value,
            reason="must be callable",
        )


def _bounded_lifecycle_error_type(error: Exception) -> str:
    """Map arbitrary implementation failures into a finite compatibility vocabulary."""
    if isinstance(error, ValidationError):
        return "ValidationError"
    if isinstance(error, ValueError):
        return "ValueError"
    if isinstance(error, OSError):
        return "OSError"
    return "RuntimeError"


def _raise_lifecycle_gateway_error(
    message: str,
    response_data: Mapping[str, Any],
) -> NoReturn:
    """Raise one package error after removing any implicit exception context."""
    error = GatewayError(message, response_data=dict(response_data))
    try:
        raise error from None
    except GatewayError:
        error.__context__ = None
        raise


class DurableBatchAPIClient(BatchAPIClient):
    """Batch API client with fail-closed standalone lifecycle persistence.

    This client preserves the original four-argument recorder seam. Successful
    create, poll, and accepted-cancel transitions are stored under the explicit
    ``standalone`` database scope by the default recorder.
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
        _validate_callable_seam("lifecycle_recorder", lifecycle_recorder)
        _validate_callable_seam("observation_reserver", observation_reserver)
        super().__init__(postgres_dsn, credentials, **client_options)
        self._lifecycle_recorder = lifecycle_recorder
        self._observation_reserver = observation_reserver

    def _lifecycle_recovery_context(self) -> Dict[str, Any]:
        """Return trusted context safe to expose in recovery diagnostics."""
        return {}

    async def _record_lifecycle_snapshot(
        self,
        endpoint_alias: str,
        provider_batch: Mapping[str, Any],
        observation_order: int,
    ) -> None:
        """Dispatch one snapshot through the compatible recorder seam."""
        await asyncio.to_thread(
            self._lifecycle_recorder,
            self.postgres_dsn,
            endpoint_alias,
            provider_batch,
            observation_order,
        )

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
        except Exception as exc:
            failure_type = _bounded_lifecycle_error_type(exc)
        else:
            return observation_order

        response_data: Dict[str, Any] = {
            "operation": operation,
            "phase": "reservation",
            "endpoint_alias": endpoint_alias,
            "batch_id": batch_id,
            "error_type": failure_type,
        }
        response_data.update(self._lifecycle_recovery_context())
        _raise_lifecycle_gateway_error(
            f"{operation} lifecycle reservation failed",
            response_data,
        )

    async def _persist_snapshot(
        self,
        endpoint_alias: str,
        provider_batch: Mapping[str, Any],
        observation_order: int,
        *,
        operation: str,
        expected_batch_id: Optional[str] = None,
    ) -> None:
        """Persist one ordered observation while enforcing expected identity.

        Args:
            endpoint_alias: Validated local provider endpoint alias.
            provider_batch: Untrusted provider lifecycle response object.
            observation_order: Database-owned order reserved before provider I/O.
            operation: Stable operation label for recovery evidence.
            expected_batch_id: Optional trusted requested identifier for poll paths.

        Raises:
            GatewayError: If validation or lifecycle persistence fails after a
                successful provider operation.
        """
        recovery_batch_id: Optional[str] = None
        try:
            if expected_batch_id is not None:
                recovery_batch_id = validate_remote_resource_id(
                    expected_batch_id,
                    "expected_batch_id",
                )
            validated_batch_id = validate_remote_resource_id(
                provider_batch.get("id"),
                "remote_batch_id",
            )
            if recovery_batch_id is None:
                recovery_batch_id = validated_batch_id
            elif validated_batch_id != recovery_batch_id:
                raise ValidationError(
                    field="remote_batch_id",
                    value="<redacted>",
                    reason="does not match requested batch id",
                    message="provider batch id does not match requested batch id",
                )
            normalized_snapshot = dict(provider_batch)
            normalized_snapshot["id"] = validated_batch_id
            for resource_field in (
                "input_file_id",
                "output_file_id",
                "error_file_id",
            ):
                normalized_snapshot[resource_field] = (
                    validate_optional_remote_resource_id(
                        normalized_snapshot.get(resource_field),
                        resource_field,
                    )
                )
            normalized_snapshot["endpoint"] = normalize_optional_provider_text(
                normalized_snapshot.get("endpoint")
            )
            normalized_snapshot["status"] = (
                normalize_optional_provider_text(normalized_snapshot.get("status"))
                or "unknown"
            )
            if "metadata" in provider_batch:
                normalized_snapshot["metadata"] = normalize_provider_metadata(
                    provider_batch.get("metadata")
                )
            await self._record_lifecycle_snapshot(
                endpoint_alias,
                normalized_snapshot,
                observation_order,
            )
        except Exception as exc:
            failure_type = _bounded_lifecycle_error_type(exc)
        else:
            return

        response_data: Dict[str, Any] = {
            "operation": operation,
            "phase": "persistence",
            "endpoint_alias": endpoint_alias,
            "batch_id": recovery_batch_id,
            "observation_order": observation_order,
            "error_type": failure_type,
        }
        response_data.update(self._lifecycle_recovery_context())
        _raise_lifecycle_gateway_error(
            f"{operation} succeeded but lifecycle persistence failed",
            response_data,
        )

    async def create_batch_job(
        self,
        input_file_id: str,
        endpoint_alias: str,
        endpoint: str = "/v1/chat/completions",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Validate identities, create a remote job, and persist initial state."""
        normalized_alias = validate_endpoint_alias(endpoint_alias)
        validated_input_file_id = validate_remote_resource_id(
            input_file_id,
            "input_file_id",
        )
        observation_order = await self._reserve_observation_order(
            normalized_alias,
            operation="Batch creation",
            batch_id=None,
        )
        result = await super().create_batch_job(
            validated_input_file_id,
            normalized_alias,
            endpoint=endpoint,
            metadata=metadata,
        )
        snapshot = dict(result)
        snapshot.setdefault("input_file_id", validated_input_file_id)
        snapshot.setdefault("endpoint", endpoint)
        if metadata is not None:
            snapshot.setdefault("metadata", metadata)
        await self._persist_snapshot(
            normalized_alias,
            snapshot,
            observation_order,
            operation="Batch creation",
        )
        return result

    async def get_batch_status(
        self, batch_id: str, endpoint_alias: str
    ) -> Dict[str, Any]:
        """Validate identity, poll a remote job, and persist the observation."""
        normalized_alias = validate_endpoint_alias(endpoint_alias)
        validated_batch_id = validate_remote_resource_id(batch_id, "batch_id")
        observation_order = await self._reserve_observation_order(
            normalized_alias,
            operation="Batch status",
            batch_id=validated_batch_id,
        )
        result = await super().get_batch_status(
            validated_batch_id,
            normalized_alias,
        )
        snapshot = dict(result)
        snapshot.setdefault("id", validated_batch_id)
        await self._persist_snapshot(
            normalized_alias,
            snapshot,
            observation_order,
            operation="Batch status",
            expected_batch_id=validated_batch_id,
        )
        return result

    async def cancel_batch(
        self, batch_id: str, endpoint_alias: str
    ) -> Dict[str, Any]:
        """Validate identity, cancel remotely, and persist accepted cancellation."""
        normalized_alias = validate_endpoint_alias(endpoint_alias)
        validated_batch_id = validate_remote_resource_id(batch_id, "batch_id")
        observation_order = await self._reserve_observation_order(
            normalized_alias,
            operation="Batch cancellation",
            batch_id=validated_batch_id,
        )
        result = await super().cancel_batch(
            validated_batch_id,
            normalized_alias,
        )
        if result.get("success"):
            snapshot = {
                "id": validated_batch_id,
                "status": result.get("status", "cancelling"),
            }
            await self._persist_snapshot(
                normalized_alias,
                snapshot,
                observation_order,
                operation="Batch cancellation",
            )
        return result


class TenantDurableBatchAPIClient(DurableBatchAPIClient):
    """Durable Batch API client with a required trusted tenant identity.

    The tenant scope is validated synchronously at construction and remains
    read-only. It is propagated only through the explicit tenant-aware recorder
    seam and trusted recovery evidence; provider data never selects it.
    """

    def __init__(
        self,
        postgres_dsn: str,
        credentials: CredentialsProvider,
        *,
        tenant_scope: str,
        tenant_lifecycle_recorder: TenantLifecycleRecorder = (
            persist_tenant_remote_batch_state
        ),
        observation_reserver: ObservationReserver = (
            reserve_remote_batch_observation_order
        ),
        **client_options: Any,
    ) -> None:
        """Initialize the client after validating trusted tenant context."""
        self._tenant_scope = validate_tenant_scope(tenant_scope)
        if "lifecycle_recorder" in client_options:
            raise ValidationError(
                field="lifecycle_recorder",
                value="<provided>",
                reason="tenant clients require tenant_lifecycle_recorder",
                safe_value="<provided>",
            )
        _validate_callable_seam(
            "tenant_lifecycle_recorder",
            tenant_lifecycle_recorder,
        )
        self._tenant_lifecycle_recorder = tenant_lifecycle_recorder
        super().__init__(
            postgres_dsn,
            credentials,
            observation_reserver=observation_reserver,
            **client_options,
        )

    @property
    def tenant_scope(self) -> str:
        """Return the exact immutable host-authorized tenant identity."""
        return self._tenant_scope

    def _lifecycle_recovery_context(self) -> Dict[str, Any]:
        """Return the trusted tenant identity for bounded recovery evidence."""
        return {"tenant_scope": self._tenant_scope}

    async def _record_lifecycle_snapshot(
        self,
        endpoint_alias: str,
        provider_batch: Mapping[str, Any],
        observation_order: int,
    ) -> None:
        """Dispatch one snapshot through the tenant-qualified recorder seam."""
        await asyncio.to_thread(
            self._tenant_lifecycle_recorder,
            self.postgres_dsn,
            self._tenant_scope,
            endpoint_alias,
            provider_batch,
            observation_order,
        )
