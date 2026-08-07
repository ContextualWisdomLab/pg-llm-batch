# SPDX-License-Identifier: Apache-2.0
"""Concurrency tests for durable checkpoint telemetry."""

from concurrent.futures import ThreadPoolExecutor
from threading import Lock
from typing import Any

from pg_llm_batch.checkpoint_telemetry import OpenTelemetryCheckpointStore


class ConcurrentSpan:
    """Collect attributes local to one concurrent operation."""

    def __init__(self, initial: dict[str, str]) -> None:
        self.attributes = dict(initial)

    def set_attribute(self, name: str, value: str) -> None:
        """Set one operation-local attribute."""
        self.attributes[name] = value


class ConcurrentSpanContext:
    """Own one operation-local span."""

    def __init__(self, span: ConcurrentSpan, completed: list[dict[str, str]], lock: Lock) -> None:
        self.span = span
        self.completed = completed
        self.lock = lock

    def __enter__(self) -> ConcurrentSpan:
        """Enter the operation-local span."""
        return self.span

    def __exit__(self, *_exc: Any) -> bool:
        """Publish one completed immutable attribute snapshot."""
        with self.lock:
            self.completed.append(dict(self.span.attributes))
        return False


class ConcurrentTracer:
    """Create independent spans for concurrent calls."""

    def __init__(self) -> None:
        self.completed: list[dict[str, str]] = []
        self.lock = Lock()

    def start_as_current_span(
        self,
        _name: str,
        *,
        attributes: dict[str, str],
        **_kwargs: Any,
    ) -> ConcurrentSpanContext:
        """Create one operation-local context from a copied initial mapping."""
        return ConcurrentSpanContext(
            ConcurrentSpan(attributes),
            self.completed,
            self.lock,
        )


class ConcurrentInstrument:
    """Collect copied metric attributes safely across threads."""

    def __init__(self) -> None:
        self.measurements: list[dict[str, str]] = []
        self.lock = Lock()

    def add(self, _value: int, *, attributes: dict[str, str]) -> None:
        """Record one counter mapping."""
        with self.lock:
            self.measurements.append(dict(attributes))

    def record(self, _value: float, *, attributes: dict[str, str]) -> None:
        """Record one histogram mapping."""
        with self.lock:
            self.measurements.append(dict(attributes))


class ConcurrentMeter:
    """Provide independent counter and histogram collectors."""

    def __init__(self) -> None:
        self.counter = ConcurrentInstrument()
        self.histogram = ConcurrentInstrument()

    def create_counter(self, *_args: Any, **_kwargs: Any) -> ConcurrentInstrument:
        """Return the shared thread-safe counter."""
        return self.counter

    def create_histogram(self, *_args: Any, **_kwargs: Any) -> ConcurrentInstrument:
        """Return the shared thread-safe histogram."""
        return self.histogram


class ConcurrentStore:
    """Count delegated loads and saves safely across threads."""

    def __init__(self) -> None:
        self.calls: list[str] = []
        self.lock = Lock()

    def load(self, *_args: Any, **_kwargs: Any) -> str:
        """Record and return one load result."""
        with self.lock:
            self.calls.append("load")
        return "loaded"

    def save(self, *_args: Any, **_kwargs: Any) -> str:
        """Record and return one save result."""
        with self.lock:
            self.calls.append("save")
        return "saved"


def test_concurrent_operations_do_not_share_mutable_telemetry_attributes() -> None:
    """Concurrent load and save signals retain independent finite attributes."""
    store = ConcurrentStore()
    tracer = ConcurrentTracer()
    meter = ConcurrentMeter()
    clock_lock = Lock()
    clock_value = 0

    def clock() -> int:
        nonlocal clock_value
        with clock_lock:
            clock_value += 1
            return clock_value

    observed = OpenTelemetryCheckpointStore(
        store,
        tracer=tracer,
        meter=meter,
        monotonic_ns=clock,
    )

    def invoke(index: int) -> str:
        if index % 2 == 0:
            return observed.load("consumer-a", "batch-a", "endpoint-a")
        return observed.save("consumer-a", object())

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(invoke, range(32)))

    assert results.count("loaded") == 16
    assert results.count("saved") == 16
    assert store.calls.count("load") == 16
    assert store.calls.count("save") == 16
    assert len(tracer.completed) == 32
    assert len(meter.counter.measurements) == 32
    assert len(meter.histogram.measurements) == 32

    expected_attributes = {
        "pg_llm_batch.checkpoint.operation",
        "pg_llm_batch.checkpoint.transaction_owner",
        "pg_llm_batch.checkpoint.outcome",
    }
    for measurement in meter.counter.measurements + meter.histogram.measurements:
        assert measurement["pg_llm_batch.checkpoint.operation"] in {"load", "save"}
        assert measurement["pg_llm_batch.checkpoint.transaction_owner"] == "package"
        assert measurement["pg_llm_batch.checkpoint.outcome"] == "success"
        assert "error.type" not in measurement
        assert "db.system.name" not in measurement
        assert set(measurement) == expected_attributes

    for attributes in tracer.completed:
        assert attributes["pg_llm_batch.checkpoint.operation"] in {"load", "save"}
        assert attributes["pg_llm_batch.checkpoint.transaction_owner"] == "package"
        assert attributes["pg_llm_batch.checkpoint.outcome"] == "success"
        assert "error.type" not in attributes
        assert "db.system.name" not in attributes
        assert set(attributes) == expected_attributes