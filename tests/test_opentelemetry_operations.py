# SPDX-License-Identifier: Apache-2.0
"""Tests for opt-in OpenTelemetry operation traces and metrics."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.exceptions import GatewayError
from pg_llm_batch.observability import OpenTelemetryBatchAPIClient


@dataclass
class FakeSpan:
    """Capture attributes and exception events written by the client."""

    attributes: dict[str, Any] = field(default_factory=dict)
    exceptions: list[BaseException] = field(default_factory=list)

    def set_attribute(self, name: str, value: Any) -> None:
        """Record one span attribute."""
        self.attributes[name] = value

    def record_exception(self, error: BaseException) -> None:
        """Record one exception event."""
        self.exceptions.append(error)


class FakeSpanContext:
    """Expose a fake span through the tracer context-manager contract."""

    def __init__(self, span: FakeSpan) -> None:
        self.span = span

    def __enter__(self) -> FakeSpan:
        """Return the span when the context starts."""
        return self.span

    def __exit__(self, *_exc: Any) -> None:
        """Leave the span context without suppressing exceptions."""
        return None


class FakeTracer:
    """Capture span names and options requested by the client."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, dict[str, Any]]] = []
        self.spans: list[FakeSpan] = []

    def start_as_current_span(self, name: str, **kwargs: Any) -> FakeSpanContext:
        """Create and return one fake current-span context."""
        span = FakeSpan()
        self.calls.append((name, kwargs))
        self.spans.append(span)
        return FakeSpanContext(span)


class ExplodingTracer:
    """Model a broken tracer provider that raises before entering a span."""

    def start_as_current_span(self, _name: str, **_kwargs: Any) -> FakeSpanContext:
        """Raise the provider failure instead of creating a span."""
        raise RuntimeError("tracer unavailable")


@dataclass
class FakeInstrument:
    """Capture metric measurements and their attributes."""

    calls: list[tuple[float, dict[str, Any]]] = field(default_factory=list)

    def add(self, value: int, attributes: dict[str, Any]) -> None:
        """Capture a counter addition."""
        self.calls.append((float(value), dict(attributes)))

    def record(self, value: float, attributes: dict[str, Any]) -> None:
        """Capture a histogram measurement."""
        self.calls.append((float(value), dict(attributes)))


class ExplodingInstrument(FakeInstrument):
    """Model a metric instrument whose provider fails during measurement."""

    def add(self, _value: int, attributes: dict[str, Any]) -> None:
        """Raise while adding a counter measurement."""
        del attributes
        raise RuntimeError("metric provider unavailable")

    def record(self, _value: float, attributes: dict[str, Any]) -> None:
        """Raise while recording a histogram measurement."""
        del attributes
        raise RuntimeError("metric provider unavailable")


class FakeMeter:
    """Create fake instruments while preserving instrument metadata."""

    def __init__(self) -> None:
        self.created: list[tuple[str, str, str, str]] = []
        self.counter = FakeInstrument()
        self.histogram = FakeInstrument()

    def create_counter(self, name: str, *, unit: str, description: str) -> FakeInstrument:
        """Return the shared fake counter."""
        self.created.append(("counter", name, unit, description))
        return self.counter

    def create_histogram(
        self, name: str, *, unit: str, description: str
    ) -> FakeInstrument:
        """Return the shared fake histogram."""
        self.created.append(("histogram", name, unit, description))
        return self.histogram


class ExplodingMeter(FakeMeter):
    """Create metric instruments that fail when the client emits measurements."""

    def __init__(self) -> None:
        self.created: list[tuple[str, str, str, str]] = []
        self.counter = ExplodingInstrument()
        self.histogram = ExplodingInstrument()


def credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic credentials without exposing the alias to telemetry."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


