# SPDX-License-Identifier: Apache-2.0
"""Tests for durable provider batch lifecycle persistence."""

from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from pg_llm_batch import db
from pg_llm_batch.durable_client import DurableBatchAPIClient
from pg_llm_batch.exceptions import GatewayError
from pg_llm_batch.batch_api_client import GatewayCredentials


class _Cursor:
    """Record SQL executions for lifecycle persistence tests."""

    def __init__(self, driver):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def execute(self, sql, params=None):
        self.driver.executions.append((sql, params))


class _Connection:
    """Expose a cursor and commit counter for the fake driver."""

    def __init__(self, driver):
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def cursor(self):
        return _Cursor(self.driver)

    def commit(self):
        self.driver.commits += 1


class _Psycopg:
    """Minimal psycopg replacement used by the database helper tests."""

    def __init__(self):
        self.executions = []
        self.commits = 0
        self.connections = []

    def connect(self, dsn):
        self.connections.append(dsn)
        return _Connection(self)


class _Response:
    """Async response double for successful or failed provider operations."""

    def __init__(self, status, payload):
        self.status = status
        self.payload = payload
        self.headers = {}

    async def json(self):
        return self.payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return None


class _Session:
    """Route provider operations to exact canned responses."""

    def __init__(self, responses):
        self.responses = responses

    def post(self, url, **_kwargs):
        return self.responses[("POST", url)]

    def get(self, url, **_kwargs):
        return self.responses[("GET", url)]


def _credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic credentials for provider request tests."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


def test_schema_defines_a_stale_safe_remote_lifecycle_table():
    """The packaged schema must expose one unique lifecycle row per provider job."""
    schema = Path(db.SCHEMA_PATH).read_text(encoding="utf-8")
    assert "CREATE TABLE IF NOT EXISTS llm_remote_batch_jobs" in schema
    assert "CONSTRAINT uq_llm_remote_batch_jobs_endpoint_id" in schema
    assert "UNIQUE (endpoint_alias, remote_batch_id)" in schema
    assert "last_observed_at" in schema
    assert "terminal_at" in schema
    assert "idx_llm_remote_batch_jobs_status_observed" in schema


def test_persist_remote_batch_state_upserts_curated_terminal_snapshot(monkeypatch):
    """A terminal provider observation is atomically stored without raw response data."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)
    observed = datetime(2026, 8, 4, 9, 0, tzinfo=timezone.utc)
    snapshot = db.persist_remote_batch_state(
        "postgresql://x",
        "primary",
        {
            "id": "batch-123",
            "input_file_id": "file-123",
            "endpoint": "/v1/responses",
            "status": "completed",
            "output_file_id": "output-123",
            "error_file_id": "error-123",
            "request_counts": {"total": 4, "completed": 3, "failed": 1},
            "metadata": {"tenant_id": "tenant-a"},
            "ignored_provider_field": "must not be persisted",
        },
        observed_at=observed,
    )

    assert snapshot == {
        "endpoint_alias": "primary",
        "remote_batch_id": "batch-123",
        "input_file_id": "file-123",
        "batch_endpoint": "/v1/responses",
        "batch_status": "completed",
        "output_file_id": "output-123",
        "error_file_id": "error-123",
        "total_requests": 4,
        "completed_requests": 3,
        "failed_requests": 1,
        "provider_metadata": {"tenant_id": "tenant-a"},
        "observed_at": observed,
        "terminal_at": observed,
    }
    sql, params = driver.executions[0]
    assert "ON CONFLICT (endpoint_alias, remote_batch_id) DO UPDATE" in sql
    assert "EXCLUDED.last_observed_at >= llm_remote_batch_jobs.last_observed_at" in sql
    assert "ignored_provider_field" not in params[10]
    assert params[10] == '{"tenant_id":"tenant-a"}'
    assert driver.connections == ["postgresql://x"]
    assert driver.commits == 1


def test_persist_remote_batch_state_normalizes_untrusted_optional_fields(monkeypatch):
    """Invalid optional provider values are reduced to safe deterministic defaults."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)
    snapshot = db.persist_remote_batch_state(
        "postgresql://x",
        "  edge  ",
        {
            "id": "batch-edge",
            "input_file_id": 7,
            "endpoint": "",
            "status": None,
            "output_file_id": False,
            "error_file_id": [],
            "request_counts": {"total": True, "completed": -1, "failed": "2"},
            "metadata": ["not", "an", "object"],
        },
    )

    assert snapshot["endpoint_alias"] == "edge"
    assert snapshot["batch_status"] == "unknown"
    assert snapshot["input_file_id"] is None
    assert snapshot["batch_endpoint"] is None
    assert snapshot["output_file_id"] is None
    assert snapshot["error_file_id"] is None
    assert snapshot["total_requests"] == 0
    assert snapshot["completed_requests"] == 0
    assert snapshot["failed_requests"] == 0
    assert snapshot["provider_metadata"] == {}
    assert snapshot["observed_at"].tzinfo is timezone.utc
    assert snapshot["terminal_at"] is None


