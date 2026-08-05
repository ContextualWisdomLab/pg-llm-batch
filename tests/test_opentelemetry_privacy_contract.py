# SPDX-License-Identifier: Apache-2.0
"""Regression tests for the OpenTelemetry exception-privacy boundary."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.exceptions import GatewayError
from pg_llm_batch.observability import OpenTelemetryBatchAPIClient


@dataclass
class PrivacySpan:
    """Capture every value the observability layer writes to a span."""

    attributes: dict[str, Any] = field(default_factory=dict)
    exceptions: list[BaseException] = field(default_factory=list)
    exit_arguments: tuple[Any, ...] | None = None

    def set_attribute(self, name: str, value: Any) -> None:
        """Record one span attribute."""
        self.attributes[name] = value

    def record_exception(self, error: BaseException) -> None:
        """Capture an exception event, including any sensitive message payload."""
        self.exceptions.append(error)


class PrivacySpanContext:
    """Expose one privacy-test span through the context-manager contract."""

    def __init__(self, span: PrivacySpan) -> None:
        self.span = span

    def __enter__(self) -> PrivacySpan:
        """Enter and return the captured span."""
        return self.span

    def __exit__(self, *exc: Any) -> None:
        """Capture exit arguments without suppressing the provider exception."""
        self.span.exit_arguments = exc
        return None


class PrivacyTracer:
    """Create spans whose emitted values can be inspected for secrets."""

    def __init__(self) -> None:
        self.spans: list[PrivacySpan] = []

    def start_as_current_span(
        self, _name: str, **_kwargs: Any
    ) -> PrivacySpanContext:
        """Create one inspectable span context."""
        span = PrivacySpan()
        self.spans.append(span)
        return PrivacySpanContext(span)


@dataclass
class PrivacyInstrument:
    """Capture metric attributes without retaining operation payloads."""

    calls: list[tuple[float, dict[str, Any]]] = field(default_factory=list)

    def add(self, value: int, attributes: dict[str, Any]) -> None:
        """Capture one counter measurement."""
        self.calls.append((float(value), dict(attributes)))

    def record(self, value: float, attributes: dict[str, Any]) -> None:
        """Capture one duration measurement."""
        self.calls.append((float(value), dict(attributes)))


class PrivacyMeter:
    """Return inspectable counter and histogram instruments."""

    def __init__(self) -> None:
        self.counter = PrivacyInstrument()
        self.histogram = PrivacyInstrument()

    def create_counter(
        self, _name: str, *, unit: str, description: str
    ) -> PrivacyInstrument:
        """Return the privacy-test counter."""
        del unit, description
        return self.counter

    def create_histogram(
        self, _name: str, *, unit: str, description: str
    ) -> PrivacyInstrument:
        """Return the privacy-test histogram."""
        del unit, description
        return self.histogram


def credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic credentials for the regression test."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


async def test_failure_telemetry_does_not_capture_exception_message(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A propagated provider error must not copy its secret message into telemetry."""
    secret_message = "tenant-42 bearer-token-should-never-enter-telemetry"
    failure = GatewayError(secret_message)
    tracer = PrivacyTracer()
    meter = PrivacyMeter()

    async def parent_method(_self: BatchAPIClient, *_args: Any, **_kwargs: Any) -> Any:
        raise failure

    monkeypatch.setattr(BatchAPIClient, "cancel_batch", parent_method)
    client = OpenTelemetryBatchAPIClient(
        "postgresql://example",
        credentials,
        tracer=tracer,
        meter=meter,
    )

    with pytest.raises(GatewayError) as exc_info:
        await client.cancel_batch("batch-private", "tenant-private")

    assert exc_info.value is failure
    assert tracer.spans[0].exceptions == []
    assert tracer.spans[0].exit_arguments == (None, None, None)
    emitted_telemetry = repr(
        (
            tracer.spans[0].attributes,
            tracer.spans[0].exceptions,
            tracer.spans[0].exit_arguments,
            meter.counter.calls,
            meter.histogram.calls,
        )
    )
    assert secret_message not in emitted_telemetry
    assert "batch-private" not in emitted_telemetry
    assert "tenant-private" not in emitted_telemetry


async def test_untrusted_exception_class_name_uses_bounded_fallback(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Caller-defined exception types cannot create secret or unbounded dimensions."""
    secret_type_name = "Tenant42BearerTokenMustNotBecomeTelemetry"
    custom_error_type = type(secret_type_name, (Exception,), {})
    failure = custom_error_type("private exception message")
    tracer = PrivacyTracer()
    meter = PrivacyMeter()

    async def parent_method(_self: BatchAPIClient, *_args: Any, **_kwargs: Any) -> Any:
        raise failure

    monkeypatch.setattr(BatchAPIClient, "cancel_batch", parent_method)
    client = OpenTelemetryBatchAPIClient(
        "postgresql://example",
        credentials,
        tracer=tracer,
        meter=meter,
    )

    with pytest.raises(custom_error_type) as exc_info:
        await client.cancel_batch("batch-private", "tenant-private")

    assert exc_info.value is failure
    assert tracer.spans[0].attributes["error.type"] == "_OTHER"
    assert meter.counter.calls[0][1]["error.type"] == "_OTHER"
    assert meter.histogram.calls[0][1]["error.type"] == "_OTHER"
    emitted_telemetry = repr(
        (
            tracer.spans[0].attributes,
            meter.counter.calls,
            meter.histogram.calls,
        )
    )
    assert secret_type_name not in emitted_telemetry
    assert "private exception message" not in emitted_telemetry
