# SPDX-License-Identifier: Apache-2.0
"""Tests for low-cardinality OpenTelemetry checkpoint instrumentation."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pytest

from pg_llm_batch.checkpoint_store import CheckpointConflictError
from pg_llm_batch.checkpoint_telemetry import OpenTelemetryCheckpointStore
from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.result_streaming import BatchResultCheckpoint


@dataclass(frozen=True)
class RecordedMeasurement:
    """Capture one deterministic metric call."""

    value: float
    attributes: dict[str, str]


class FakeInstrument:
    """Collect metric calls or raise one configured telemetry failure."""

    def __init__(self, *, failure: Exception | None = None) -> None:
        self.failure = failure
        self.measurements: list[RecordedMeasurement] = []

    def add(self, value: int, attributes: dict[str, str]) -> None:
        """Record one counter measurement."""
        if self.failure is not None:
            raise self.failure
        self.measurements.append(RecordedMeasurement(float(value), dict(attributes)))

    def record(self, value: float, attributes: dict[str, str]) -> None:
        """Record one histogram measurement."""
        if self.failure is not None:
            raise self.failure
        self.measurements.append(RecordedMeasurement(float(value), dict(attributes)))


class FakeMeter:
    """Create deterministic counter and histogram instruments."""

    def __init__(
        self,
        *,
        create_failure: Exception | None = None,
        measurement_failure: Exception | None = None,
    ) -> None:
        self.create_failure = create_failure
        self.counter = FakeInstrument(failure=measurement_failure)
        self.histogram = FakeInstrument(failure=measurement_failure)
        self.created: list[tuple[str, str, str]] = []

    def create_counter(self, name: str, *, unit: str, description: str) -> FakeInstrument:
        """Create the operation counter."""
        if self.create_failure is not None:
            raise self.create_failure
        self.created.append((name, unit, description))
        return self.counter

    def create_histogram(
        self,
        name: str,
        *,
        unit: str,
        description: str,
    ) -> FakeInstrument:
        """Create the operation-duration histogram."""
        if self.create_failure is not None:
            raise self.create_failure
        self.created.append((name, unit, description))
        return self.histogram


class FakeSpan:
    """Collect bounded span attributes without recording exceptions."""

    def __init__(self, *, set_failure: Exception | None = None) -> None:
        self.set_failure = set_failure
        self.attributes: dict[str, str] = {}
        self.recorded_exceptions: list[BaseException] = []

    def set_attribute(self, name: str, value: str) -> None:
        """Record one span attribute."""
        if self.set_failure is not None:
            raise self.set_failure
        self.attributes[name] = value

    def record_exception(self, error: BaseException) -> None:
        """Expose accidental exception recording to confidentiality assertions."""
        self.recorded_exceptions.append(error)


class FakeSpanContext:
    """Enter and exit one fake span with configurable telemetry failures."""

    def __init__(
        self,
        span: FakeSpan,
        *,
        enter_failure: Exception | None = None,
        exit_failure: Exception | None = None,
    ) -> None:
        self.span = span
        self.enter_failure = enter_failure
        self.exit_failure = exit_failure
        self.exits: list[tuple[Any, Any, Any]] = []

    def __enter__(self) -> FakeSpan:
        """Enter the fake span context."""
        if self.enter_failure is not None:
            raise self.enter_failure
        return self.span

    def __exit__(self, *exc: Any) -> bool:
        """Record context exit and never suppress application exceptions."""
        self.exits.append(exc)
        if self.exit_failure is not None:
            raise self.exit_failure
        return False


class FakeTracer:
    """Create deterministic spans using the OpenTelemetry tracer call shape."""

    def __init__(
        self,
        *,
        start_failure: Exception | None = None,
        enter_failure: Exception | None = None,
        exit_failure: Exception | None = None,
        set_failure: Exception | None = None,
    ) -> None:
        self.start_failure = start_failure
        self.enter_failure = enter_failure
        self.exit_failure = exit_failure
        self.set_failure = set_failure
        self.starts: list[tuple[str, dict[str, str], bool, bool]] = []
        self.contexts: list[FakeSpanContext] = []

    def start_as_current_span(
        self,
        name: str,
        *,
        attributes: dict[str, str],
        record_exception: bool,
        set_status_on_exception: bool,
    ) -> FakeSpanContext:
        """Create one current-span context with exception capture disabled."""
        if self.start_failure is not None:
            raise self.start_failure
        self.starts.append(
            (
                name,
                dict(attributes),
                record_exception,
                set_status_on_exception,
            )
        )
        context = FakeSpanContext(
            FakeSpan(set_failure=self.set_failure),
            enter_failure=self.enter_failure,
            exit_failure=self.exit_failure,
        )
        self.contexts.append(context)
        return context


class FakeCheckpointStore:
    """Provide all four checkpoint operations with deterministic outcomes."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...], dict[str, Any]]] = []
        self.results: dict[str, Any] = {}
        self.failures: dict[str, BaseException] = {}

    def _run(self, operation: str, *args: Any, **kwargs: Any) -> Any:
        """Record and execute one configured checkpoint operation."""
        self.calls.append((operation, args, kwargs))
        failure = self.failures.get(operation)
        if failure is not None:
            raise failure
        return self.results.get(operation)

    def load(self, *args: Any, **kwargs: Any) -> Any:
        """Run one package-owned load."""
        return self._run("load", *args, **kwargs)

    def load_in_transaction(self, *args: Any, **kwargs: Any) -> Any:
        """Run one caller-owned load."""
        return self._run("load_in_transaction", *args, **kwargs)

    def save(self, *args: Any, **kwargs: Any) -> Any:
        """Run one package-owned save."""
        return self._run("save", *args, **kwargs)

    def save_in_transaction(self, *args: Any, **kwargs: Any) -> Any:
        """Run one caller-owned save."""
        return self._run("save_in_transaction", *args, **kwargs)


