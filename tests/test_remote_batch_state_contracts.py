# SPDX-License-Identifier: Apache-2.0
"""Regression contracts for durable remote batch state semantics."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from pg_llm_batch import db
from pg_llm_batch.batch_api_client import GatewayCredentials
from pg_llm_batch.durable_client import DurableBatchAPIClient
from pg_llm_batch.exceptions import GatewayError, ValidationError


class _Cursor:
    """Capture SQL submitted by the lifecycle helper."""

    def __init__(self, driver: "_Psycopg") -> None:
        self.driver = driver

    def __enter__(self) -> "_Cursor":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def execute(self, sql: str, params: Any = None) -> None:
        """Record one SQL execution and its bound parameters."""
        self.driver.executions.append((sql, params))


class _Connection:
    """Expose the small connection surface used by the lifecycle helper."""

    def __init__(self, driver: "_Psycopg") -> None:
        self.driver = driver

    def __enter__(self) -> "_Connection":
        return self

    def __exit__(self, *_exc: Any) -> None:
        return None

    def cursor(self) -> _Cursor:
        """Return a cursor that records SQL instead of contacting PostgreSQL."""
        return _Cursor(self.driver)

    def commit(self) -> None:
        """Record the explicit lifecycle transaction commit."""
        self.driver.commits += 1


class _Psycopg:
    """Minimal psycopg replacement for deterministic SQL contract tests."""

    def __init__(self) -> None:
        self.executions: list[tuple[str, Any]] = []
        self.commits = 0
        self.connections: list[str] = []

    def connect(self, dsn: str) -> _Connection:
        """Return a fake connection for the supplied DSN."""
        self.connections.append(dsn)
        return _Connection(self)


class _ProviderResponse:
    """Return one successful provider batch creation response."""

    status = 201

    def __init__(self, payload: dict[str, Any]) -> None:
        self.payload = payload

    async def __aenter__(self) -> "_ProviderResponse":
        return self

    async def __aexit__(self, *_exc: Any) -> None:
        return None

    async def json(self) -> dict[str, Any]:
        """Return the configured provider JSON object."""
        return self.payload


class _ProviderSession:
    """Record provider POST calls and return one configured response."""

    def __init__(self, response: _ProviderResponse) -> None:
        self.response = response
        self.post_urls: list[str] = []

    def post(self, url: str, **_kwargs: Any) -> _ProviderResponse:
        """Record the provider URL and return its response context manager."""
        self.post_urls.append(url)
        return self.response


def _compact_sql(sql: str) -> str:
    """Normalize SQL whitespace so assertions focus on update semantics."""
    return " ".join(sql.split())


def test_sparse_observations_cannot_reduce_persisted_request_counts(
    monkeypatch: Any,
) -> None:
    """Newer sparse polls or cancellations must not erase known progress counts."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)

    db.persist_remote_batch_state(
        "postgresql://example",
        "primary",
        {"id": "batch-1", "status": "cancelling"},
        observation_order=2,
    )

    sql = _compact_sql(driver.executions[0][0])
    assert (
        "total_requests = GREATEST( llm_remote_batch_jobs.total_requests, "
        "EXCLUDED.total_requests )"
    ) in sql
    assert (
        "completed_requests = GREATEST( "
        "llm_remote_batch_jobs.completed_requests, EXCLUDED.completed_requests )"
    ) in sql
    assert (
        "failed_requests = GREATEST( llm_remote_batch_jobs.failed_requests, "
        "EXCLUDED.failed_requests )"
    ) in sql
    assert driver.commits == 1


def test_remote_identity_validators_accept_schema_maximums() -> None:
    """Exact schema-length aliases and provider identifiers remain supported."""
    endpoint_alias = "a" * 128
    remote_batch_id = "b" * 256

    assert db.validate_endpoint_alias(f" {endpoint_alias} ") == endpoint_alias
    assert (
        db.validate_remote_resource_id(remote_batch_id, "remote_batch_id")
        == remote_batch_id
    )
    schema = Path(db.SCHEMA_PATH).read_text(encoding="utf-8")
    assert (
        "CHECK (LENGTH(endpoint_alias) BETWEEN 1 AND "
        f"{db.MAX_ENDPOINT_ALIAS_CHARACTERS})"
    ) in schema
    assert (
        "CHECK (LENGTH(remote_batch_id) BETWEEN 1 AND "
        f"{db.MAX_REMOTE_RESOURCE_ID_CHARACTERS})"
    ) in schema


