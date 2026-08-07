# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Best-effort OpenTelemetry-compatible signals for durable checkpoints."""

from __future__ import annotations

import math
import time
from asyncio import CancelledError
from typing import Any, Callable, Optional, TypeVar

from .checkpoint_store import CheckpointConflictError
from .exceptions import ValidationError
from .result_streaming import BatchResultCheckpoint

_OPERATION_COUNT_NAME = "pg_llm_batch.checkpoint.operation.count"
_OPERATION_DURATION_NAME = "pg_llm_batch.checkpoint.operation.duration"
_OPERATION_ATTRIBUTE = "pg_llm_batch.checkpoint.operation"
_TRANSACTION_OWNER_ATTRIBUTE = "pg_llm_batch.checkpoint.transaction_owner"
_OUTCOME_ATTRIBUTE = "pg_llm_batch.checkpoint.outcome"
_ERROR_TYPE_ATTRIBUTE = "error.type"
_TELEMETRY_FAILURES = (Exception, CancelledError)

_ResultT = TypeVar("_ResultT")


class _NoOpInstrument:
    """Ignore one metric operation after instrumentation becomes unavailable."""

    def add(self, _value: int, *, attributes: dict[str, str]) -> None:
        """Ignore one counter measurement."""
        del attributes

    def record(self, _value: float, *, attributes: dict[str, str]) -> None:
        """Ignore one histogram measurement."""
        del attributes


class _NoOpSpan:
    """Ignore span mutation after tracing becomes unavailable."""

    def set_attribute(self, _name: str, _value: str) -> None:
        """Ignore one span attribute."""
        return None


_NO_OP_INSTRUMENT = _NoOpInstrument()
_NO_OP_SPAN = _NoOpSpan()


class _SafeSpanScope:
    """Contain ordinary tracer failures without altering application behavior."""

    def __init__(
        self,
        tracer: Any,
        name: str,
        attributes: dict[str, str],
    ) -> None:
        """Store one injected tracer and a bounded initial attribute set."""
        self._tracer = tracer
        self._name = name
        self._attributes = attributes
        self._context: Any = None
        self._span: Any = _NO_OP_SPAN

    def __enter__(self) -> Any:
        """Start one span or degrade to a no-op span on telemetry failure."""
        try:
            context = self._tracer.start_as_current_span(
                self._name,
                attributes=dict(self._attributes),
                record_exception=False,
                set_status_on_exception=False,
            )
            span = context.__enter__()
        except _TELEMETRY_FAILURES:
            self._context = None
            self._span = _NO_OP_SPAN
        else:
            self._context = context
            self._span = span
        return self._span

    def __exit__(self, *_exc: Any) -> bool:
        """End one span without handing application exceptions to observers."""
        if self._context is not None:
            try:
                self._context.__exit__(None, None, None)
            except _TELEMETRY_FAILURES:
                pass
        return False


def _create_counter(meter: Any) -> Any:
    """Create the bounded operation counter or return a no-op instrument."""
    try:
        return meter.create_counter(
            _OPERATION_COUNT_NAME,
            unit="{operation}",
            description="Completed durable checkpoint operations by bounded outcome.",
        )
    except _TELEMETRY_FAILURES:
        return _NO_OP_INSTRUMENT


def _create_histogram(meter: Any) -> Any:
    """Create the duration histogram or return a no-op instrument."""
    try:
        return meter.create_histogram(
            _OPERATION_DURATION_NAME,
            unit="s",
            description="Duration of durable checkpoint operations.",
        )
    except _TELEMETRY_FAILURES:
        return _NO_OP_INSTRUMENT


def _read_clock(clock: Callable[[], Any]) -> Any:
    """Read a monotonic clock without making telemetry a business dependency."""
    try:
        return clock()
    except _TELEMETRY_FAILURES:
        return None


def _duration_seconds(start_ns: Any, end_ns: Any) -> float:
    """Return a finite nonnegative duration or zero for invalid clock evidence."""
    if start_ns is None or end_ns is None:
        return 0.0
    try:
        duration = (end_ns - start_ns) / 1_000_000_000
        if not math.isfinite(duration):
            return 0.0
        return max(0.0, float(duration))
    except _TELEMETRY_FAILURES:
        return 0.0


def _resolve_error_status() -> Any:
    """Resolve OpenTelemetry ``StatusCode.ERROR`` without adding a dependency."""
    try:
        from opentelemetry.trace import StatusCode
    except _TELEMETRY_FAILURES:
        return None
    return StatusCode.ERROR


def _classify_failure(error: BaseException) -> tuple[str, str]:
    """Map one failure to a finite low-cardinality telemetry classification."""
    if isinstance(error, CheckpointConflictError):
        return "conflict", "checkpoint_conflict"
    if isinstance(error, ValidationError):
        return "validation_error", "validation_error"
    return "error", "internal_error"


def _safe_set_attribute(span: Any, name: str, value: str) -> None:
    """Set one bounded span attribute without exposing exporter availability."""
    try:
        span.set_attribute(name, value)
    except _TELEMETRY_FAILURES:
        pass


def _safe_set_status(span: Any, status: Any) -> None:
    """Set one host API status without making tracing an application dependency."""
    if status is None:
        return
    try:
        span.set_status(status)
    except _TELEMETRY_FAILURES:
        pass