def checkpoint() -> BatchResultCheckpoint:
    """Build one valid checkpoint without embedding it in telemetry attributes."""
    return BatchResultCheckpoint(
        schema_version=1,
        batch_id="batch-secret",
        endpoint_alias="private-endpoint",
        file_kind="result",
        file_id="file-secret",
        file_line_number=2,
        batch_line_count=2,
        record_count=1,
        prefix_sha256="a" * 64,
    )


def clock(*values: int | BaseException) -> Callable[[], int]:
    """Return a deterministic monotonic clock with optional failures."""
    remaining = list(values)

    def read() -> int:
        value = remaining.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    return read


def flattened_telemetry(tracer: FakeTracer, meter: FakeMeter) -> str:
    """Render all captured telemetry for secret-leak assertions."""
    parts: list[str] = [repr(tracer.starts), repr(meter.created)]
    for context in tracer.contexts:
        parts.append(repr(context.span.attributes))
        parts.append(repr(context.span.recorded_exceptions))
    parts.append(repr(meter.counter.measurements))
    parts.append(repr(meter.histogram.measurements))
    return " ".join(parts)


def test_successful_load_emits_fixed_low_cardinality_signals() -> None:
    """A successful load emits one safe span, count, and duration measurement."""
    store = FakeCheckpointStore()
    expected = checkpoint()
    store.results["load"] = expected
    tracer = FakeTracer()
    meter = FakeMeter()
    observed = OpenTelemetryCheckpointStore(
        store,
        tracer=tracer,
        meter=meter,
        monotonic_ns=clock(10, 2_000_000_010),
    )

    assert observed.load("worker-secret", "batch-secret", "private-endpoint") == expected
    assert store.calls == [
        (
            "load",
            ("worker-secret", "batch-secret", "private-endpoint"),
            {},
        )
    ]
    assert tracer.starts == [
        (
            "pg_llm_batch.checkpoint.load",
            {
                "db.system.name": "postgresql",
                "pg_llm_batch.checkpoint.operation": "load",
                "pg_llm_batch.checkpoint.transaction_owner": "package",
            },
            False,
            False,
        )
    ]
    assert tracer.contexts[0].span.attributes == {
        "pg_llm_batch.checkpoint.outcome": "success"
    }
    assert meter.counter.measurements == [
        RecordedMeasurement(
            1.0,
            {
                "pg_llm_batch.checkpoint.operation": "load",
                "pg_llm_batch.checkpoint.transaction_owner": "package",
                "pg_llm_batch.checkpoint.outcome": "success",
            },
        )
    ]
    assert meter.histogram.measurements == [
        RecordedMeasurement(
            2.0,
            {
                "pg_llm_batch.checkpoint.operation": "load",
                "pg_llm_batch.checkpoint.transaction_owner": "package",
                "pg_llm_batch.checkpoint.outcome": "success",
            },
        )
    ]
    captured = flattened_telemetry(tracer, meter)
    for secret in (
        "worker-secret",
        "batch-secret",
        "private-endpoint",
        "file-secret",
        "a" * 64,
    ):
        assert secret not in captured