def test_remote_identity_validators_reject_values_beyond_schema_maximums() -> None:
    """One character beyond either durable identity limit fails closed."""
    with pytest.raises(ValidationError, match="endpoint_alias"):
        db.validate_endpoint_alias("a" * 129)
    with pytest.raises(ValidationError, match="remote_batch_id"):
        db.validate_remote_resource_id("b" * 257, "remote_batch_id")


def test_persistence_rejects_oversized_provider_id_before_database_access(
    monkeypatch: Any,
) -> None:
    """Unsupported provider IDs cannot reach PostgreSQL or its CHECK constraint."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)

    with pytest.raises(ValueError, match="remote_batch_id"):
        db.persist_remote_batch_state(
            "postgresql://example",
            "primary",
            {"id": "b" * 257, "status": "validating"},
            observation_order=3,
        )

    assert driver.connections == []
    assert driver.executions == []


def test_persistence_rejects_nul_alias_before_database_access(
    monkeypatch: Any,
) -> None:
    """PostgreSQL-incompatible NUL aliases fail before opening a connection."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)

    with pytest.raises(ValueError, match="endpoint_alias"):
        db.persist_remote_batch_state(
            "postgresql://example",
            "primary\x00shadow",
            {"id": "batch-1", "status": "validating"},
            observation_order=4,
        )

    assert driver.connections == []
    assert driver.executions == []


async def test_durable_client_rejects_oversized_alias_before_external_effects() -> None:
    """An invalid alias cannot reserve order, resolve secrets, or call a provider."""
    events: list[str] = []

    def credentials(_alias: str) -> GatewayCredentials:
        events.append("credentials")
        raise AssertionError("credentials must not be resolved")

    def reserver(_dsn: str) -> int:
        events.append("reservation")
        return 1

    client = DurableBatchAPIClient(
        "postgresql://example",
        credentials,
        observation_reserver=reserver,
    )

    with pytest.raises(ValidationError, match="endpoint_alias"):
        await client.create_batch_job("file-1", "a" * 129)

    assert events == []


async def test_durable_client_rejects_oversized_batch_id_before_reservation() -> None:
    """An invalid caller batch ID cannot consume an observation order."""
    reservations: list[str] = []

    def reserver(dsn: str) -> int:
        reservations.append(dsn)
        return 1

    client = DurableBatchAPIClient(
        "postgresql://example",
        lambda _alias: GatewayCredentials(
            url="https://gateway.example/v1",
            api_key="secret",
        ),
        observation_reserver=reserver,
    )

    with pytest.raises(ValidationError, match="batch_id"):
        await client.get_batch_status("b" * 257, "primary")

    assert reservations == []


async def test_provider_generated_oversized_id_never_reaches_recorder() -> None:
    """An unsupported successful provider ID becomes recovery-oriented evidence."""
    recorded: list[dict[str, Any]] = []
    session = _ProviderSession(
        _ProviderResponse({"id": "b" * 257, "status": "validating"})
    )

    def recorder(
        _dsn: str,
        _alias: str,
        provider_batch: Any,
        _observation_order: int,
    ) -> None:
        recorded.append(dict(provider_batch))

    client = DurableBatchAPIClient(
        "postgresql://example",
        lambda _alias: GatewayCredentials(
            url="https://gateway.example/v1",
            api_key="secret",
        ),
        lifecycle_recorder=recorder,
        observation_reserver=lambda _dsn: 1,
    )
    client._session = session

    with pytest.raises(GatewayError, match="persistence failed") as caught:
        await client.create_batch_job("file-1", "primary")

    assert caught.value.response_data["phase"] == "persistence"
    assert caught.value.response_data["error_type"] == "ValidationError"
    assert recorded == []
    assert session.post_urls == ["https://gateway.example/v1/batches"]


