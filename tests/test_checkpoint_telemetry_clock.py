# SPDX-License-Identifier: Apache-2.0
"""Clock-failure coverage for durable checkpoint telemetry."""

from typing import Any

from pg_llm_batch.checkpoint_telemetry import OpenTelemetryCheckpointStore


class Span:
    """Accept bounded attributes."""

    def set_attribute(self, _name: str, _value: str) -> None:
        """Accept one attribute."""
        return None


class SpanContext:
    """Provide one no-op span context."""

    def __enter__(self) -> Span:
        """Enter the context."""
        return Span()

    def __exit__(self, *_exc: Any) -> bool:
        """Exit without suppressing application behavior."""
        return False


class Tracer:
    """Create one no-op span context."""

    def start_as_current_span(self, *_args: Any, **_kwargs: Any) -> SpanContext:
        """Start a no-op span."""
        return SpanContext()


class Instrument:
    """Capture histogram values while accepting counter calls."""

    def __init__(self) -> None:
        self.values: list[float] = []

    def add(self, _value: int, *, attributes: dict[str, str]) -> None:
        """Accept one counter value."""
        del attributes

    def record(self, value: float, *, attributes: dict[str, str]) -> None:
        """Capture one duration value."""
        del attributes
        self.values.append(value)


class Meter:
    """Return deterministic instruments."""

    def __init__(self) -> None:
        self.counter = Instrument()
        self.histogram = Instrument()

    def create_counter(self, *_args: Any, **_kwargs: Any) -> Instrument:
        """Return the counter."""
        return self.counter

    def create_histogram(self, *_args: Any, **_kwargs: Any) -> Instrument:
        """Return the histogram."""
        return self.histogram


class Store:
    """Return one successful checkpoint sentinel."""

    def load(self, *_args: Any, **_kwargs: Any) -> str:
        """Return the sentinel."""
        return "checkpoint"


def test_end_clock_failure_records_zero_duration() -> None:
    """A failed end-clock read remains a zero-duration observer signal."""
    readings: list[int | BaseException] = [1, RuntimeError("clock unavailable")]

    def clock() -> int:
        value = readings.pop(0)
        if isinstance(value, BaseException):
            raise value
        return value

    meter = Meter()
    observed = OpenTelemetryCheckpointStore(
        Store(),
        tracer=Tracer(),
        meter=meter,
        monotonic_ns=clock,
    )

    assert observed.load("consumer-a", "batch-a", "endpoint-a") == "checkpoint"
    assert meter.histogram.values == [0.0]