def test_conflict_is_re_raised_without_recording_sensitive_exception_data() -> None:
    """A checkpoint conflict uses a fixed error class and preserves the exception."""
    store = FakeCheckpointStore()
    conflict = CheckpointConflictError(
        "worker-secret",
        "batch-secret",
        "expected_previous_stale",
    )
    store.failures["save"] = conflict
    tracer = FakeTracer()
    meter = FakeMeter()
    observed = OpenTelemetryCheckpointStore(
        store,
        tracer=tracer,
        meter=meter,
        monotonic_ns=clock(0, 500_000_000),
    )

    with pytest.raises(CheckpointConflictError) as raised:
        observed.save("worker-secret", checkpoint())

    assert raised.value is conflict
    assert tracer.contexts[0].span.recorded_exceptions == []
    assert tracer.contexts[0].span.attributes == {
        "pg_llm_batch.checkpoint.outcome": "conflict",
        "error.type": "checkpoint_conflict",
    }
    expected_attributes = {
        "pg_llm_batch.checkpoint.operation": "save",
        "pg_llm_batch.checkpoint.transaction_owner": "package",
        "pg_llm_batch.checkpoint.outcome": "conflict",
        "error.type": "checkpoint_conflict",
    }
    assert meter.counter.measurements == [RecordedMeasurement(1.0, expected_attributes)]
    assert meter.histogram.measurements == [
        RecordedMeasurement(0.5, expected_attributes)
    ]
    captured = flattened_telemetry(tracer, meter)
    assert "worker-secret" not in captured
    assert "batch-secret" not in captured
    assert "expected_previous_stale" not in captured


@pytest.mark.parametrize(
    ("failure", "outcome", "error_type"),
    [
        (
            ValidationError(field="tenant_scope", value="secret", reason="invalid"),
            "validation_error",
            "validation_error",
        ),
        (RuntimeError("provider-secret"), "error", "internal_error"),
    ],
)
def test_failure_classification_is_bounded(
    failure: BaseException,
    outcome: str,
    error_type: str,
) -> None:
    """Validation and internal failures use finite non-secret classifications."""
    store = FakeCheckpointStore()
    store.failures["load"] = failure
    tracer = FakeTracer()
    meter = FakeMeter()
    observed = OpenTelemetryCheckpointStore(
        store,
        tracer=tracer,
        meter=meter,
        monotonic_ns=clock(100, 90),
    )

    with pytest.raises(type(failure)) as raised:
        observed.load("worker-secret", "batch-secret", "private-endpoint")

    assert raised.value is failure
    assert tracer.contexts[0].span.attributes == {
        "pg_llm_batch.checkpoint.outcome": outcome,
        "error.type": error_type,
    }
    assert meter.histogram.measurements[0].value == 0.0
    assert "secret" not in flattened_telemetry(tracer, meter)


