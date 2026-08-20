# SPDX-License-Identifier: Apache-2.0
"""Regression tests for stable result-application input authority."""

from __future__ import annotations

from typing import Any

import pg_llm_batch.result_application as result_application
from pg_llm_batch.result_application import (
    ResultApplicationOutcome,
    apply_checkpointed_result_in_transaction,
)
from pg_llm_batch.result_streaming import (
    BatchResultCheckpoint,
    CheckpointedBatchResultRecord,
)


def _checkpoint() -> BatchResultCheckpoint:
    """Build one valid checkpoint for the mutation-race regression."""
    return BatchResultCheckpoint(
        schema_version=1,
        batch_id="batch-123",
        endpoint_alias="openrouter",
        file_kind="result",
        file_id="file-123",
        file_line_number=1,
        batch_line_count=1,
        record_count=1,
        prefix_sha256="a" * 64,
    )


class _MutatingLoadStore:
    """Mutate caller-owned checkpoint slots after the package validates them."""

    def __init__(self, item: CheckpointedBatchResultRecord) -> None:
        self.item = item
        self.saved_checkpoint: BatchResultCheckpoint | None = None

    def load_in_transaction(
        self,
        _cursor: Any,
        _consumer_name: str,
        batch_id: str,
        endpoint_alias: str,
    ) -> None:
        """Prove load used validated identity, then mutate caller-owned state."""
        assert batch_id == "batch-123"
        assert endpoint_alias == "openrouter"
        object.__setattr__(self.item.checkpoint, "batch_id", "batch-mutated")
        return None

    def save_in_transaction(
        self,
        _cursor: Any,
        _consumer_name: str,
        checkpoint: BatchResultCheckpoint,
        *,
        expected_previous: BatchResultCheckpoint | None = None,
    ) -> BatchResultCheckpoint:
        """Record the checkpoint authority supplied after local application."""
        assert expected_previous is None
        self.saved_checkpoint = checkpoint
        return checkpoint


def test_result_application_uses_validated_checkpoint_snapshot_after_load_hook() -> None:
    """A store hook cannot change the checkpoint applied after validation."""
    checkpoint = _checkpoint()
    item = CheckpointedBatchResultRecord(
        batch_id=checkpoint.batch_id,
        file_kind=checkpoint.file_kind,
        record={"custom_id": "request-1"},
        checkpoint=checkpoint,
    )
    store = _MutatingLoadStore(item)
    seen_records: list[dict[str, Any]] = []

    outcome = apply_checkpointed_result_in_transaction(
        object(),
        store,
        "result-writer",
        item,
        lambda _cursor, record: seen_records.append(dict(record)),
    )

    assert checkpoint.batch_id == "batch-mutated"
    assert store.saved_checkpoint == _checkpoint()
    assert seen_records == [{"custom_id": "request-1"}]
    assert outcome == ResultApplicationOutcome(
        applied=True,
        checkpoint=_checkpoint(),
    )


def test_result_application_does_not_reread_caller_slots_after_validation(
    monkeypatch: Any,
) -> None:
    """Post-validation caller mutation cannot replace snapshotted authority."""
    checkpoint = _checkpoint()
    item = CheckpointedBatchResultRecord(
        batch_id=checkpoint.batch_id,
        file_kind=checkpoint.file_kind,
        record={"custom_id": "request-1"},
        checkpoint=checkpoint,
    )
    store = _MutatingLoadStore(item)
    seen_records: list[dict[str, Any]] = []
    original_validator = result_application._validate_item_and_effect
    validation_calls = 0

    def validate_then_mutate(
        candidate: Any,
        apply_record: Any,
    ) -> CheckpointedBatchResultRecord:
        nonlocal validation_calls
        validated = original_validator(candidate, apply_record)
        validation_calls += 1
        if validation_calls == 1:
            object.__setattr__(checkpoint, "batch_id", "batch-mutated")
        return validated

    monkeypatch.setattr(
        result_application,
        "_validate_item_and_effect",
        validate_then_mutate,
    )

    outcome = apply_checkpointed_result_in_transaction(
        object(),
        store,
        "result-writer",
        item,
        lambda _cursor, record: seen_records.append(dict(record)),
    )

    assert validation_calls == 1
    assert checkpoint.batch_id == "batch-mutated"
    assert store.saved_checkpoint == _checkpoint()
    assert seen_records == [{"custom_id": "request-1"}]
    assert outcome == ResultApplicationOutcome(
        applied=True,
        checkpoint=_checkpoint(),
    )
