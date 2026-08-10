# SPDX-License-Identifier: Apache-2.0
"""Regression tests for observability lifecycle and construction isolation."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from typing import Any

import pytest

from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.observability import OpenTelemetryBatchAPIClient


@dataclass
class CapturingSpan:
    """Capture bounded span attributes and context-exit arguments."""

    attributes: dict[str, Any] = field(default_factory=dict)
    exit_arguments: tuple[Any, ...] | None = None

    def set_attribute(self, name: str, value: Any) -> None:
        """Record one bounded span attribute."""
        self.attributes[name] = value


class CapturingSpanContext:
    """Expose a span and retain every value supplied during context exit."""

    def __init__(self, span: CapturingSpan) -> None:
        self.span = span

    def __enter__(self) -> CapturingSpan:
        """Enter the span context."""
        return self.span

    def __exit__(self, *exc: Any) -> None:
        """Record context-exit arguments without suppressing control flow."""
        self.span.exit_arguments = exc
        return None


class FailingEnterSpanContext:
    """Track whether cleanup is called after telemetry context entry fails."""

    def __init__(self) -> None:
        self.exit_calls = 0

    def __enter__(self) -> CapturingSpan:
        """Model a telemetry context that fails before it is entered."""
        raise RuntimeError("span entry unavailable")

    def __exit__(self, *_exc: Any) -> None:
        """Record an invalid exit attempt after failed entry."""
        self.exit_calls += 1
        return None


class CapturingTracer:
    """Create inspectable span contexts for lifecycle tests."""

    def __init__(self) -> None:
        self.spans: list[CapturingSpan] = []

    def start_as_current_span(
        self,
        _name: str,
        **_kwargs: Any,
    ) -> CapturingSpanContext:
        """Create one inspectable span context."""
        span = CapturingSpan()
        self.spans.append(span)
        return CapturingSpanContext(span)


class FailingEnterTracer:
    """Return one span context whose entry fails before activation."""

    def __init__(self) -> None:
        self.context = FailingEnterSpanContext()

    def start_as_current_span(
        self,
        _name: str,
        **_kwargs: Any,
    ) -> FailingEnterSpanContext:
        """Return the deterministic failed-entry context."""
        return self.context


class CancellingTracer:
    """Raise task cancellation from a telemetry-only span-start boundary."""

    def start_as_current_span(
        self,
        _name: str,
        **_kwargs: Any,
    ) -> CapturingSpanContext:
        """Model a tracer that raises cancellation before a span is created."""
        raise asyncio.CancelledError("telemetry-only-cancellation")


@dataclass
class CapturingInstrument:
    """Capture low-cardinality metric calls."""

    calls: list[tuple[float, dict[str, Any]]] = field(default_factory=list)

    def add(self, value: int, attributes: dict[str, Any]) -> None:
        """Capture one counter update."""
        self.calls.append((float(value), dict(attributes)))

    def record(self, value: float, attributes: dict[str, Any]) -> None:
        """Capture one duration sample."""
        self.calls.append((float(value), dict(attributes)))


class CancellingInstrument(CapturingInstrument):
    """Raise task cancellation from telemetry-only metric boundaries."""

    def add(self, _value: int, attributes: dict[str, Any]) -> None:
        """Model cancellation while recording a counter measurement."""
        del attributes
        raise asyncio.CancelledError("telemetry-counter-cancellation")

    def record(self, _value: float, attributes: dict[str, Any]) -> None:
        """Model cancellation while recording a duration measurement."""
        del attributes
        raise asyncio.CancelledError("telemetry-histogram-cancellation")


class CapturingMeter:
    """Create inspectable metric instruments."""

    def __init__(self) -> None:
        self.counter = CapturingInstrument()
        self.histogram = CapturingInstrument()

    def create_counter(
        self,
        _name: str,
        *,
        unit: str,
        description: str,
    ) -> CapturingInstrument:
        """Return the inspectable counter."""
        del unit, description
        return self.counter

    def create_histogram(
        self,
        _name: str,
        *,
        unit: str,
        description: str,
    ) -> CapturingInstrument:
        """Return the inspectable histogram."""
        del unit, description
        return self.histogram


class CancellingMeter(CapturingMeter):
    """Create instruments that raise cancellation during telemetry emission."""

    def __init__(self) -> None:
        self.counter = CancellingInstrument()
        self.histogram = CancellingInstrument()


class ExplodingCreationMeter:
    """Raise while the client creates either metric instrument."""

    def create_counter(self, _name: str, **_kwargs: Any) -> Any:
        """Model counter-construction failure."""
        raise RuntimeError("counter provider unavailable")

    def create_histogram(self, _name: str, **_kwargs: Any) -> Any:
        """Model histogram-construction failure."""
        raise RuntimeError("histogram provider unavailable")


def credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic credentials for lifecycle tests."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


async def test_async_cancellation_closes_span_without_exception_payload(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Task cancellation is measured and re-raised without entering telemetry payloads."""
    cancellation = asyncio.CancelledError("tenant-secret-cancellation")
    tracer = CapturingTracer()
    meter = CapturingMeter()

    async def parent_method(_self: BatchAPIClient, *_args: Any, **_kwargs: Any) -> Any:
        raise cancellation

    monkeypatch.setattr(BatchAPIClient, "cancel_batch", parent_method)
    client = OpenTelemetryBatchAPIClient(
        "postgresql://example",
        credentials,
        tracer=tracer,
        meter=meter,
    )

    with pytest.raises(asyncio.CancelledError) as exc_info:
        await client.cancel_batch("batch-private", "tenant-private")

    assert exc_info.value is cancellation
    assert tracer.spans[0].exit_arguments == (None, None, None)
    assert tracer.spans[0].attributes == {
        "pg_llm_batch.operation.name": "cancel_batch",
        "error.type": "CancelledError",
    }
    expected_attributes = {
        "pg_llm_batch.operation.name": "cancel_batch",
        "pg_llm_batch.operation.outcome": "error",
        "error.type": "CancelledError",
    }
    assert meter.counter.calls == [(1.0, expected_attributes)]
    assert len(meter.histogram.calls) == 1
    assert meter.histogram.calls[0][1] == expected_attributes
    emitted = repr((tracer.spans, meter.counter.calls, meter.histogram.calls))
    assert "tenant-secret-cancellation" not in emitted
    assert "batch-private" not in emitted
    assert "tenant-private" not in emitted


