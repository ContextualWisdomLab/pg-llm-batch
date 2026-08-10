# SPDX-License-Identifier: Apache-2.0
"""Regression tests for confidential OpenTelemetry operation span status."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from pg_llm_batch import observability
from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.exceptions import GatewayError


@dataclass
class _Span:
    """Capture bounded span attributes and status mutations."""

    attributes: dict[str, Any] = field(default_factory=dict)
    statuses: list[Any] = field(default_factory=list)

    def set_attribute(self, name: str, value: Any) -> None:
        """Record one bounded span attribute."""
        self.attributes[name] = value

    def set_status(self, status: Any) -> None:
        """Record one status object without accepting a description."""
        self.statuses.append(status)


class _ExplodingStatusSpan(_Span):
    """Model an injected span whose status mutation fails."""

    def set_status(self, status: Any) -> None:
        """Reject status mutation without retaining the supplied object."""
        del status
        raise RuntimeError("telemetry status sink unavailable")


class _SpanContext:
    """Expose one deterministic span through the tracer context contract."""

    def __init__(self, span: _Span) -> None:
        self._span = span

    def __enter__(self) -> _Span:
        """Return the configured span."""
        return self._span

    def __exit__(self, *_exc: Any) -> None:
        """Close without observing application exceptions."""
        return None


class _Tracer:
    """Create exactly one inspectable span."""

    def __init__(self, span: _Span | None = None) -> None:
        self.span = span if span is not None else _Span()

    def start_as_current_span(self, _name: str, **_kwargs: Any) -> _SpanContext:
        """Return the deterministic span context."""
        return _SpanContext(self.span)


class _Instrument:
    """Accept metrics so the regression isolates trace status behavior."""

    def add(self, _value: int, *, attributes: dict[str, str]) -> None:
        """Accept one counter measurement."""
        del attributes

    def record(self, _value: float, *, attributes: dict[str, str]) -> None:
        """Accept one duration measurement."""
        del attributes


class _Meter:
    """Return no-op-compatible deterministic metric instruments."""

    def create_counter(self, _name: str, **_kwargs: Any) -> _Instrument:
        """Return one counter double."""
        return _Instrument()

    def create_histogram(self, _name: str, **_kwargs: Any) -> _Instrument:
        """Return one histogram double."""
        return _Instrument()


def _credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic provider credentials for the isolated operation."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


def _status_module(error_code: Any, error_status: Any) -> type[Any]:
    """Build a tiny OpenTelemetry trace-status API double."""

    class _TraceModule:
        """Expose only the OpenTelemetry status API needed by the client."""

        class StatusCode:
            """Provide the stable Error code used by OpenTelemetry Python."""

            ERROR = error_code

        @staticmethod
        def Status(code: Any) -> Any:
            """Construct one status object from the exact Error code."""
            assert code is error_code
            return error_status

    return _TraceModule


async def test_failed_operation_sets_error_status_without_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A propagated failure marks the span Error without exporting its message."""
    error_code = object()
    error_status = object()
    trace_module = _status_module(error_code, error_status)

    def _import_module(name: str) -> Any:
        assert name == "opentelemetry.trace"
        return trace_module

    failure = GatewayError("provider secret should stay private")

    async def _fail(
        _self: BatchAPIClient,
        _batch_id: str,
        _endpoint_alias: str,
    ) -> dict[str, Any]:
        raise failure

    monkeypatch.setattr(observability, "import_module", _import_module)
    monkeypatch.setattr(BatchAPIClient, "cancel_batch", _fail)
    tracer = _Tracer()
    client = observability.OpenTelemetryBatchAPIClient(
        "postgresql://example",
        _credentials,
        tracer=tracer,
        meter=_Meter(),
    )

    with pytest.raises(GatewayError) as exc_info:
        await client.cancel_batch("batch-1", "private-alias")

    assert exc_info.value is failure
    assert tracer.span.statuses == [error_status]
    assert tracer.span.attributes == {
        "pg_llm_batch.operation.name": "cancel_batch",
        "error.type": "GatewayError",
    }
    assert "provider secret should stay private" not in repr(
        (tracer.span.statuses, tracer.span.attributes)
    )


async def test_successful_operation_leaves_span_status_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Success keeps the OpenTelemetry default status and avoids status imports."""
    expected = {"cancelled": True}

    async def _succeed(
        _self: BatchAPIClient,
        _batch_id: str,
        _endpoint_alias: str,
    ) -> dict[str, Any]:
        return expected

    def _unexpected_import(name: str) -> Any:
        raise AssertionError(f"successful operation imported {name}")

    monkeypatch.setattr(observability, "import_module", _unexpected_import)
    monkeypatch.setattr(BatchAPIClient, "cancel_batch", _succeed)
    tracer = _Tracer()
    client = observability.OpenTelemetryBatchAPIClient(
        "postgresql://example",
        _credentials,
        tracer=tracer,
        meter=_Meter(),
    )

    result = await client.cancel_batch("batch-1", "default")

    assert result is expected
    assert tracer.span.statuses == []


async def test_status_mutation_failure_does_not_mask_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A broken telemetry status sink cannot replace the application exception."""
    error_code = object()
    error_status = object()
    trace_module = _status_module(error_code, error_status)

    def _import_module(name: str) -> Any:
        assert name == "opentelemetry.trace"
        return trace_module

    failure = GatewayError("provider failure remains authoritative")

    async def _fail(
        _self: BatchAPIClient,
        _batch_id: str,
        _endpoint_alias: str,
    ) -> dict[str, Any]:
        raise failure

    monkeypatch.setattr(observability, "import_module", _import_module)
    monkeypatch.setattr(BatchAPIClient, "cancel_batch", _fail)
    tracer = _Tracer(_ExplodingStatusSpan())
    client = observability.OpenTelemetryBatchAPIClient(
        "postgresql://example",
        _credentials,
        tracer=tracer,
        meter=_Meter(),
    )

    with pytest.raises(GatewayError) as exc_info:
        await client.cancel_batch("batch-1", "default")

    assert exc_info.value is failure
    assert tracer.span.attributes == {
        "pg_llm_batch.operation.name": "cancel_batch",
        "error.type": "GatewayError",
    }
    assert "telemetry status sink unavailable" not in str(exc_info.value)


async def test_missing_optional_status_api_does_not_mask_provider_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Optional trace API absence leaves the original provider failure intact."""
    failure = GatewayError("provider failure remains authoritative")

    async def _fail(
        _self: BatchAPIClient,
        _batch_id: str,
        _endpoint_alias: str,
    ) -> dict[str, Any]:
        raise failure

    def _missing_trace_api(name: str) -> Any:
        assert name == "opentelemetry.trace"
        raise ModuleNotFoundError("opentelemetry.trace")

    monkeypatch.setattr(observability, "import_module", _missing_trace_api)
    monkeypatch.setattr(BatchAPIClient, "cancel_batch", _fail)
    tracer = _Tracer()
    client = observability.OpenTelemetryBatchAPIClient(
        "postgresql://example",
        _credentials,
        tracer=tracer,
        meter=_Meter(),
    )

    with pytest.raises(GatewayError) as exc_info:
        await client.cancel_batch("batch-1", "default")

    assert exc_info.value is failure
    assert tracer.span.statuses == []