@pytest.mark.parametrize("endpoint_alias", [None, "", "   "])
def test_persist_remote_batch_state_rejects_invalid_endpoint_alias(monkeypatch, endpoint_alias):
    """Lifecycle identities require a non-empty textual endpoint alias."""
    monkeypatch.setattr(db, "psycopg", _Psycopg())
    with pytest.raises(ValueError, match="endpoint_alias"):
        db.persist_remote_batch_state(
            "postgresql://x", endpoint_alias, {"id": "batch-1"}
        )


@pytest.mark.parametrize("provider_batch", [None, [], "batch"])
def test_persist_remote_batch_state_rejects_non_object_payload(monkeypatch, provider_batch):
    """Provider lifecycle payloads must be mapping objects."""
    monkeypatch.setattr(db, "psycopg", _Psycopg())
    with pytest.raises(ValueError, match="provider_batch"):
        db.persist_remote_batch_state("postgresql://x", "primary", provider_batch)


@pytest.mark.parametrize("remote_id", [None, "", 3])
def test_persist_remote_batch_state_rejects_missing_remote_id(monkeypatch, remote_id):
    """A durable row cannot be written without a provider batch identifier."""
    monkeypatch.setattr(db, "psycopg", _Psycopg())
    with pytest.raises(ValueError, match="provider batch id"):
        db.persist_remote_batch_state(
            "postgresql://x", "primary", {"id": remote_id}
        )


def test_persist_remote_batch_state_requires_aware_observation_time(monkeypatch):
    """Audit timestamps must be timezone-aware to remain unambiguous."""
    monkeypatch.setattr(db, "psycopg", _Psycopg())
    with pytest.raises(ValueError, match="timezone-aware"):
        db.persist_remote_batch_state(
            "postgresql://x",
            "primary",
            {"id": "batch-1"},
            observed_at=datetime(2026, 8, 4, 9, 0),
        )


async def test_durable_client_records_create_poll_and_successful_cancel():
    """Every successful lifecycle transition is recorded with a recoverable identity."""
    recorded = []

    def recorder(dsn, alias, payload):
        recorded.append((dsn, alias, dict(payload)))

    client = DurableBatchAPIClient(
        "postgresql://x", _credentials, lifecycle_recorder=recorder
    )
    client._session = _Session(
        {
            ("POST", "https://gateway.example/v1/batches"): _Response(
                201, {"id": "batch-1", "status": "validating"}
            ),
            ("GET", "https://gateway.example/v1/batches/batch-1"): _Response(
                200,
                {
                    "status": "in_progress",
                    "request_counts": {"total": 2, "completed": 1, "failed": 0},
                },
            ),
            ("POST", "https://gateway.example/v1/batches/batch-1/cancel"): _Response(
                202, {"status": "cancelling"}
            ),
        }
    )

    await client.create_batch_job(
        "file-1",
        "primary",
        endpoint="/v1/responses",
        metadata={"tenant_id": "tenant-a"},
    )
    await client.get_batch_status("batch-1", "primary")
    cancelled = await client.cancel_batch("batch-1", "primary")

    assert cancelled == {
        "success": True,
        "batch_id": "batch-1",
        "status": "cancelling",
    }
    assert [entry[2]["id"] for entry in recorded] == [
        "batch-1",
        "batch-1",
        "batch-1",
    ]
    assert recorded[0][2]["input_file_id"] == "file-1"
    assert recorded[0][2]["endpoint"] == "/v1/responses"
    assert recorded[0][2]["metadata"] == {"tenant_id": "tenant-a"}
    assert recorded[1][2]["progress_percentage"] == 50.0
    assert recorded[2][2]["status"] == "cancelling"


async def test_durable_client_does_not_record_failed_cancel():
    """A rejected cancellation must not fabricate a lifecycle transition."""
    recorded = []
    client = DurableBatchAPIClient(
        "postgresql://x",
        _credentials,
        lifecycle_recorder=lambda *_args: recorded.append(_args),
    )
    client._session = _Session(
        {
            ("POST", "https://gateway.example/v1/batches/batch-1/cancel"): _Response(
                409, {"error": {"message": "already complete"}}
            )
        }
    )

    result = await client.cancel_batch("batch-1", "primary")

    assert result == {"success": False, "reason": "already complete"}
    assert recorded == []


async def test_durable_client_surfaces_persistence_failure_with_remote_id():
    """A remote success without local durability fails closed and exposes recovery data."""
    def failing_recorder(_dsn, _alias, _payload):
        raise OSError("database unavailable")

    client = DurableBatchAPIClient(
        "postgresql://x", _credentials, lifecycle_recorder=failing_recorder
    )
    client._session = _Session(
        {
            ("POST", "https://gateway.example/v1/batches"): _Response(
                201, {"id": "batch-9", "status": "validating"}
            )
        }
    )

    with pytest.raises(GatewayError, match="lifecycle persistence failed") as exc_info:
        await client.create_batch_job("file-9", "primary")

    assert exc_info.value.response_data == {
        "operation": "Batch creation",
        "endpoint_alias": "primary",
        "batch_id": "batch-9",
        "error_type": "OSError",
    }
