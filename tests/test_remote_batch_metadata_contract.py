# SPDX-License-Identifier: Apache-2.0
"""Regression tests for PostgreSQL-safe provider metadata persistence."""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Mapping
from typing import Any

import pytest

from pg_llm_batch import db
from pg_llm_batch.batch_api_client import GatewayCredentials
from pg_llm_batch.durable_client import DurableBatchAPIClient


class _MetadataCursor:
    """Capture lifecycle SQL and bound parameters without a real database."""

    def __init__(self, driver: "_MetadataPsycopg") -> None:
        self.driver = driver

    def __enter__(self) -> "_MetadataCursor":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        """Record one SQL execution for deterministic trust-boundary assertions."""
        self.driver.executions.append((sql, params))


class _MetadataConnection:
    """Expose the connection operations used by lifecycle persistence."""

    def __init__(self, driver: "_MetadataPsycopg") -> None:
        self.driver = driver

    def __enter__(self) -> "_MetadataConnection":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def cursor(self) -> _MetadataCursor:
        """Return a cursor that records rather than executes SQL."""
        return _MetadataCursor(self.driver)

    def commit(self) -> None:
        """Record the explicit lifecycle transaction commit."""
        self.driver.commits += 1


class _MetadataPsycopg:
    """Minimal psycopg replacement for provider metadata contract tests."""

    def __init__(self) -> None:
        self.executions: list[tuple[str, Any]] = []
        self.connections: list[str] = []
        self.commits = 0

    def connect(self, dsn: str) -> _MetadataConnection:
        """Return a recording connection for the supplied DSN."""
        self.connections.append(dsn)
        return _MetadataConnection(self)


class _MetadataByteStream:
    """Expose deterministic provider JSON through bounded byte streaming."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.body = json.dumps(payload, separators=(",", ":")).encode("utf-8")

    async def iter_chunked(self, size: int) -> AsyncIterator[bytes]:
        """Yield response bytes using chunks no larger than the requested size."""
        for offset in range(0, len(self.body), size):
            yield self.body[offset : offset + size]


class _MetadataResponse:
    """Return one successful provider payload through aiohttp's response seam."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.status = 201
        self.headers: dict[str, str] = {}
        self.content = _MetadataByteStream(payload)
        self.content_length = len(self.content.body)

    async def json(self) -> dict[str, Any]:
        """Reject whole-body reads that bypass the bounded byte-stream contract."""
        raise AssertionError("response.json() must not bypass bounded streaming")

    async def __aenter__(self) -> "_MetadataResponse":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None


class _MetadataSession:
    """Expose one deterministic provider batch-creation response."""

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    def post(self, _url: str, **_kwargs: Any) -> _MetadataResponse:
        """Return the configured response for the provider POST request."""
        return _MetadataResponse(self.payload)


def _metadata_credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic gateway credentials for durable client tests."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


@pytest.mark.parametrize(
    "provider_metadata",
    [
        {"metadata_value": chr(0)},
        {f"metadata{chr(0)}key": "value"},
        {"nested_values": ["safe", chr(0)]},
    ],
    ids=("nul-value", "nul-key", "nested-nul-value"),
)
def test_postgresql_incompatible_nul_metadata_normalizes_to_empty_object(
    monkeypatch: pytest.MonkeyPatch,
    provider_metadata: dict[str, Any],
) -> None:
    """NUL-bearing JSON metadata must fail closed before the jsonb parameter."""
    driver = _MetadataPsycopg()
    monkeypatch.setattr(db, "psycopg", driver)

    snapshot = db.persist_remote_batch_state(
        "postgresql://example",
        "primary",
        {"id": "batch-1", "metadata": provider_metadata},
        observation_order=22,
    )

    assert snapshot["provider_metadata"] == {}
    assert driver.executions[0] == (
        "SELECT set_config('pg_llm_batch.tenant_scope', %s, true)",
        ("standalone",),
    )
    assert driver.executions[1][1][12] == "{}"
    assert driver.connections == ["postgresql://example"]
    assert driver.commits == 1


def test_postgresql_safe_metadata_retains_json_scalars_and_literal_escape(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Safe nested JSON and a literal backslash escape must remain unchanged."""
    driver = _MetadataPsycopg()
    monkeypatch.setattr(db, "psycopg", driver)
    provider_metadata = {
        "empty_object": {},
        "empty_values": [],
        "literal_escape": "\\u0000",
        "nested_values": [1, "safe"],
    }

    snapshot = db.persist_remote_batch_state(
        "postgresql://example",
        "primary",
        {"id": "batch-2", "metadata": provider_metadata},
        observation_order=23,
    )

    assert snapshot["provider_metadata"] == provider_metadata
    assert driver.executions[1][1][12] == json.dumps(
        provider_metadata,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


async def test_nul_metadata_normalizes_before_custom_lifecycle_recorder() -> None:
    """Embeddable recorders must receive the same PostgreSQL-safe metadata."""
    recorded_snapshots: list[Mapping[str, Any]] = []

    def recorder(
        _dsn: str,
        _alias: str,
        payload: Mapping[str, Any],
        _observation_order: int,
    ) -> None:
        recorded_snapshots.append(payload)

    client = DurableBatchAPIClient(
        "postgresql://example",
        _metadata_credentials,
        lifecycle_recorder=recorder,
        observation_reserver=lambda _dsn: 24,
    )
    client._session = _MetadataSession(
        {
            "id": "batch-3",
            "status": "validating",
            "metadata": {"nested_values": ["safe", chr(0)]},
        }
    )

    created = await client.create_batch_job("file-3", "primary")

    assert created["id"] == "batch-3"
    assert len(recorded_snapshots) == 1
    assert recorded_snapshots[0]["metadata"] == {}
