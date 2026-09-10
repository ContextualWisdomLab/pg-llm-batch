# SPDX-License-Identifier: Apache-2.0
"""Regression tests for pre-effect checkpoint monotonicity enforcement."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.checkpoint_store import CheckpointConflictError
from pg_llm_batch.result_application import apply_checkpointed_result_in_transaction
from pg_llm_batch.result_streaming import BatchResultCheckpoint, CheckpointedBatchResultRecord


def _checkpoint(*, record_count: int, digest: str) -> BatchResultCheckpoint:
    """Build one valid checkpoint in a single batch-wide result stream."""
    return BatchResultCheckpoint(
        schema_version=1,
        batch_id="batch-123",
        endpoint_alias="openrouter",
        file_kind="result",
        file_id="file-123",
        file_line_number=record_count,
        batch_line_count=record_count,
        record_count=record_count,
        prefix_sha256=digest,
    )


class _RegressionStore:
    """Expose a durable checkpoint ahead of the stale candidate under test."""

    def __init__(self, previous: BatchResultCheckpoint) -> None:
        self.previous = previous
        self.events: list[str] = []

    def load_in_transaction(
        self,
        _cursor: Any,
        _consumer_name: str,
        _batch_id: str,
        _endpoint_alias: str,
    ) -> BatchResultCheckpoint:
        """Return the already advanced durable predecessor."""
        self.events.append("load")
        return self.previous

    def save_in_transaction(
        self,
        _cursor: Any,
        consumer_name: str,
        checkpoint: BatchResultCheckpoint,
        *,
        expected_previous: BatchResultCheckpoint | None = None,
    ) -> BatchResultCheckpoint:
        """Model the built-in store's late checkpoint-regression rejection."""
        self.events.append("save")
        assert expected_previous == self.previous
        raise CheckpointConflictError(
            consumer_name,
            checkpoint.batch_id,
            "checkpoint_regression",
        )


def test_stale_checkpoint_regression_fails_before_caller_owned_effect() -> None:
    """Detect an already-visible count regression before running business logic."""
    previous = _checkpoint(record_count=2, digest="b" * 64)
    candidate = _checkpoint(record_count=1, digest="a" * 64)
    item = CheckpointedBatchResultRecord(
        batch_id=candidate.batch_id,
        file_kind=candidate.file_kind,
        record={"custom_id": "request-1"},
        checkpoint=candidate,
    )
    store = _RegressionStore(previous)

    def effect(_cursor: Any, _record: dict[str, Any]) -> None:
        store.events.append("effect")

    with pytest.raises(CheckpointConflictError) as caught:
        apply_checkpointed_result_in_transaction(
            object(),
            store,
            "result-writer",
            item,
            effect,
        )

    assert caught.value.reason == "checkpoint_regression"
    assert store.events == ["load"]