@pytest.fixture
def telemetry_client() -> tuple[OpenTelemetryBatchAPIClient, FakeTracer, FakeMeter]:
    """Build an instrumented client with deterministic in-memory telemetry."""
    tracer = FakeTracer()
    meter = FakeMeter()
    client = OpenTelemetryBatchAPIClient(
        "postgresql://example",
        credentials,
        tracer=tracer,
        meter=meter,
    )
    return client, tracer, meter


@pytest.mark.parametrize(
    ("method_name", "args", "kwargs", "expected"),
    [
        ("upload_jsonl", ("memory://input-1", "private-alias"), {}, {"id": "file-1"}),
        (
            "create_batch_job",
            ("file-1", "private-alias"),
            {"metadata": {"tenant": "hidden"}},
            {"id": "batch-1"},
        ),
        (
            "get_batch_status",
            ("batch-1", "private-alias"),
            {},
            {"status": "running"},
        ),
        (
            "wait_for_batch",
            ("batch-1", "private-alias"),
            {"poll_interval_seconds": 1.0, "timeout_seconds": 2.0},
            {"status": "completed"},
        ),
        (
            "download_results",
            ("batch-1", "private-alias"),
            {},
            {"success": True},
        ),
        (
            "cancel_batch",
            ("batch-1", "private-alias"),
            {},
            {"success": True},
        ),
    ],
)
async def test_public_operations_emit_low_cardinality_success_telemetry(
    telemetry_client: tuple[OpenTelemetryBatchAPIClient, FakeTracer, FakeMeter],
    monkeypatch: pytest.MonkeyPatch,
    method_name: str,
    args: tuple[Any, ...],
    kwargs: dict[str, Any],
    expected: dict[str, Any],
) -> None:
    """Every public operation emits one span, count, and duration without tenant data."""
    client, tracer, meter = telemetry_client

    async def parent_method(_self: BatchAPIClient, *_args: Any, **_kwargs: Any) -> Any:
        return expected

    monkeypatch.setattr(BatchAPIClient, method_name, parent_method)

    result = await getattr(client, method_name)(*args, **kwargs)

    assert result == expected
    assert tracer.calls == [
        (
            f"pg_llm_batch.{method_name}",
            {"record_exception": False, "set_status_on_exception": False},
        )
    ]
    assert tracer.spans[0].attributes == {
        "pg_llm_batch.operation.name": method_name,
    }
    assert tracer.spans[0].exceptions == []
    expected_attributes = {
        "pg_llm_batch.operation.name": method_name,
        "pg_llm_batch.operation.outcome": "success",
    }
    assert meter.counter.calls == [(1.0, expected_attributes)]
    assert len(meter.histogram.calls) == 1
    duration, attributes = meter.histogram.calls[0]
    assert duration >= 0
    assert attributes == expected_attributes
    assert "private-alias" not in repr(
        tracer.calls + meter.counter.calls + meter.histogram.calls
    )


async def test_failed_operation_records_error_type_and_reraises(
    telemetry_client: tuple[OpenTelemetryBatchAPIClient, FakeTracer, FakeMeter],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failures preserve exceptions without exporting their payloads."""
    client, tracer, meter = telemetry_client
    failure = GatewayError("provider unavailable")

    async def parent_method(_self: BatchAPIClient, *_args: Any, **_kwargs: Any) -> Any:
        raise failure

    monkeypatch.setattr(BatchAPIClient, "cancel_batch", parent_method)

    with pytest.raises(GatewayError) as exc_info:
        await client.cancel_batch("batch-1", "private-alias")

    assert exc_info.value is failure
    assert tracer.spans[0].attributes == {
        "pg_llm_batch.operation.name": "cancel_batch",
        "error.type": "GatewayError",
    }
    assert tracer.spans[0].exceptions == []
    expected_attributes = {
        "pg_llm_batch.operation.name": "cancel_batch",
        "pg_llm_batch.operation.outcome": "error",
        "error.type": "GatewayError",
    }
    assert meter.counter.calls == [(1.0, expected_attributes)]
    assert len(meter.histogram.calls) == 1
    assert meter.histogram.calls[0][1] == expected_attributes


async def test_tracer_failure_does_not_skip_or_replace_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken tracer cannot prevent the underlying operation from succeeding."""
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
        tracer=ExplodingTracer(),
        meter=FakeMeter(),
    )

    result = await client.cancel_batch("batch-1", "private-alias")

    assert result is expected
    assert calls == 1


