# SPDX-License-Identifier: Apache-2.0
"""Test-first contract for bounded scheduler-independent provider reconciliation."""

from __future__ import annotations

from dataclasses import asdict

import pytest

from pg_llm_batch.reconciliation import (
    MAX_RECONCILIATION_JOBS,
    ReconciliationCandidate,
    reconcile_batch_candidates,
)


class FakeClient:
    """Minimal async Batch API seam used to observe reconciliation behavior."""

    def __init__(self, statuses, *, failure_batch_id: str | None = None) -> None:
        self.statuses = statuses
        self.failure_batch_id = failure_batch_id
        self.status_calls: list[tuple[str, str]] = []
        self.download_calls: list[tuple[str, str]] = []

    async def get_batch_status(self, batch_id: str, endpoint_alias: str):
        """Return one configured status or raise a confidential synthetic failure."""
        self.status_calls.append((batch_id, endpoint_alias))
        if batch_id == self.failure_batch_id:
            raise SecretNamedProviderError("provider-secret-sentinel")
        return dict(self.statuses[batch_id])

    async def download_results(self, batch_id: str, endpoint_alias: str):
        """Return content-bearing data that must not escape the worker report."""
        self.download_calls.append((batch_id, endpoint_alias))
        return {
            "success": True,
            "responses": [{"private": "provider-payload-sentinel"}],
            "errors": [],
            "response_count": 1,
            "error_count": 0,
        }


class SecretNamedProviderError(Exception):
    """Synthetic caller/provider exception whose type and message are private."""


@pytest.mark.asyncio
async def test_reconciliation_bounds_unique_work_and_discards_provider_payloads() -> None:
    """One pass processes only the bounded unique prefix and returns no payloads."""
    client = FakeClient(
        {
            "batch-a": {
                "status": "completed",
                "is_complete": True,
                "output_file_id": "file-a",
            },
            "batch-b": {"status": "in_progress", "is_complete": False},
            "batch-c": {"status": "in_progress", "is_complete": False},
        }
    )
    candidates = [
        ReconciliationCandidate("default", "batch-a"),
        ReconciliationCandidate("default", "batch-a"),
        ReconciliationCandidate("backup", "batch-b"),
        ReconciliationCandidate("backup", "batch-c"),
    ]

    report = await reconcile_batch_candidates(client, candidates, max_jobs=2)

    assert client.status_calls == [("batch-a", "default"), ("batch-b", "backup")]
    assert client.download_calls == [("batch-a", "default")]
    assert report.processed_count == 2
    assert report.retrieved_count == 1
    assert report.failed_count == 0
    assert [outcome.outcome for outcome in report.outcomes] == ["retrieved", "polled"]
    assert [outcome.batch_status for outcome in report.outcomes] == [
        "completed",
        "in_progress",
    ]
    assert "provider-payload-sentinel" not in repr(report)
    assert all("response" not in asdict(outcome) for outcome in report.outcomes)


@pytest.mark.asyncio
async def test_reconciliation_validates_selected_candidates_before_provider_io() -> None:
    """Malformed selected identity must fail before any provider operation begins."""
    client = FakeClient({"batch-a": {"status": "in_progress", "is_complete": False}})
    candidates = [
        ReconciliationCandidate("default", "batch-a"),
        ReconciliationCandidate("default", "bad id provider-secret-sentinel"),
    ]

    with pytest.raises(Exception) as exc_info:
        await reconcile_batch_candidates(client, candidates, max_jobs=2)

    assert client.status_calls == []
    assert client.download_calls == []
    assert "provider-secret-sentinel" not in str(exc_info.value)


@pytest.mark.asyncio
async def test_reconciliation_isolates_one_failure_with_finite_error_evidence() -> None:
    """One provider failure does not block later work or export dynamic diagnostics."""
    client = FakeClient(
        {
            "batch-b": {
                "status": "completed",
                "is_complete": True,
                "error_file_id": "file-error-b",
            }
        },
        failure_batch_id="batch-a",
    )
    candidates = [
        ReconciliationCandidate("default", "batch-a"),
        ReconciliationCandidate("backup", "batch-b"),
    ]

    report = await reconcile_batch_candidates(client, candidates, max_jobs=2)

    assert client.status_calls == [("batch-a", "default"), ("batch-b", "backup")]
    assert client.download_calls == [("batch-b", "backup")]
    assert report.processed_count == 2
    assert report.retrieved_count == 1
    assert report.failed_count == 1
    assert report.outcomes[0].outcome == "failed"
    assert report.outcomes[0].error_type == "_OTHER"
    assert report.outcomes[1].outcome == "retrieved"
    assert "SecretNamedProviderError" not in repr(report)
    assert "provider-secret-sentinel" not in repr(report)


@pytest.mark.asyncio
@pytest.mark.parametrize("max_jobs", [True, False, 0, -1, MAX_RECONCILIATION_JOBS + 1])
async def test_reconciliation_rejects_invalid_work_budget_before_provider_io(max_jobs) -> None:
    """The finite per-run work budget is a strict local authority boundary."""
    client = FakeClient({"batch-a": {"status": "in_progress", "is_complete": False}})

    with pytest.raises(Exception):
        await reconcile_batch_candidates(
            client,
            [ReconciliationCandidate("default", "batch-a")],
            max_jobs=max_jobs,
        )

    assert client.status_calls == []
    assert client.download_calls == []