def test_operator_docs_define_current_state_and_tenant_trust_boundaries() -> None:
    """Lifecycle documentation must not overstate audit or tenant isolation."""
    documentation = (
        Path(__file__).parents[1] / "docs" / "remote-batch-lifecycle.md"
    ).read_text(encoding="utf-8")

    assert "current-state projection" in documentation
    assert "not an authorization or tenant-isolation boundary" in documentation
    assert "append-only audit history" in documentation
    assert "at most 128 characters" in documentation
    assert "at most 256 ASCII characters" in documentation


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("input_file_id", "file\x00shadow"),
        ("output_file_id", "o" * 257),
        ("error_file_id", "é"),
    ],
)
def test_remote_field_contract_rejects_invalid_optional_ids_before_database_access(
    monkeypatch: Any,
    field: str,
    value: str,
) -> None:
    """Every present provider file identifier is validated before PostgreSQL."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)

    with pytest.raises(ValueError, match=field):
        db.persist_remote_batch_state(
            "postgresql://example",
            "primary",
            {"id": "batch-1", field: value},
            observation_order=5,
        )

    assert driver.connections == []
    assert driver.executions == []


async def test_remote_field_contract_blocks_invalid_optional_id_before_custom_recorder() -> None:
    """A successful provider response cannot send an invalid file ID to a recorder."""
    recorded: list[dict[str, Any]] = []
    session = _ProviderSession(
        _ProviderResponse(
            {
                "id": "batch-1",
                "status": "completed",
                "output_file_id": "o" * 257,
            }
        )
    )

    def recorder(
        _dsn: str,
        _alias: str,
        provider_batch: Any,
        _observation_order: int,
    ) -> None:
        recorded.append(dict(provider_batch))

    client = DurableBatchAPIClient(
        "postgresql://example",
        lambda _alias: GatewayCredentials(
            url="https://gateway.example/v1",
            api_key="secret",
        ),
        lifecycle_recorder=recorder,
        observation_reserver=lambda _dsn: 1,
    )
    client._session = session

    with pytest.raises(GatewayError, match="persistence failed") as caught:
        await client.create_batch_job("file-1", "primary")

    assert caught.value.response_data["phase"] == "persistence"
    assert caught.value.response_data["error_type"] == "ValidationError"
    assert recorded == []
    assert session.post_urls == ["https://gateway.example/v1/batches"]


async def test_remote_field_contract_sanitizes_nul_text_before_custom_recorder() -> None:
    """Custom recorders receive safe endpoint and status text after remote success."""
    recorded: list[dict[str, Any]] = []
    session = _ProviderSession(
        _ProviderResponse(
            {
                "id": "batch-1",
                "endpoint": "/v1/responses\x00shadow",
                "status": "completed\x00shadow",
            }
        )
    )

    def recorder(
        _dsn: str,
        _alias: str,
        provider_batch: Any,
        _observation_order: int,
    ) -> None:
        recorded.append(dict(provider_batch))

    client = DurableBatchAPIClient(
        "postgresql://example",
        lambda _alias: GatewayCredentials(
            url="https://gateway.example/v1",
            api_key="secret",
        ),
        lifecycle_recorder=recorder,
        observation_reserver=lambda _dsn: 1,
    )
    client._session = session

    await client.create_batch_job("file-1", "primary")

    assert recorded[0]["endpoint"] is None
    assert recorded[0]["status"] == "unknown"
    assert "\x00" not in repr(recorded)


def test_remote_field_contract_normalizes_nul_optional_text(
    monkeypatch: Any,
) -> None:
    """NUL-bearing descriptive provider text cannot reach PostgreSQL columns."""
    driver = _Psycopg()
    monkeypatch.setattr(db, "psycopg", driver)

    snapshot = db.persist_remote_batch_state(
        "postgresql://example",
        "primary",
        {
            "id": "batch-1",
            "endpoint": "/v1/responses\x00shadow",
            "status": "completed\x00shadow",
        },
        observation_order=6,
    )

    assert snapshot["batch_endpoint"] is None
    assert snapshot["batch_status"] == "unknown"
    assert "\x00" not in repr(driver.executions[0][1])


def test_remote_field_contract_adds_database_checks() -> None:
    """The canonical schema constrains every stored remote resource identifier."""
    schema = _compact_sql(Path(db.SCHEMA_PATH).read_text(encoding="utf-8"))
    identifier_pattern = "'^[A-Za-z0-9][A-Za-z0-9._:-]{0,255}$'"

    assert (
        "remote_batch_id TEXT NOT NULL "
        "CHECK (LENGTH(remote_batch_id) BETWEEN 1 AND "
        f"{db.MAX_REMOTE_RESOURCE_ID_CHARACTERS}) "
        f"CHECK (remote_batch_id ~ {identifier_pattern})"
    ) in schema
    for field_name in ("input_file_id", "output_file_id", "error_file_id"):
        assert (
            f"{field_name} TEXT CHECK ( {field_name} IS NULL OR "
            f"{field_name} ~ {identifier_pattern} )"
        ) in schema, f"missing identifier CHECK for {field_name}"