async def test_tracer_cancellation_cannot_skip_successful_provider_operation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Telemetry-originated cancellation cannot skip or replace provider success."""
    expected = {"success": True}
    calls = 0

    async def parent_method(_self: BatchAPIClient, *_args: Any, **_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return expected

    monkeypatch.setattr(BatchAPIClient, "cancel_batch", parent_method)
    client = OpenTelemetryBatchAPIClient(
        "postgresql://example",
        credentials,
        tracer=CancellingTracer(),
        meter=CapturingMeter(),
    )

    result = await client.cancel_batch("batch-1", "default")

    assert result is expected
    assert calls == 1


async def test_failed_span_entry_is_not_exited_after_provider_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A context that never entered must not receive a synthetic exit call."""
    expected = {"success": True}
    tracer = FailingEnterTracer()

    async def parent_method(_self: BatchAPIClient, *_args: Any, **_kwargs: Any) -> Any:
        return expected

    monkeypatch.setattr(BatchAPIClient, "cancel_batch", parent_method)
    client = OpenTelemetryBatchAPIClient(
        "postgresql://example",
        credentials,
        tracer=tracer,
        meter=CapturingMeter(),
    )

    result = await client.cancel_batch("batch-1", "default")

    assert result is expected
    assert tracer.context.exit_calls == 0


async def test_metric_cancellation_cannot_replace_successful_provider_result(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Telemetry-originated metric cancellation cannot replace provider success."""
    expected = {"success": True}

    async def parent_method(_self: BatchAPIClient, *_args: Any, **_kwargs: Any) -> Any:
        return expected

    monkeypatch.setattr(BatchAPIClient, "cancel_batch", parent_method)
    client = OpenTelemetryBatchAPIClient(
        "postgresql://example",
        credentials,
        tracer=CapturingTracer(),
        meter=CancellingMeter(),
    )

    result = await client.cancel_batch("batch-1", "default")

    assert result is expected


async def test_metric_cancellation_cannot_mask_provider_cancellation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Telemetry cancellation cannot replace the provider's cancellation object."""
    cancellation = asyncio.CancelledError("provider-cancellation")

    async def parent_method(_self: BatchAPIClient, *_args: Any, **_kwargs: Any) -> Any:
        raise cancellation

    monkeypatch.setattr(BatchAPIClient, "cancel_batch", parent_method)
    client = OpenTelemetryBatchAPIClient(
        "postgresql://example",
        credentials,
        tracer=CapturingTracer(),
        meter=CancellingMeter(),
    )

    with pytest.raises(asyncio.CancelledError) as exc_info:
        await client.cancel_batch("batch-1", "default")

    assert exc_info.value is cancellation


async def test_metric_instrument_creation_failure_does_not_disable_client(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken meter cannot prevent construction or a provider operation."""
    expected = {"success": True}
    calls = 0

    async def parent_method(_self: BatchAPIClient, *_args: Any, **_kwargs: Any) -> Any:
        nonlocal calls
        calls += 1
        return expected

    monkeypatch.setattr(BatchAPIClient, "cancel_batch", parent_method)
    client = OpenTelemetryBatchAPIClient(
        "postgresql://example",
        credentials,
        tracer=CapturingTracer(),
        meter=ExplodingCreationMeter(),
    )

    result = await client.cancel_batch("batch-1", "default")

    assert result is expected
    assert calls == 1