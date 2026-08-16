# SPDX-License-Identifier: Apache-2.0
"""Regressions for asynchronous result-effect boundaries."""

from __future__ import annotations

from typing import Any

import pytest

from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.result_application import (
    ResultApplicationError,
    apply_checkpointed_result_in_transaction,
)
from pg_llm_batch.result_streaming import (
    BatchResultCheckpoint,
    CheckpointedBatchResultRecord,
)


class _RecordingStore:
    """Record whether the application seam reached checkpoint storage."""

    def __init__(self) -> None:
        self.events: list[str] = []

    def load_in_transaction(self, *_args: object) -> None:
        """Record checkpoint loading and provide no durable predecessor."""
        self.events.append("load")
        return None

    def save_in_transaction(self, *_args: object, **_kwargs: object) -> None:
        """Record an unexpected checkpoint save after an invalid effect."""
        self.events.append("save")
        return None


class _AsyncCallableEffect:
    """Represent a callable object whose invocation would return a coroutine."""

    async def __call__(self, _cursor: Any, _record: dict[str, Any]) -> None:
        """Model deferred work that cannot share the caller transaction."""
        return None


class _CoroutineReturningEffect:
    """Return a raw coroutine from an otherwise synchronous callable."""

    def __init__(self) -> None:
        self.returned_coroutine: Any = None

    def __call__(self, _cursor: Any, _record: dict[str, Any]) -> Any:
        """Create deferred work whose frame retains caller-owned arguments."""

        async def _deferred_work() -> None:
            return None

        self.returned_coroutine = _deferred_work()
        return self.returned_coroutine


def _item() -> CheckpointedBatchResultRecord:
    """Build one valid result item for the focused effect boundary."""
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
    store = _RecordingStore()

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


def test_returned_coroutine_is_closed_before_bounded_failure() -> None:
    """Rejected deferred work must not retain cursor or result data until GC."""
    store = _RecordingStore()
    effect = _CoroutineReturningEffect()

    with pytest.raises(ResultApplicationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(),
            store,
            "result-writer",
            _item(),
            effect,
        )

    assert caught.value.details == {"phase": "record_effect"}
    assert effect.returned_coroutine.cr_frame is None
    assert store.events == ["load"]
