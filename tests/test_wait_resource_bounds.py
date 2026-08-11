# SPDX-License-Identifier: Apache-2.0
"""Fail-closed resource-bound contracts for ``BatchAPIClient.wait_for_batch``."""

from __future__ import annotations

import math
from typing import Any

import pytest

from pg_llm_batch.batch_api_client import BatchAPIClient, GatewayCredentials
from pg_llm_batch.exceptions import ValidationError


def _unexpected_credentials(_alias: str) -> GatewayCredentials:
    """Fail if invalid wait controls reach credential or provider I/O."""
    raise AssertionError("invalid wait controls reached credential resolution")


def _client() -> BatchAPIClient:
    """Build a client whose provider boundary must remain unreachable."""
    return BatchAPIClient("postgresql://x", _unexpected_credentials)


@pytest.mark.parametrize(
    "invalid_value",
    [True, "1", None, math.nan, math.inf, -math.inf],
)
async def test_wait_rejects_invalid_poll_intervals_before_provider_io(
    invalid_value: Any,
) -> None:
    """Polling intervals must be finite positive numbers, never bool/coerced input."""
    with pytest.raises(ValidationError, match="poll_interval_seconds"):
        await _client().wait_for_batch(
            "batch-1",
            "default",
            poll_interval_seconds=invalid_value,
            timeout_seconds=1.0,
        )


@pytest.mark.parametrize(
    "invalid_value",
    [True, "1", None, math.nan, math.inf, -math.inf],
)
async def test_wait_rejects_invalid_timeouts_before_provider_io(
    invalid_value: Any,
) -> None:
    """Timeouts must be finite positive numbers, never bool/coerced input."""
    with pytest.raises(ValidationError, match="timeout_seconds"):
        await _client().wait_for_batch(
            "batch-1",
            "default",
            poll_interval_seconds=1.0,
            timeout_seconds=invalid_value,
        )
