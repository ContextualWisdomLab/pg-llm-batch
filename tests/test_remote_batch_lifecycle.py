# SPDX-License-Identifier: Apache-2.0
"""Tests for durable provider batch lifecycle persistence."""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from pg_llm_batch import db
from pg_llm_batch.batch_api_client import GatewayCredentials
from pg_llm_batch.durable_client import DurableBatchAPIClient
from pg_llm_batch.exceptions import GatewayError


class _Cursor:
    """Record SQL executions and return configured rows for database tests."""

    def __init__(self, driver: Any) -> None:
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *exc: Any):
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        self.driver.executions.append((sql, params))

    def fetchone(self):
        if not self.driver.fetchone_rows:
            return None
        return self.driver.fetchone_rows.pop(0)


class _Connection:
    """Expose a cursor and commit counter for the fake driver."""

    def __init__(self, driver: Any) -> None:
        self.driver = driver

    def __enter__(self):
        return self

    def __exit__(self, *exc: Any):
        return None

    def cursor(self):
        return _Cursor(self.driver)

    def commit(self) -> None:
        self.driver.commits += 1


class _Psycopg:
    """Minimal psycopg replacement used by the database helper tests."""

    def __init__(self, fetchone_rows: list[Any] | None = None) -> None:
        self.executions: list[tuple[str, Any]] = []
        self.commits = 0
        self.connections: list[str] = []
        self.fetchone_rows = list(fetchone_rows or [])

    def connect(self, dsn: str):
        self.connections.append(dsn)
        return _Connection(self)


class _Response:
    """Async response double for successful or failed provider operations."""

    def __init__(self, status: int, payload: dict[str, Any]) -> None:
        self.status = status
        self.payload = payload
        self.headers: dict[str, str] = {}

    async def json(self) -> dict[str, Any]:
        return self.payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc: Any):
        return None


class _Session:
    """Route provider operations to exact canned responses."""

    def __init__(self, responses: dict[tuple[str, str], Any]) -> None:
        self.responses = responses

    def post(self, url: str, **_kwargs: Any):
        return self.responses[("POST", url)]

    def get(self, url: str, **_kwargs: Any):
        return self.responses[("GET", url)]


class _SequenceSession:
    """Return ordered responses for overlapping calls to the same URL."""

    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)

    def get(self, _url: str, **_kwargs: Any):
        if not self.responses:
            raise AssertionError("no response left")
        return self.responses.pop(0)


def _credentials(_alias: str) -> GatewayCredentials:
    """Return deterministic credentials for provider request tests."""
    return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


def test_schema_defines_an_ordered_terminal_safe_remote_lifecycle_table() -> None:
    """The schema exposes compound identity, global order, and audit fields."""
    schema = Path(db.SCHEMA_PATH).read_text(encoding="utf-8")
    source = Path(db.__file__).read_text(encoding="utf-8")
    assert "CREATE SEQUENCE IF NOT EXISTS llm_remote_batch_observation_sequence" in schema
    assert "CREATE TABLE IF NOT EXISTS llm_remote_batch_jobs" in schema
    assert "CONSTRAINT uq_llm_remote_batch_jobs_endpoint_id" in schema
    assert "UNIQUE (endpoint_alias, remote_batch_id)" in schema
    assert "observation_order BIGINT NOT NULL" in schema
    assert "last_observed_at" in schema
    assert "terminal_at" in schema
    assert "idx_llm_remote_batch_jobs_status_observed" in schema
    assert "EXCLUDED.observation_order > llm_remote_batch_jobs.observation_order" in source
    assert "llm_remote_batch_jobs.batch_status NOT IN" in source
    assert "EXCLUDED.batch_status = llm_remote_batch_jobs.batch_status" in source


