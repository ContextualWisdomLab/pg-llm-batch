# SPDX-License-Identifier: Apache-2.0
"""Regression tests for the checkpoint telemetry exception boundary."""

from asyncio import CancelledError
from typing import Any

import pytest

from pg_llm_batch.checkpoint_telemetry import OpenTelemetryCheckpointStore


class CapturingSpan:
    """Accept bounded span attributes."""

    def set_attribute(self, _name: str, _value: str) -> None:
        """Accept one package-owned attribute."""
        return None


class CapturingContext:
    """Capture arguments supplied when the span context closes."""

    def __init__(self, *, exit_failure: BaseException | None = None) -> None:
        self.exit_failure = exit_failure
        self.exit_arguments: list[tuple[Any, Any, Any]] = []

    def __enter__(self) -> CapturingSpan:
        """Enter one deterministic span context."""
        return CapturingSpan()

    def __exit__(self, *exc: Any) -> bool:
        """Capture close arguments and optionally raise observer cancellation."""
        self.exit_arguments.append(exc)
        if self.exit_failure is not None:
            raise self.exit_failure
        return False


class CapturingTracer:
    """Return one context without interpreting operation exceptions."""

    def __init__(self, context: CapturingContext) -> None:
        self.context = context

    def start_as_current_span(self, *_args: Any, **_kwargs: Any) -> CapturingContext:
        """Start the configured span context."""
        return self.context


class CancellingMeter:
    """Raise task cancellation from instrument creation."""

    def create_counter(self, *_args: Any, **_kwargs: Any) -> Any:
        """Cancel counter creation."""
        raise CancelledError()

    def create_histogram(self, *_args: Any, **_kwargs: Any) -> Any:
        """Cancel histogram creation."""
        raise CancelledError()


class NoOpMeter:
    """Provide instruments that accept metrics."""

    def create_counter(self, *_args: Any, **_kwargs: Any) -> "NoOpMeter":
        """Return this object as a counter."""
        return self

    def create_histogram(self, *_args: Any, **_kwargs: Any) -> "NoOpMeter":
        """Return this object as a histogram."""
        return self

    def add(self, *_args: Any, **_kwargs: Any) -> None:
        """Accept one counter measurement."""
        return None

    def record(self, *_args: Any, **_kwargs: Any) -> None:
        """Accept one histogram measurement."""
        return None


class FailingStore:
    """Raise one application exception from a checkpoint load."""

    def __init__(self, failure: BaseException) -> None:
        self.failure = failure

    def load(self, *_args: Any, **_kwargs: Any) -> Any:
        """Raise the configured application failure."""
        raise self.failure


class SuccessfulStore:
    """Return one deterministic application result."""

    def load(self, *_args: Any, **_kwargs: Any) -> str:
        """Return the durable checkpoint sentinel."""
        return "durable-result"


def test_application_exception_is_not_passed_to_span_context_exit() -> None:
    """Observers never receive the application exception on context close."""
    context = CapturingContext()
    failure = RuntimeError("application-state")
    observed = OpenTelemetryCheckpointStore(
        FailingStore(failure),
        tracer=CapturingTracer(context),
        meter=NoOpMeter(),
        monotonic_ns=lambda: 0,
    )

    with pytest.raises(RuntimeError) as raised:
        observed.load("consumer-a", "batch-a", "endpoint-a")

    assert raised.value is failure
    assert context.exit_arguments == [(None, None, None)]


def test_observer_cancellation_does_not_cancel_successful_checkpoint_operation() -> None:
    """Telemetry cancellation is isolated like other observer failure."""
    context = CapturingContext(exit_failure=CancelledError())
    observed = OpenTelemetryCheckpointStore(
        SuccessfulStore(),
        tracer=CapturingTracer(context),
        meter=CancellingMeter(),
        monotonic_ns=lambda: 0,
    )

    assert observed.load("consumer-a", "batch-a", "endpoint-a") == "durable-result"
    assert context.exit_arguments == [(None, None, None)]
