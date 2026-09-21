# SPDX-License-Identifier: Apache-2.0
"""PostgreSQL DSN authority regressions for durable batch lifecycle handoff."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.batch_api_client import GatewayCredentials
from pg_llm_batch.durable_client import DurableBatchAPIClient


class _BehaviorBearingDsn(str):
    """Record caller-controlled string hooks without changing stored characters."""

    def __new__(
        cls,
        value: str,
        events: list[str],
    ) -> "_BehaviorBearingDsn":
        """Create one hostile DSN while retaining an external hook ledger."""
        instance = super().__new__(cls, value)
        instance._events = events
        return instance

    def __bool__(self) -> bool:
        """Record truth evaluation that must not run at the DSN trust boundary."""
        self._events.append("__bool__")
        return True

    def __str__(self) -> str:
        """Record caller string conversion and return attacker-selected text."""
        self._events.append("__str__")
        return "postgresql://attacker.invalid/redirected"


class _ClassSpoofingDsn:
    """Expose a caller-controlled ``__class__`` hook that impersonates ``str``."""

    def __init__(self, events: list[str]) -> None:
        """Retain the hook ledger without becoming an actual string subtype."""
        self._events = events

    @property
    def __class__(self) -> type[str]:
        """Record class probing and impersonate ``str`` to unsafe ``isinstance`` checks."""
        self._events.append("__class__")
        return str


def _credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic credentials if a test unexpectedly reaches provider setup."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


@pytest.mark.asyncio
async def test_durable_client_snapshots_dsn_before_lifecycle_handoff() -> None:
    """Durable hooks receive one exact built-in DSN without caller hook execution."""
    events: list[str] = []
    original_text = "postgresql://db.example/tenant?application_name=pg-llm-batch"
    hostile_dsn = _BehaviorBearingDsn(original_text, events)
    reserved_dsns: list[Any] = []
    recorded_dsns: list[Any] = []

    def reserve(dsn: str) -> int:
        """Capture the DSN handed to durable observation-order reservation."""
        reserved_dsns.append(dsn)
        return 1

    def record(
        dsn: str,
        _endpoint_alias: str,
        _provider_batch: dict[str, Any],
        _observation_order: int,
    ) -> None:
        """Capture the DSN handed to durable lifecycle persistence."""
        recorded_dsns.append(dsn)

    client = DurableBatchAPIClient(
        hostile_dsn,
        _credentials,
        observation_reserver=reserve,
        lifecycle_recorder=record,
    )

    assert events == []
    assert type(client.postgres_dsn) is str
    assert client.postgres_dsn == original_text
    assert client.postgres_dsn is not hostile_dsn

    observation_order = await client._reserve_observation_order(
        "gateway-a",
        operation="DSN authority regression",
        batch_id=None,
    )
    await client._record_lifecycle_snapshot(
        "gateway-a",
        {"id": "batch-a", "status": "queued"},
        observation_order,
    )

    assert observation_order == 1
    assert reserved_dsns == [client.postgres_dsn]
    assert recorded_dsns == [client.postgres_dsn]
    assert type(reserved_dsns[0]) is str
    assert type(recorded_dsns[0]) is str
    assert reserved_dsns[0] is client.postgres_dsn
    assert recorded_dsns[0] is client.postgres_dsn
    assert events == []


@pytest.mark.parametrize("invalid_dsn", [1, object()])
def test_batch_client_rejects_non_string_dsn_before_retaining_authority(
    invalid_dsn: Any,
) -> None:
    """Truthy non-string DSNs fail during construction instead of becoming authority."""
    with pytest.raises(RuntimeError, match="A Postgres DSN is required"):
        DurableBatchAPIClient(invalid_dsn, _credentials)


def test_batch_client_rejects_class_spoof_without_executing_caller_hook() -> None:
    """Admission uses the real runtime type instead of caller-controlled ``__class__``."""
    events: list[str] = []
    invalid_dsn = _ClassSpoofingDsn(events)

    with pytest.raises(RuntimeError, match="A Postgres DSN is required"):
        DurableBatchAPIClient(invalid_dsn, _credentials)

    assert events == []
