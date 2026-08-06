# SPDX-License-Identifier: Apache-2.0
"""Regression tests for OpenTelemetry checkpoint span error status."""

from __future__ import annotations

import builtins
import sys
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

import pg_llm_batch.checkpoint_telemetry as telemetry


_ERROR_STATUS = object()


class _StatusCode:
    """Provide the minimum OpenTelemetry StatusCode shape used by the wrapper."""

    ERROR = _ERROR_STATUS


class _Instrument:
    """Accept bounded counter and histogram measurements."""

    def add(self, _value: int, *, attributes: dict[str, str]) -> None:
        """Accept one counter measurement."""
        del attributes

    def record(self, _value: float, *, attributes: dict[str, str]) -> None:
        """Accept one histogram measurement."""
        del attributes


class _Meter:
    """Create no-op metric instruments with the expected API shape."""

    def create_counter(self, _name: str, **_kwargs: Any) -> _Instrument:
        """Create one counter."""
        return _Instrument()

    def create_histogram(self, _name: str, **_kwargs: Any) -> _Instrument:
        """Create one histogram."""
        return _Instrument()


class _Span:
    """Capture bounded attributes and explicit span status calls."""

    def __init__(self, *, status_failure: BaseException | None = None) -> None:
        self.attributes: dict[str, str] = {}
        self.statuses: list[Any] = []
        self.status_failure = status_failure

    def set_attribute(self, name: str, value: str) -> None:
        """Capture one span attribute."""
        self.attributes[name] = value

    def set_status(self, status: Any) -> None:
        """Capture one status value or simulate observer failure."""
        self.statuses.append(status)
        if self.status_failure is not None:
            raise self.status_failure


class _SpanContext:
    """Own one span without receiving the application exception."""

    def __init__(self, span: _Span) -> None:
        self.span = span
        self.exits: list[tuple[Any, Any, Any]] = []

    def __enter__(self) -> _Span:
        """Enter the fake span."""
        return self.span

    def __exit__(self, *exc: Any) -> bool:
        """Capture the sanitized context-manager exit tuple."""
        self.exits.append(exc)
        return False


class _Tracer:
    """Create one status-aware span per checkpoint operation."""

    def __init__(self, *, status_failure: BaseException | None = None) -> None:
        self.status_failure = status_failure
        self.contexts: list[_SpanContext] = []

    def start_as_current_span(self, _name: str, **_kwargs: Any) -> _SpanContext:
        """Create one context with automatic exception handling disabled upstream."""
        context = _SpanContext(_Span(status_failure=self.status_failure))
        self.contexts.append(context)
        return context


class _Store:
    """Provide one deterministic load result or failure."""

    def __init__(self, *, failure: BaseException | None = None) -> None:
        self.failure = failure
        self.result = object()

    def load(self, *_args: Any, **_kwargs: Any) -> Any:
        """Return one result or raise the exact configured application failure."""
        if self.failure is not None:
            raise self.failure
        return self.result


def _install_fake_otel(monkeypatch: pytest.MonkeyPatch) -> None:
    """Install only the OpenTelemetry API symbol needed for explicit Error status."""
    package = ModuleType("opentelemetry")
    trace_module = ModuleType("opentelemetry.trace")
    trace_module.StatusCode = _StatusCode
    package.trace = trace_module
    monkeypatch.setitem(sys.modules, "opentelemetry", package)
    monkeypatch.setitem(sys.modules, "opentelemetry.trace", trace_module)


def _normalized(path: str) -> str:
    """Normalize Markdown layout while preserving semantic documentation text."""
    return " ".join(Path(path).read_text(encoding="utf-8").split())


def test_failed_operation_sets_error_status_without_exception_description(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Failed checkpoint spans use OpenTelemetry Error without secret description."""
    _install_fake_otel(monkeypatch)
    failure = RuntimeError("provider-secret")
    store = _Store(failure=failure)
    tracer = _Tracer()
    observed = telemetry.OpenTelemetryCheckpointStore(
        store,
        tracer=tracer,
        meter=_Meter(),
    )

    with pytest.raises(RuntimeError) as raised:
        observed.load("consumer-secret", "batch-secret", "endpoint-secret")

    assert raised.value is failure
    span = tracer.contexts[0].span
    assert span.statuses == [_ERROR_STATUS]
    assert span.attributes["error.type"] == "internal_error"
    assert tracer.contexts[0].exits == [(None, None, None)]
    assert "provider-secret" not in repr(span.statuses)


def test_successful_operation_leaves_span_status_unset(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Successful checkpoint spans retain the OpenTelemetry default Unset status."""
    _install_fake_otel(monkeypatch)
    store = _Store()
    tracer = _Tracer()
    observed = telemetry.OpenTelemetryCheckpointStore(
        store,
        tracer=tracer,
        meter=_Meter(),
    )

    assert observed.load("consumer", "batch", "endpoint") is store.result
    assert tracer.contexts[0].span.statuses == []


def test_span_status_failure_never_masks_application_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing observer status mutation preserves the exact application error."""
    _install_fake_otel(monkeypatch)
    failure = RuntimeError("application-secret")
    store = _Store(failure=failure)
    tracer = _Tracer(status_failure=RuntimeError("telemetry-secret"))
    observed = telemetry.OpenTelemetryCheckpointStore(
        store,
        tracer=tracer,
        meter=_Meter(),
    )

    with pytest.raises(RuntimeError) as raised:
        observed.load("consumer", "batch", "endpoint")

    assert raised.value is failure
    assert tracer.contexts[0].span.statuses == [_ERROR_STATUS]


def test_missing_opentelemetry_api_keeps_failure_authoritative(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Missing optional OpenTelemetry API support degrades to status-less telemetry."""
    original_import = builtins.__import__

    def reject_opentelemetry(
        name: str,
        globals: dict[str, Any] | None = None,
        locals: dict[str, Any] | None = None,
        fromlist: tuple[str, ...] = (),
        level: int = 0,
    ) -> Any:
        if name == "opentelemetry.trace":
            raise ImportError("optional API unavailable")
        return original_import(name, globals, locals, fromlist, level)

    monkeypatch.delitem(sys.modules, "opentelemetry.trace", raising=False)
    monkeypatch.delitem(sys.modules, "opentelemetry", raising=False)
    monkeypatch.setattr(builtins, "__import__", reject_opentelemetry)
    failure = RuntimeError("application-secret")
    store = _Store(failure=failure)
    tracer = _Tracer()
    observed = telemetry.OpenTelemetryCheckpointStore(
        store,
        tracer=tracer,
        meter=_Meter(),
    )

    with pytest.raises(RuntimeError) as raised:
        observed.load("consumer", "batch", "endpoint")

    assert raised.value is failure
    assert tracer.contexts[0].span.statuses == []


def test_authoritative_docs_require_explicit_error_status_and_current_semconv() -> None:
    """Authoritative guidance records the explicit Error-status confidentiality rule."""
    adr = _normalized("docs/adr/0008-checkpoint-opentelemetry-observability.md")
    operator = _normalized("docs/checkpoint-observability.md")
    doctoring = _normalized("docs/doctoring/checkpoint-opentelemetry-observability.md")

    required = (
        "failed checkpoint spans explicitly set OpenTelemetry status Error without a description",
        "successful checkpoint spans leave status Unset",
    )
    for document in (adr, operator, doctoring):
        for phrase in required:
            assert phrase in document
    assert "OpenTelemetry semantic conventions 1.44.0" in doctoring
