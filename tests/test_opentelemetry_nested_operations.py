# SPDX-License-Identifier: Apache-2.0
"""Regression tests for nested public-operation telemetry suppression."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

import pytest

from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.observability import OpenTelemetryBatchAPIClient


@dataclass
class CapturingSpan:
    """Accept bounded attributes emitted by the observed operation."""

    attributes: dict[str, Any] = field(default_factory=dict)

    def set_attribute(self, name: str, value: Any) -> None:
        """Store one span attribute for deterministic assertions."""
        self.attributes[name] = value


class CapturingSpanContext:
    """Expose one span through the OpenTelemetry context-manager protocol."""

    def __init__(self, span: CapturingSpan) -> None:
        self._span = span

    def __enter__(self) -> CapturingSpan:
        """Return the captured span when observation begins."""
        return self._span

    def __exit__(self, *_exc: Any) -> None:
        """Close the span without suppressing provider exceptions."""
        return None


class CapturingTracer:
    """Capture every public-operation span name requested by the client."""

    def __init__(self) -> None:
        self.names: list[str] = []

    def start_as_current_span(self, name: str, **_kwargs: Any) -> CapturingSpanContext:
        """Record the name and return an in-memory span context."""
        self.names.append(name)
        return CapturingSpanContext(CapturingSpan())


@dataclass
class CapturingInstrument:
    """Capture metric attributes while ignoring measurement magnitudes."""

    operation_names: list[str] = field(default_factory=list)

    def add(self, _value: int, *, attributes: dict[str, str]) -> None:
        """Record one counter operation name."""
        self.operation_names.append(attributes["pg_llm_batch.operation.name"])

    def record(self, _value: float, *, attributes: dict[str, str]) -> None:
        """Record one histogram operation name."""
        self.operation_names.append(attributes["pg_llm_batch.operation.name"])


class CapturingMeter:
    """Return separate capturing counter and histogram instruments."""

    def __init__(self) -> None:
        self.counter = CapturingInstrument()
        self.histogram = CapturingInstrument()

    def create_counter(
        self, _name: str, *, unit: str, description: str
    ) -> CapturingInstrument:
        """Return the deterministic counter instrument."""
        del unit, description
        return self.counter

    def create_histogram(
        self, _name: str, *, unit: str, description: str
    ) -> CapturingInstrument:
        """Return the deterministic duration instrument."""
        del unit, description
        return self.histogram


def credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic credentials for parent-client construction."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


def build_client() -> tuple[
    OpenTelemetryBatchAPIClient, CapturingTracer, CapturingMeter
]:
    """Build an instrumented client with deterministic capture providers."""
    tracer = CapturingTracer()
    meter = CapturingMeter()
    client = OpenTelemetryBatchAPIClient(
        "postgresql://example",
        credentials,
        tracer=tracer,
        meter=meter,
    )
    return client, tracer, meter


@pytest.mark.parametrize("operation_name", ["wait_for_batch", "download_results"])
async def test_parent_operation_suppresses_internal_status_poll_telemetry(
    monkeypatch: pytest.MonkeyPatch,
    operation_name: str,
) -> None:
    """A caller invocation emits only its own signal set, not internal poll signals."""
    client, tracer, meter = build_client()

    async def terminal_status(
        _self: BatchAPIClient, _batch_id: str, _endpoint_alias: str
    ) -> dict[str, Any]:
        return {"status": "completed", "is_complete": True}

    monkeypatch.setattr(BatchAPIClient, "get_batch_status", terminal_status)

    if operation_name == "wait_for_batch":
        result = await client.wait_for_batch(
            "batch-1",
            "private-alias",
            poll_interval_seconds=0.01,
            timeout_seconds=1.0,
        )
        assert result["status"] == "completed"
    else:
        result = await client.download_results("batch-1", "private-alias")
        assert result == {"success": False, "reason": "No output_file_id on batch"}

    expected_span_name = f"pg_llm_batch.{operation_name}"
    assert tracer.names == [expected_span_name]
    assert meter.counter.operation_names == [operation_name]
    assert meter.histogram.operation_names == [operation_name]