async def test_metric_failure_does_not_replace_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken metric provider cannot replace a successful operation result."""
    expected = {"success": True}

    async def parent_method(_self: BatchAPIClient, *_args: Any, **_kwargs: Any) -> Any:
        return expected

    monkeypatch.setattr(BatchAPIClient, "cancel_batch", parent_method)
    client = OpenTelemetryBatchAPIClient(
        "postgresql://example",
        credentials,
        tracer=FakeTracer(),
        meter=ExplodingMeter(),
    )

    result = await client.cancel_batch("batch-1", "private-alias")

    assert result is expected


async def test_metric_failure_does_not_replace_operation_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken metric provider cannot mask the original operation exception."""
    failure = GatewayError("provider unavailable")

    async def parent_method(_self: BatchAPIClient, *_args: Any, **_kwargs: Any) -> Any:
        raise failure

    monkeypatch.setattr(BatchAPIClient, "cancel_batch", parent_method)
    client = OpenTelemetryBatchAPIClient(
        "postgresql://example",
        credentials,
        tracer=FakeTracer(),
        meter=ExplodingMeter(),
    )

    with pytest.raises(GatewayError) as exc_info:
        await client.cancel_batch("batch-1", "private-alias")

    assert exc_info.value is failure


def test_client_creates_stable_metric_instruments(
    telemetry_client: tuple[OpenTelemetryBatchAPIClient, FakeTracer, FakeMeter],
) -> None:
    """Metric names and units remain stable and acquisition-friendly."""
    _client, _tracer, meter = telemetry_client
    assert meter.created == [
        (
            "counter",
            "pg_llm_batch.client.operation.count",
            "{operation}",
            "Number of completed pg-llm-batch client operations.",
        ),
        (
            "histogram",
            "pg_llm_batch.client.operation.duration",
            "s",
            "Duration of completed pg-llm-batch client operations.",
        ),
    ]


def test_from_global_provider_uses_opentelemetry_api(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The convenience constructor resolves global tracer and meter providers lazily."""
    tracer = FakeTracer()
    meter = FakeMeter()
    requested_modules: list[str] = []

    class TraceModule:
        @staticmethod
        def get_tracer(name: str) -> FakeTracer:
            assert name == "pg_llm_batch"
            return tracer

    class MetricsModule:
        @staticmethod
        def get_meter(name: str) -> FakeMeter:
            assert name == "pg_llm_batch"
            return meter

    def import_module(name: str) -> Any:
        requested_modules.append(name)
        return {
            "opentelemetry.trace": TraceModule,
            "opentelemetry.metrics": MetricsModule,
        }[name]

    monkeypatch.setattr("pg_llm_batch.observability.import_module", import_module)

    client = OpenTelemetryBatchAPIClient.from_global_provider(
        "postgresql://example",
        credentials,
    )

    assert isinstance(client, OpenTelemetryBatchAPIClient)
    assert requested_modules == ["opentelemetry.trace", "opentelemetry.metrics"]
    assert client._tracer is tracer


def test_from_global_provider_reports_missing_optional_dependency(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing OpenTelemetry produces an actionable installation error."""
    def import_module(_name: str) -> Any:
        raise ModuleNotFoundError("opentelemetry")

    monkeypatch.setattr("pg_llm_batch.observability.import_module", import_module)

    with pytest.raises(RuntimeError, match="opentelemetry-api"):
        OpenTelemetryBatchAPIClient.from_global_provider(
            "postgresql://example",
            credentials,
        )
