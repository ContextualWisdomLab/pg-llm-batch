# SPDX-License-Identifier: Apache-2.0
"""Regression test for durable checkpoint save confirmation."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.result_application import (
    ResultApplicationError,
    apply_checkpointed_result_in_transaction,
)
from pg_llm_batch.result_streaming import (
    BatchResultCheckpoint,
    CheckpointedBatchResultRecord,
)


def _checkpoint(*, record_count: int, digest: str) -> BatchResultCheckpoint:
    """Build one valid checkpoint with deterministic position evidence."""
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


class _MismatchedSaveStore:
    """Simulate a broken adapter that does not confirm the requested checkpoint."""

    def __init__(self, returned_checkpoint: BatchResultCheckpoint) -> None:
        self.returned_checkpoint = returned_checkpoint

    def load_in_transaction(
        self,
        _cursor: Any,
        _consumer_name: str,
        _batch_id: str,
        _endpoint_alias: str,
    ) -> None:
        """Report no durable predecessor for the fresh application."""
        return None

    def save_in_transaction(
        self,
        _cursor: Any,
        _consumer_name: str,
        _checkpoint: BatchResultCheckpoint,
        *,
        expected_previous: BatchResultCheckpoint | None = None,
    ) -> BatchResultCheckpoint:
        """Return a different durable identity to expose missing confirmation checks."""
        assert expected_previous is None
        return self.returned_checkpoint


def test_mismatched_checkpoint_save_confirmation_fails_closed() -> None:
    """Success must require the store to confirm the exact requested checkpoint."""
    candidate = _checkpoint(record_count=1, digest="a" * 64)
    mismatched = _checkpoint(record_count=2, digest="b" * 64)
    item = CheckpointedBatchResultRecord(
        batch_id=candidate.batch_id,
        file_kind=candidate.file_kind,
        record={"custom_id": "request-1"},
        checkpoint=candidate,
    )

    with pytest.raises(ResultApplicationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(),
            _MismatchedSaveStore(mismatched),
            "result-writer",
            item,
            lambda _cursor, _record: None,
        )

    assert caught.value.details == {"phase": "checkpoint_save"}
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
