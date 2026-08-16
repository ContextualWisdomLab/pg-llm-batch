# SPDX-License-Identifier: Apache-2.0
"""Regression for asynchronous callable-object result effects."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.result_application import apply_checkpointed_result_in_transaction
from pg_llm_batch.result_streaming import (
    BatchResultCheckpoint,
    CheckpointedBatchResultRecord,
)


class _NoReadStore:
    """Record whether validation allowed checkpoint-store access."""

    def __init__(self) -> None:
        self.events: list[str] = []

    def load_in_transaction(self, *_args: object) -> None:
        """Record an unexpected load after an invalid effect boundary."""
        self.events.append("load")
        return None

    def save_in_transaction(self, *_args: object, **_kwargs: object) -> None:
        """Record an unexpected save after an invalid effect boundary."""
        self.events.append("save")
        return None


class _AsyncCallableEffect:
    """Represent a callable object whose invocation would return a coroutine."""

    async def __call__(self, _cursor: Any, _record: dict[str, Any]) -> None:
        """Model deferred work that cannot share the caller transaction."""
        return None


def _item() -> CheckpointedBatchResultRecord:
    """Build one valid result item for the focused validation boundary."""
    checkpoint = BatchResultCheckpoint(
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
    return CheckpointedBatchResultRecord(
        batch_id=checkpoint.batch_id,
        file_kind=checkpoint.file_kind,
        record={"custom_id": "request-1"},
        checkpoint=checkpoint,
    )


def test_async_callable_object_fails_before_checkpoint_store_access() -> None:
    """An async ``__call__`` cannot masquerade as a synchronous transaction effect."""
    store = _NoReadStore()

    with pytest.raises(ValidationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(),
            store,
            "result-writer",
            _item(),
            _AsyncCallableEffect(),
        )

    assert caught.value.details["field"] == "apply_record"
    assert caught.value.details["value"] == "<redacted>"
    assert store.events == []