def _safe_add(counter: Any, attributes: dict[str, str]) -> None:
    """Record one completed operation without making metrics authoritative."""
    try:
        counter.add(1, attributes=dict(attributes))
    except _TELEMETRY_FAILURES:
        pass


def _safe_record(
    histogram: Any,
    duration_seconds: float,
    attributes: dict[str, str],
) -> None:
    """Record one duration without making metrics authoritative."""
    try:
        histogram.record(duration_seconds, attributes=dict(attributes))
    except _TELEMETRY_FAILURES:
        pass


class OpenTelemetryCheckpointStore:
    """Wrap a durable checkpoint store with confidential best-effort telemetry.

    The injected ``tracer`` and ``meter`` use the stable OpenTelemetry API call
    shapes, but this package does not require or configure an SDK or exporter.
    Hosts retain ownership of providers, sampling, export, and resource metadata.
    Checkpoint tenant, consumer, batch, endpoint, file, digest, cursor, and DSN
    values are never added to package-owned telemetry. Package operation spans
    are storage-agnostic and do not claim database-client semantic attributes;
    database instrumentation remains the embedding host's responsibility.
    """

    def __init__(
        self,
        store: Any,
        *,
        tracer: Any,
        meter: Any,
        monotonic_ns: Callable[[], Any] = time.monotonic_ns,
    ) -> None:
        """Bind one store and host-owned OpenTelemetry-compatible instruments."""
        self._store = store
        self._tracer = tracer
        self._counter = _create_counter(meter)
        self._histogram = _create_histogram(meter)
        self._monotonic_ns = monotonic_ns
        self._error_status = _resolve_error_status()

    def _execute(
        self,
        operation: str,
        transaction_owner: str,
        callback: Callable[[], _ResultT],
    ) -> _ResultT:
        """Run one checkpoint operation while containing telemetry failures."""
        span_attributes = {
            _OPERATION_ATTRIBUTE: operation,
            _TRANSACTION_OWNER_ATTRIBUTE: transaction_owner,
        }
        metric_attributes = {
            _OPERATION_ATTRIBUTE: operation,
            _TRANSACTION_OWNER_ATTRIBUTE: transaction_owner,
        }
        start_ns = _read_clock(self._monotonic_ns)
        with _SafeSpanScope(
            self._tracer,
            f"pg_llm_batch.checkpoint.{operation}",
            span_attributes,
        ) as span:
            try:
                result = callback()
            except BaseException as error:
                outcome, error_type = _classify_failure(error)
                metric_attributes[_OUTCOME_ATTRIBUTE] = outcome
                metric_attributes[_ERROR_TYPE_ATTRIBUTE] = error_type
                _safe_set_attribute(span, _OUTCOME_ATTRIBUTE, outcome)
                _safe_set_attribute(span, _ERROR_TYPE_ATTRIBUTE, error_type)
                _safe_set_status(span, self._error_status)
                _safe_add(self._counter, metric_attributes)
                _safe_record(
                    self._histogram,
                    _duration_seconds(
                        start_ns,
                        _read_clock(self._monotonic_ns),
                    ),
                    metric_attributes,
                )
                raise
            metric_attributes[_OUTCOME_ATTRIBUTE] = "success"
            _safe_set_attribute(span, _OUTCOME_ATTRIBUTE, "success")
            _safe_add(self._counter, metric_attributes)
            _safe_record(
                self._histogram,
                _duration_seconds(start_ns, _read_clock(self._monotonic_ns)),
                metric_attributes,
            )
            return result

    def load(
        self,
        consumer_name: str,
        batch_id: str,
        endpoint_alias: str,
    ) -> Optional[BatchResultCheckpoint]:
        """Load one checkpoint and emit package-owned operation telemetry."""
        return self._execute(
            "load",
            "package",
            lambda: self._store.load(consumer_name, batch_id, endpoint_alias),
        )

    def load_in_transaction(
        self,
        cursor: Any,
        consumer_name: str,
        batch_id: str,
        endpoint_alias: str,
    ) -> Optional[BatchResultCheckpoint]:
        """Load through a caller transaction without changing its ownership."""
        return self._execute(
            "load",
            "caller",
            lambda: self._store.load_in_transaction(
                cursor,
                consumer_name,
                batch_id,
                endpoint_alias,
            ),
        )

    def save(
        self,
        consumer_name: str,
        checkpoint: BatchResultCheckpoint,
        *,
        expected_previous: Optional[BatchResultCheckpoint] = None,
    ) -> BatchResultCheckpoint:
        """Save one checkpoint and emit package-owned operation telemetry."""
        return self._execute(
            "save",
            "package",
            lambda: self._store.save(
                consumer_name,
                checkpoint,
                expected_previous=expected_previous,
            ),
        )

    def save_in_transaction(
        self,
        cursor: Any,
        consumer_name: str,
        checkpoint: BatchResultCheckpoint,
        *,
        expected_previous: Optional[BatchResultCheckpoint] = None,
    ) -> BatchResultCheckpoint:
        """Save through a caller transaction without changing its ownership."""
        return self._execute(
            "save",
            "caller",
            lambda: self._store.save_in_transaction(
                cursor,
                consumer_name,
                checkpoint,
                expected_previous=expected_previous,
            ),
        )