def test_transaction_methods_preserve_cursor_and_expected_checkpoint_arguments() -> None:
    """Caller-owned transaction methods delegate unchanged and use caller labels."""
    store = FakeCheckpointStore()
    cursor = object()
    previous = checkpoint()
    candidate = BatchResultCheckpoint(
        schema_version=1,
        batch_id="batch-secret",
        endpoint_alias="private-endpoint",
        file_kind="result",
        file_id="file-secret",
        file_line_number=3,
        batch_line_count=3,
        record_count=2,
        prefix_sha256="b" * 64,
    )
    store.results["load_in_transaction"] = previous
    store.results["save_in_transaction"] = candidate
    tracer = FakeTracer()
    meter = FakeMeter()
    observed = OpenTelemetryCheckpointStore(
        store,
        tracer=tracer,
        meter=meter,
        monotonic_ns=clock(0, 1, 2, 4),
    )

    assert (
        observed.load_in_transaction(
            cursor,
            "worker-secret",
            "batch-secret",
            "private-endpoint",
        )
        == previous
    )
    assert (
        observed.save_in_transaction(
            cursor,
            "worker-secret",
            candidate,
            expected_previous=previous,
        )
        == candidate
    )
    assert store.calls == [
        (
            "load_in_transaction",
            (cursor, "worker-secret", "batch-secret", "private-endpoint"),
            {},
        ),
        (
            "save_in_transaction",
            (cursor, "worker-secret", candidate),
            {"expected_previous": previous},
        ),
    ]
    assert [start[0] for start in tracer.starts] == [
        "pg_llm_batch.checkpoint.load",
        "pg_llm_batch.checkpoint.save",
    ]
    assert all(
        measurement.attributes["pg_llm_batch.checkpoint.transaction_owner"]
        == "caller"
        for measurement in meter.counter.measurements
    )


@pytest.mark.parametrize(
    "tracer",
    [
        FakeTracer(start_failure=RuntimeError("telemetry-secret")),
        FakeTracer(enter_failure=RuntimeError("telemetry-secret")),
        FakeTracer(exit_failure=RuntimeError("telemetry-secret")),
        FakeTracer(set_failure=RuntimeError("telemetry-secret")),
    ],
)
def test_trace_failures_never_change_checkpoint_success(tracer: FakeTracer) -> None:
    """Tracing failures are isolated from the durable checkpoint operation."""
    store = FakeCheckpointStore()
    expected = checkpoint()
    store.results["load"] = expected
    meter = FakeMeter()
    observed = OpenTelemetryCheckpointStore(
        store,
        tracer=tracer,
        meter=meter,
        monotonic_ns=clock(0, 1),
    )

    assert observed.load("worker-secret", "batch-secret", "private-endpoint") == expected
    assert store.calls[0][0] == "load"


@pytest.mark.parametrize(
    "meter",
    [
        FakeMeter(create_failure=RuntimeError("telemetry-secret")),
        FakeMeter(measurement_failure=RuntimeError("telemetry-secret")),
    ],
)
def test_metric_failures_never_change_checkpoint_success(meter: FakeMeter) -> None:
    """Metric creation and export failures remain best-effort observability."""
    store = FakeCheckpointStore()
    expected = checkpoint()
    store.results["save"] = expected
    observed = OpenTelemetryCheckpointStore(
        store,
        tracer=FakeTracer(),
        meter=meter,
        monotonic_ns=clock(0, 1),
    )

    assert observed.save("worker-secret", expected) == expected
    assert store.calls[0][0] == "save"


def test_telemetry_and_clock_failures_never_mask_checkpoint_failure() -> None:
    """The original application exception survives every observer-side failure."""
    store = FakeCheckpointStore()
    failure = RuntimeError("application-secret")
    store.failures["load"] = failure
    observed = OpenTelemetryCheckpointStore(
        store,
        tracer=FakeTracer(exit_failure=RuntimeError("telemetry-secret")),
        meter=FakeMeter(measurement_failure=RuntimeError("telemetry-secret")),
        monotonic_ns=clock(RuntimeError("clock-secret"), RuntimeError("clock-secret")),
    )

    with pytest.raises(RuntimeError) as raised:
        observed.load("worker-secret", "batch-secret", "private-endpoint")

    assert raised.value is failure
