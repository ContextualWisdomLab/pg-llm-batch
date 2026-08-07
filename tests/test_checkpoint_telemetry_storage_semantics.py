# SPDX-License-Identifier: Apache-2.0
"""Regression tests for storage-agnostic checkpoint telemetry semantics."""

from __future__ import annotations

from typing import Any

from pg_llm_batch.checkpoint_telemetry import OpenTelemetryCheckpointStore


class _Instrument:
    """Accept metric measurements without retaining application values."""

    def add(self, _value: int, *, attributes: dict[str, str]) -> None:
        """Accept one counter measurement."""
        assert "db.system.name" not in attributes

    def record(self, _value: float, *, attributes: dict[str, str]) -> None:
        """Accept one histogram measurement."""
        assert "db.system.name" not in attributes


class _Meter:
    """Provide no-op metric instruments using the OpenTelemetry API shape."""

    def create_counter(self, _name: str, *, unit: str, description: str) -> _Instrument:
        """Create one counter after validating bounded metadata."""
        assert unit == "{operation}"
        assert description
        return _Instrument()

    def create_histogram(
        self,
        _name: str,
        *,
        unit: str,
        description: str,
    ) -> _Instrument:
        """Create one histogram after validating bounded metadata."""
        assert unit == "s"
        assert description
        return _Instrument()


class _Span:
    """Accept bounded span mutation."""

    def set_attribute(self, name: str, _value: str) -> None:
        """Reject accidental database-client semantic claims."""
        assert name != "db.system.name"


class _SpanContext:
    """Provide one deterministic context manager around a fake span."""

    def __enter__(self) -> _Span:
        """Enter the fake span."""
        return _Span()

    def __exit__(self, *_exc: Any) -> bool:
        """Exit without suppressing application exceptions."""
        return False


class _Tracer:
    """Capture the initial attributes of one package operation span."""

    def __init__(self) -> None:
        """Initialize an empty start record."""
        self.starts: list[tuple[str, dict[str, str], bool, bool]] = []

    def start_as_current_span(
        self,
        name: str,
        *,
        attributes: dict[str, str],
        record_exception: bool,
        set_status_on_exception: bool,
    ) -> _SpanContext:
        """Record one span request using the dependency-injected API shape."""
        self.starts.append(
            (
                name,
                dict(attributes),
                record_exception,
                set_status_on_exception,
            )
        )
        return _SpanContext()


class _CompatibleStore:
    """Model a non-PostgreSQL host store that implements the public load seam."""

    def load(self, _consumer_name: str, _batch_id: str, _endpoint_alias: str) -> None:
        """Return an empty checkpoint without exposing a database technology."""
        return None


def test_operation_span_is_storage_agnostic_for_compatible_host_store() -> None:
    """A compatible host store must not be mislabeled as a PostgreSQL client span."""
    tracer = _Tracer()
    observed = OpenTelemetryCheckpointStore(
        _CompatibleStore(),
        tracer=tracer,
        meter=_Meter(),
        monotonic_ns=lambda: 0,
    )

    assert observed.load("consumer", "batch", "endpoint") is None
    assert tracer.starts == [
        (
            "pg_llm_batch.checkpoint.load",
            {
                "pg_llm_batch.checkpoint.operation": "load",
                "pg_llm_batch.checkpoint.transaction_owner": "package",
            },
            False,
            False,
        )
    ]
