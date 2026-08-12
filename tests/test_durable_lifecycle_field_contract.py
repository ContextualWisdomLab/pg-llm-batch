# SPDX-License-Identifier: Apache-2.0
"""Regression tests for durable provider lifecycle field validation."""

from __future__ import annotations

from datetime import datetime, timezone

import pytest

from pg_llm_batch import db


class _NoDatabaseIO:
    """Fail if invalid provider lifecycle fields reach PostgreSQL acquisition."""

    def __init__(self) -> None:
        self.connections: list[str] = []

    def connect(self, dsn: str):
        """Record an unexpected connection attempt and fail the test immediately."""
        self.connections.append(dsn)
        raise AssertionError("invalid lifecycle fields reached PostgreSQL")


def _provider_batch(*, status: object, endpoint: object) -> dict[str, object]:
    """Build one otherwise-valid provider lifecycle observation."""
    return {
        "id": "batch_contract_1",
        "status": status,
        "endpoint": endpoint,
        "request_counts": {"total": 1, "completed": 0, "failed": 0},
    }


@pytest.mark.parametrize(
    "status",
    [None, "future_state", "COMPLETED", "x" * 65, "completed\x00secret"],
)
def test_persistence_rejects_unsupported_status_before_database_io(
    monkeypatch: pytest.MonkeyPatch,
    status: object,
) -> None:
    """Reject unsupported provider status evidence before PostgreSQL mutation."""
    driver = _NoDatabaseIO()
    monkeypatch.setattr(db, "psycopg", driver)

    with pytest.raises(ValueError, match="batch_status is not a supported provider status") as exc:
        db.persist_remote_batch_state(
            "postgresql://should-not-connect",
            "default",
            _provider_batch(status=status, endpoint="/v1/responses"),
            1,
            observed_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
        )

    assert str(status) not in str(exc.value)
    assert driver.connections == []


@pytest.mark.parametrize(
    "endpoint",
    [
        None,
        "/v1/future-endpoint",
        "/v1/chat/completions?debug=1",
        "/v1/../chat/completions",
        "/v1/responses\x00secret",
    ],
)
def test_persistence_rejects_unsupported_endpoint_before_database_io(
    monkeypatch: pytest.MonkeyPatch,
    endpoint: object,
) -> None:
    """Reject unsupported provider endpoint evidence before PostgreSQL mutation."""
    driver = _NoDatabaseIO()
    monkeypatch.setattr(db, "psycopg", driver)

    with pytest.raises(
        ValueError,
        match="batch_endpoint is not a supported provider batch endpoint",
    ) as exc:
        db.persist_remote_batch_state(
            "postgresql://should-not-connect",
            "default",
            _provider_batch(status="validating", endpoint=endpoint),
            1,
            observed_at=datetime(2026, 8, 13, tzinfo=timezone.utc),
        )

    assert str(endpoint) not in str(exc.value)
    assert driver.connections == []


def test_official_openai_statuses_and_endpoints_normalize_deterministically() -> None:
    """Accept the currently documented OpenAI Batch status and endpoint sets."""
    statuses = (
        "validating",
        "failed",
        "in_progress",
        "finalizing",
        "completed",
        "expired",
        "cancelling",
        "cancelled",
    )
    endpoints = (
        "/v1/responses",
        "/v1/chat/completions",
        "/v1/embeddings",
        "/v1/completions",
        "/v1/moderations",
    )
    observed = datetime(2026, 8, 13, tzinfo=timezone.utc)

    for index, status in enumerate(statuses, start=1):
        endpoint = endpoints[(index - 1) % len(endpoints)]
        snapshot, _ = db._normalize_remote_batch_snapshot(
            "standalone",
            "default",
            _provider_batch(status=status, endpoint=endpoint),
            index,
            observed,
        )
        assert snapshot["batch_status"] == status
        assert snapshot["batch_endpoint"] == endpoint
        assert (snapshot["terminal_at"] is observed) is (
            status in {"failed", "completed", "expired", "cancelled"}
        )