def test_reserve_remote_batch_observation_order_uses_database_sequence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The lifecycle ticket comes from the shared PostgreSQL sequence."""
    driver = _Psycopg(fetchone_rows=[(41,)])
    monkeypatch.setattr(db, "psycopg", driver)

    order = db.reserve_remote_batch_observation_order("postgresql://x")

    assert order == 41
    assert driver.connections == ["postgresql://x"]
    assert driver.executions == [
        ("SELECT nextval('llm_remote_batch_observation_sequence')", None)
    ]


@pytest.mark.parametrize(
    "row",
    [None, (), (True,), (0,), (-1,), (1.5,), ("1",)],
)
def test_reserve_remote_batch_observation_order_rejects_invalid_rows(
    monkeypatch: pytest.MonkeyPatch,
    row: Any,
) -> None:
    """An invalid sequence result cannot become a lifecycle order."""
    rows = [] if row is None else [row]
    monkeypatch.setattr(db, "psycopg", _Psycopg(fetchone_rows=rows))

    with pytest.raises(RuntimeError, match="invalid order"):
        db.reserve_remote_batch_observation_order("postgresql://x")


def test_persist_remote_batch_state_upserts_curated_terminal_snapshot(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A terminal provider observation is stored without arbitrary response data."""
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
        observation_order=17,
        observed_at=observed,
    )

    assert snapshot == {
        "endpoint_alias": "primary",
        "remote_batch_id": "batch-123",
        "observation_order": 17,
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
    assert "observation_order = EXCLUDED.observation_order" in sql
    assert "ignored_provider_field" not in params[11]
    assert params[11] == '{"tenant_id":"tenant-a"}'
    assert driver.connections == ["postgresql://x"]
    assert driver.commits == 1


def test_persist_remote_batch_state_normalizes_untrusted_optional_fields(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Invalid optional provider values become deterministic safe defaults."""
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
        observation_order=18,
    )

    assert snapshot["endpoint_alias"] == "edge"
    assert snapshot["observation_order"] == 18
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


@pytest.mark.parametrize(
    "metadata_value",
    [
        {"unsupported": {1, 2}},
        {"not_finite": float("nan")},
        {"surrogate": "\ud800"},
    ],
)
def test_persist_remote_batch_state_normalizes_non_json_metadata(
    monkeypatch: pytest.MonkeyPatch,
    metadata_value: Any,
) -> None:
    """Non-JSON provider metadata becomes the canonical empty object."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)
    snapshot = db.persist_remote_batch_state(
        "postgresql://x",
        "primary",
        {"id": "batch-1", "metadata": metadata_value},
        observation_order=19,
    )
    assert snapshot["provider_metadata"] == {}
    assert driver.executions[-1][1][11] == "{}"


def test_persist_remote_batch_state_normalizes_cyclic_metadata(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cyclic metadata graph cannot escape the JSON trust boundary."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)
    metadata: dict[str, Any] = {}
    metadata["self"] = metadata

    snapshot = db.persist_remote_batch_state(
        "postgresql://x",
        "primary",
        {"id": "batch-1", "metadata": metadata},
        observation_order=20,
    )

    assert snapshot["provider_metadata"] == {}
    assert driver.executions[-1][1][11] == "{}"


def test_persist_remote_batch_state_bounds_metadata_bytes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Excessive canonical metadata is discarded before the database write."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)
    snapshot = db.persist_remote_batch_state(
        "postgresql://x",
        "primary",
        {"id": "batch-1", "metadata": {"value": "x" * (64 * 1024)}},
        observation_order=21,
    )
    assert snapshot["provider_metadata"] == {}
    assert driver.executions[-1][1][11] == "{}"


@pytest.mark.parametrize("observation_order", [None, True, 0, -1, 1.5, "1"])
def test_persist_remote_batch_state_rejects_invalid_observation_order(
    monkeypatch: pytest.MonkeyPatch,
    observation_order: Any,
) -> None:
    """Only positive non-boolean integer lifecycle orders are accepted."""
    monkeypatch.setattr(db, "psycopg", _Psycopg())
    with pytest.raises(ValueError, match="observation_order"):
        db.persist_remote_batch_state(
            "postgresql://x",
            "primary",
            {"id": "batch-1"},
            observation_order=observation_order,
        )


@pytest.mark.parametrize("endpoint_alias", [None, "", "   "])
def test_persist_remote_batch_state_rejects_invalid_endpoint_alias(
    monkeypatch: pytest.MonkeyPatch,
    endpoint_alias: Any,
) -> None:
    """Lifecycle identities require a non-empty textual endpoint alias."""
    monkeypatch.setattr(db, "psycopg", _Psycopg())
    with pytest.raises(ValueError, match="endpoint_alias"):
        db.persist_remote_batch_state(
            "postgresql://x",
            endpoint_alias,
            {"id": "batch-1"},
            observation_order=1,
        )


@pytest.mark.parametrize("provider_batch", [None, [], "batch"])
def test_persist_remote_batch_state_rejects_non_object_payload(
    monkeypatch: pytest.MonkeyPatch,
    provider_batch: Any,
) -> None:
    """Provider lifecycle payloads must be mapping objects."""
    monkeypatch.setattr(db, "psycopg", _Psycopg())
    with pytest.raises(ValueError, match="provider_batch"):
        db.persist_remote_batch_state(
            "postgresql://x",
            "primary",
            provider_batch,
            observation_order=1,
        )


@pytest.mark.parametrize("remote_id", [None, "", 3])
def test_persist_remote_batch_state_rejects_missing_remote_id(
    monkeypatch: pytest.MonkeyPatch,
    remote_id: Any,
) -> None:
    """A durable row cannot be written without a provider batch identifier."""
    monkeypatch.setattr(db, "psycopg", _Psycopg())
    with pytest.raises(ValueError, match="provider batch id"):
        db.persist_remote_batch_state(
            "postgresql://x",
            "primary",
            {"id": remote_id},
            observation_order=1,
        )


def test_persist_remote_batch_state_requires_aware_observation_time(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Audit timestamps must be timezone-aware to remain unambiguous."""
    monkeypatch.setattr(db, "psycopg", _Psycopg())
    with pytest.raises(ValueError, match="timezone-aware"):
        db.persist_remote_batch_state(
            "postgresql://x",
            "primary",
            {"id": "batch-1"},
            observation_order=1,
            observed_at=datetime(2026, 8, 4, 9, 0),
        )


async def test_durable_client_records_create_poll_and_successful_cancel() -> None:
    """Successful lifecycle transitions retain their pre-request global orders."""
    recorded: list[tuple[str, str, dict[str, Any], int]] = []
    reserved: list[str] = []
    orders = iter([101, 102, 103])

    def reserver(dsn: str) -> int:
        reserved.append(dsn)
        return next(orders)

    def recorder(
        dsn: str,
        alias: str,
        payload: Any,
        observation_order: int,
    ) -> None:
        recorded.append((dsn, alias, dict(payload), observation_order))

    client = DurableBatchAPIClient(
        "postgresql://x",
        _credentials,
        lifecycle_recorder=recorder,
        observation_reserver=reserver,
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
    assert reserved == ["postgresql://x"] * 3
    assert [entry[2]["id"] for entry in recorded] == [
        "batch-1",
        "batch-1",
        "batch-1",
    ]
    assert [entry[3] for entry in recorded] == [101, 102, 103]
    assert recorded[0][2]["input_file_id"] == "file-1"
    assert recorded[0][2]["endpoint"] == "/v1/responses"
    assert recorded[0][2]["metadata"] == {"tenant_id": "tenant-a"}
    assert recorded[1][2]["progress_percentage"] == 50.0
    assert recorded[2][2]["status"] == "cancelling"


async def test_durable_client_does_not_record_failed_cancel() -> None:
    """A rejected cancellation consumes its order but records no transition."""
    recorded: list[Any] = []
    client = DurableBatchAPIClient(
        "postgresql://x",
        _credentials,
        lifecycle_recorder=lambda *_args: recorded.append(_args),
        observation_reserver=lambda _dsn: 104,
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


async def test_durable_client_surfaces_persistence_failure_with_remote_id() -> None:
    """Remote success without local durability exposes ordered recovery data."""

    def failing_recorder(
        _dsn: str,
        _alias: str,
        _payload: Any,
        _observation_order: int,
    ) -> None:
        raise OSError("database unavailable")

    client = DurableBatchAPIClient(
        "postgresql://x",
        _credentials,
        lifecycle_recorder=failing_recorder,
        observation_reserver=lambda _dsn: 105,
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
        "phase": "persistence",
        "endpoint_alias": "primary",
        "batch_id": "batch-9",
        "observation_order": 105,
        "error_type": "OSError",
    }


async def test_durable_client_reserves_order_before_provider_request() -> None:
    """The global order ticket is acquired before provider I/O begins."""
    events: list[Any] = []

    class OrderedResponse(_Response):
        async def __aenter__(self):
            events.append("provider")
            return await super().__aenter__()

    def reserver(dsn: str) -> int:
        events.append(("reserve", dsn))
        return 7

    def recorder(
        dsn: str,
        alias: str,
        payload: Any,
        observation_order: int,
    ) -> None:
        events.append(("persist", dsn, alias, payload["id"], observation_order))

    client = DurableBatchAPIClient(
        "postgresql://x",
        _credentials,
        lifecycle_recorder=recorder,
        observation_reserver=reserver,
    )
    client._session = _Session(
        {
            ("GET", "https://gateway.example/v1/batches/batch-1"): OrderedResponse(
                200,
                {"id": "batch-1", "status": "in_progress", "request_counts": {}},
            )
        }
    )

    await client.get_batch_status("batch-1", "primary")

    assert events == [
        ("reserve", "postgresql://x"),
        "provider",
        ("persist", "postgresql://x", "primary", "batch-1", 7),
    ]


async def test_reservation_failure_prevents_remote_creation() -> None:
    """A missing durability ticket blocks a side-effecting provider POST."""
    calls: list[Any] = []

    class RecordingSession:
        def post(self, url: str, **kwargs: Any):
            calls.append((url, kwargs))
            raise AssertionError("provider POST must not occur")

    def failing_reserver(_dsn: str) -> int:
        raise OSError("database unavailable")

    client = DurableBatchAPIClient(
        "postgresql://x",
        _credentials,
        observation_reserver=failing_reserver,
    )
    client._session = RecordingSession()

    with pytest.raises(GatewayError, match="reservation failed") as exc_info:
        await client.create_batch_job("file-1", "primary")

    assert calls == []
    assert exc_info.value.response_data == {
        "operation": "Batch creation",
        "phase": "reservation",
        "endpoint_alias": "primary",
        "batch_id": None,
        "error_type": "OSError",
    }


@pytest.mark.parametrize("reserved_value", [None, True, 0, -1, 1.5, "1"])
async def test_invalid_reserved_order_prevents_provider_poll(
    reserved_value: Any,
) -> None:
    """An invalid custom reservation result fails before provider I/O."""
    calls: list[Any] = []

    class RecordingSession:
        def get(self, url: str, **kwargs: Any):
            calls.append((url, kwargs))
            raise AssertionError("provider GET must not occur")

    client = DurableBatchAPIClient(
        "postgresql://x",
        _credentials,
        observation_reserver=lambda _dsn: reserved_value,
    )
    client._session = RecordingSession()

    with pytest.raises(GatewayError, match="reservation failed") as exc_info:
        await client.get_batch_status("batch-1", "primary")

    assert calls == []
    assert exc_info.value.response_data["batch_id"] == "batch-1"
    assert exc_info.value.response_data["error_type"] == "ValueError"


async def test_overlapping_polls_cannot_regress_a_later_started_observation() -> None:
    """A delayed earlier response carries a lower order and is ignored by the store."""
    first_entered = asyncio.Event()
    release_first = asyncio.Event()
    orders = iter([1, 2])
    stored: dict[str, Any] = {"observation_order": 0}

    class DelayedResponse(_Response):
        async def __aenter__(self):
            first_entered.set()
            await release_first.wait()
            return self

    def recorder(
        _dsn: str,
        _alias: str,
        payload: Any,
        observation_order: int,
    ) -> None:
        if observation_order > stored["observation_order"]:
            stored.clear()
            stored.update(
                observation_order=observation_order,
                status=payload["status"],
            )

    client = DurableBatchAPIClient(
        "postgresql://x",
        _credentials,
        observation_reserver=lambda _dsn: next(orders),
        lifecycle_recorder=recorder,
    )
    client._session = _SequenceSession(
        [
            DelayedResponse(
                200,
                {"id": "batch-1", "status": "validating", "request_counts": {}},
            ),
            _Response(
                200,
                {"id": "batch-1", "status": "completed", "request_counts": {}},
            ),
        ]
    )

    earlier = asyncio.create_task(client.get_batch_status("batch-1", "primary"))
    await first_entered.wait()
    later = asyncio.create_task(client.get_batch_status("batch-1", "primary"))
    await later
    release_first.set()
    await earlier

    assert stored == {"observation_order": 2, "status": "completed"}
