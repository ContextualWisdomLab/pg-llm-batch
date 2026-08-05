# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Opt-in OpenTelemetry traces and metrics for public batch operations.

The base :class:`~pg_llm_batch.batch_api_client.BatchAPIClient` remains free of
OpenTelemetry dependencies. Applications that already operate an OpenTelemetry
SDK can use :class:`OpenTelemetryBatchAPIClient` to add low-cardinality,
content-free operation telemetry without exposing endpoint aliases, resource
identifiers, tenant metadata, provider URLs, API keys, or payloads.
"""

from __future__ import annotations

from importlib import import_module
from time import perf_counter
from typing import Any, Awaitable, Callable, Dict, Optional, TypeVar

from .batch_api_client import BatchAPIClient

INSTRUMENTATION_SCOPE_NAME = "pg_llm_batch"
OPERATION_NAME_ATTRIBUTE = "pg_llm_batch.operation.name"
OPERATION_OUTCOME_ATTRIBUTE = "pg_llm_batch.operation.outcome"
ERROR_TYPE_ATTRIBUTE = "error.type"

_Result = TypeVar("_Result")
_TelemetryResult = TypeVar("_TelemetryResult")


class _NoOpInstrument:
    """Accept metric calls when an injected meter cannot create an instrument."""

    def add(self, _value: int, *, attributes: Dict[str, str]) -> None:
        """Discard one unavailable counter measurement."""
        del attributes

    def record(self, _value: float, *, attributes: Dict[str, str]) -> None:
        """Discard one unavailable histogram measurement."""
        del attributes


class OpenTelemetryBatchAPIClient(BatchAPIClient):
    """Add opt-in OpenTelemetry operation spans and metrics to the batch client.

    Supply an OpenTelemetry-compatible tracer and meter explicitly when a host
    service owns provider configuration. Alternatively, use
    :meth:`from_global_provider` after installing and configuring
    ``opentelemetry-api`` and an SDK in the host application.

    Telemetry intentionally contains only the bounded operation name, outcome,
    duration, and canonical exception class name. It never records caller or
    provider identifiers, URLs, credentials, metadata, request bodies, response
    bodies, exception objects, stack traces, or exception messages. Runtime
    failures raised while creating or using an injected tracer, span, or metric
    instrument are isolated so observability cannot skip a provider operation,
    replace its return value, or mask its exception or cancellation.
    """

    def __init__(
        self,
        *args: Any,
        tracer: Any,
        meter: Any,
        **kwargs: Any,
    ) -> None:
        """Initialize the base client and fail-open OpenTelemetry instruments."""
        super().__init__(*args, **kwargs)
        self._tracer = tracer
        self._operation_count = self._telemetry_or_default(
            lambda: meter.create_counter(
                "pg_llm_batch.client.operation.count",
                unit="{operation}",
                description="Number of completed pg-llm-batch client operations.",
            ),
            _NoOpInstrument(),
        )
        self._operation_duration = self._telemetry_or_default(
            lambda: meter.create_histogram(
                "pg_llm_batch.client.operation.duration",
                unit="s",
                description="Duration of completed pg-llm-batch client operations.",
            ),
            _NoOpInstrument(),
        )

    @classmethod
    def from_global_provider(
        cls,
        *args: Any,
        **kwargs: Any,
    ) -> "OpenTelemetryBatchAPIClient":
        """Create a client from the process-global OpenTelemetry API providers.

        The import is deliberately lazy so ordinary ``BatchAPIClient`` users do
        not need OpenTelemetry installed. The host application remains
        responsible for configuring an SDK, processors, readers, and exporters.

        Raises:
            RuntimeError: When the optional ``opentelemetry-api`` package is
                unavailable.
        """
        try:
            trace = import_module("opentelemetry.trace")
            metrics = import_module("opentelemetry.metrics")
        except ModuleNotFoundError as exc:
            raise RuntimeError(
                "OpenTelemetry support requires the optional opentelemetry-api "
                "package; install opentelemetry-api>=1.44,<2 in the host service"
            ) from exc
        return cls(
            *args,
            tracer=trace.get_tracer(INSTRUMENTATION_SCOPE_NAME),
            meter=metrics.get_meter(INSTRUMENTATION_SCOPE_NAME),
            **kwargs,
        )

    @staticmethod
    def _telemetry_or_default(
        action: Callable[[], _TelemetryResult],
        default: _TelemetryResult,
    ) -> _TelemetryResult:
        """Isolate any telemetry-only failure and return the supplied safe default."""
        try:
            return action()
        except BaseException:
            return default

    def _use_span(self, span: Any, action: Callable[[Any], Any]) -> None:
        """Apply a span mutation only when a usable span was created."""
        if span is None:
            return
        self._telemetry_or_default(lambda: action(span), None)

    def _emit_measurements(
        self,
        started_at: float,
        attributes: Dict[str, str],
    ) -> None:
        """Emit count and duration independently so one failure cannot mask another."""
        self._telemetry_or_default(
            lambda: self._operation_count.add(1, attributes=attributes),
            None,
        )
        self._telemetry_or_default(
            lambda: self._operation_duration.record(
                perf_counter() - started_at,
                attributes=attributes,
            ),
            None,
        )

    def _close_span_context(self, span_context: Any) -> None:
        """Close an entered span context without exposing operation exceptions."""
        if span_context is None:
            return
        self._telemetry_or_default(
            lambda: span_context.__exit__(None, None, None),
            None,
        )

    async def _run_observed(
        self,
        operation_name: str,
        operation: Callable[[], Awaitable[_Result]],
    ) -> _Result:
        """Execute one operation and emit bounded success or error telemetry."""
        started_at = perf_counter()
        span_name = f"{INSTRUMENTATION_SCOPE_NAME}.{operation_name}"
        span_context = self._telemetry_or_default(
            lambda: self._tracer.start_as_current_span(
                span_name,
                record_exception=False,
                set_status_on_exception=False,
            ),
            None,
        )
        span = None
        if span_context is not None:
            span = self._telemetry_or_default(span_context.__enter__, None)
        self._use_span(
            span,
            lambda active_span: active_span.set_attribute(
                OPERATION_NAME_ATTRIBUTE,
                operation_name,
            ),
        )
        try:
            result = await operation()
        except BaseException as exc:
            error_type = type(exc).__name__
            self._use_span(
                span,
                lambda active_span: active_span.set_attribute(
                    ERROR_TYPE_ATTRIBUTE,
                    error_type,
                ),
            )
            attributes = {
                OPERATION_NAME_ATTRIBUTE: operation_name,
                OPERATION_OUTCOME_ATTRIBUTE: "error",
                ERROR_TYPE_ATTRIBUTE: error_type,
            }
            self._emit_measurements(started_at, attributes)
            self._close_span_context(span_context)
            raise

        attributes = {
            OPERATION_NAME_ATTRIBUTE: operation_name,
            OPERATION_OUTCOME_ATTRIBUTE: "success",
        }
        self._emit_measurements(started_at, attributes)
        self._close_span_context(span_context)
        return result

    async def upload_jsonl(
        self,
        file_path: str,
        endpoint_alias: str,
        purpose: str = "batch",
    ) -> Dict[str, Any]:
        """Upload a virtual JSONL payload while observing the public operation."""
        return await self._run_observed(
            "upload_jsonl",
            lambda: super(OpenTelemetryBatchAPIClient, self).upload_jsonl(
                file_path,
                endpoint_alias,
                purpose,
            ),
        )

    async def create_batch_job(
        self,
        input_file_id: str,
        endpoint_alias: str,
        endpoint: str = "/v1/chat/completions",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        """Create a provider batch while observing the public operation."""
        return await self._run_observed(
            "create_batch_job",
            lambda: super(OpenTelemetryBatchAPIClient, self).create_batch_job(
                input_file_id,
                endpoint_alias,
                endpoint,
                metadata,
            ),
        )

    async def get_batch_status(
        self,
        batch_id: str,
        endpoint_alias: str,
    ) -> Dict[str, Any]:
        """Poll a provider batch while observing the public operation."""
        return await self._run_observed(
            "get_batch_status",
            lambda: super(OpenTelemetryBatchAPIClient, self).get_batch_status(
                batch_id,
                endpoint_alias,
            ),
        )

    async def wait_for_batch(
        self,
        batch_id: str,
        endpoint_alias: str,
        *,
        poll_interval_seconds: float = 5.0,
        timeout_seconds: float = 3600.0,
    ) -> Dict[str, Any]:
        """Wait for a terminal batch while observing the complete wait operation."""
        return await self._run_observed(
            "wait_for_batch",
            lambda: super(OpenTelemetryBatchAPIClient, self).wait_for_batch(
                batch_id,
                endpoint_alias,
                poll_interval_seconds=poll_interval_seconds,
                timeout_seconds=timeout_seconds,
            ),
        )

    async def download_results(
        self,
        batch_id: str,
        endpoint_alias: str,
    ) -> Dict[str, Any]:
        """Download bounded provider results while observing the public operation."""
        return await self._run_observed(
            "download_results",
            lambda: super(OpenTelemetryBatchAPIClient, self).download_results(
                batch_id,
                endpoint_alias,
            ),
        )

    async def cancel_batch(
        self,
        batch_id: str,
        endpoint_alias: str,
    ) -> Dict[str, Any]:
        """Cancel a provider batch while observing the public operation."""
        return await self._run_observed(
            "cancel_batch",
            lambda: super(OpenTelemetryBatchAPIClient, self).cancel_batch(
                batch_id,
                endpoint_alias,
            ),
        )
