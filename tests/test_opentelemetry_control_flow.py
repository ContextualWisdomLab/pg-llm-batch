# SPDX-License-Identifier: Apache-2.0
"""Regression tests for precise telemetry-only failure isolation."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.observability import OpenTelemetryBatchAPIClient


class TelemetryControlFlow(BaseException):
    """Represent process-level control flow that telemetry must not swallow."""


class ControlFlowTracer:
    """Raise process-level control flow before creating a telemetry span."""

    def start_as_current_span(self, _name: str, **_kwargs: Any) -> Any:
        """Raise the deterministic control-flow signal."""
        raise TelemetryControlFlow("stop-process")


class NoOpInstrument:
    """Accept metric calls that are unreachable in this regression test."""

    def add(self, _value: int, *, attributes: dict[str, str]) -> None:
        """Discard a counter update."""
        del attributes

    def record(self, _value: float, *, attributes: dict[str, str]) -> None:
        """Discard a histogram update."""
        del attributes


class NoOpMeter:
    """Create deterministic no-op metric instruments."""

    def create_counter(self, _name: str, **_kwargs: Any) -> NoOpInstrument:
        """Return a no-op counter."""
        return NoOpInstrument()

    def create_histogram(self, _name: str, **_kwargs: Any) -> NoOpInstrument:
        """Return a no-op histogram."""
        return NoOpInstrument()


def credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic credentials for the control-flow regression test."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


async def test_telemetry_does_not_swallow_non_cancellation_base_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only ordinary telemetry failures and cancellation are isolated."""
    provider_calls = 0

    async def parent_method(_self: BatchAPIClient, *_args: Any, **_kwargs: Any) -> Any:
        nonlocal provider_calls
        provider_calls += 1
        return {"success": True}

    monkeypatch.setattr(BatchAPIClient, "cancel_batch", parent_method)
    client = OpenTelemetryBatchAPIClient(
        "postgresql://example",
        credentials,
        tracer=ControlFlowTracer(),
        meter=NoOpMeter(),
    )

    with pytest.raises(TelemetryControlFlow, match="stop-process"):
        await client.cancel_batch("batch-1", "default")

    assert provider_calls == 0
