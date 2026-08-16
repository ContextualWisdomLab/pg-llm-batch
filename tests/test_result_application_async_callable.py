# SPDX-License-Identifier: Apache-2.0
"""Regressions for asynchronous result-effect boundaries."""

from __future__ import annotations

import asyncio
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
    """Represent an ordinary callable object with asynchronous invocation."""

    async def __call__(self, _cursor: Any, _record: dict[str, Any]) -> None:
        """Model deferred work that cannot share the caller transaction."""
        return None


class _StaticAsyncCallableEffect:
    """Represent an asynchronous static-method callable object."""

    @staticmethod
    async def __call__(_cursor: Any, _record: dict[str, Any]) -> None:
        """Model a descriptor-wrapped asynchronous effect."""
        return None


class _ClassAsyncCallableEffect:
    """Represent an asynchronous class-method callable object."""

    @classmethod
    async def __call__(
        cls,
        _cursor: Any,
        _record: dict[str, Any],
    ) -> None:
        """Model another descriptor-wrapped asynchronous effect."""
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


class _FutureReturningEffect:
    """Return scheduled-style deferred work from a synchronous callable."""

    def __init__(self) -> None:
        self.event_loop = asyncio.new_event_loop()
        self.returned_future: asyncio.Future[None] = self.event_loop.create_future()

    def __call__(self, _cursor: Any, _record: dict[str, Any]) -> asyncio.Future[None]:
        """Return a pending future that must not outlive bounded rejection."""
        return self.returned_future

    def close(self) -> None:
        """Release the isolated event loop used by this regression fixture."""
        self.event_loop.close()


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


@pytest.mark.parametrize(
    "effect_type",
    [
        _AsyncCallableEffect,
        _StaticAsyncCallableEffect,
        _ClassAsyncCallableEffect,
    ],
)
def test_async_callable_object_fails_before_checkpoint_store_access(
    effect_type: type[Any],
) -> None:
    """Every statically visible async ``__call__`` must fail before store work."""
    store = _RecordingStore()

    with pytest.raises(ValidationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(),
            store,
            "result-writer",
            _item(),
            effect_type(),
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


def test_returned_future_is_cancelled_before_bounded_failure() -> None:
    """Rejected pending futures must not remain live after the transaction call."""
    store = _RecordingStore()
    effect = _FutureReturningEffect()
    try:
        with pytest.raises(ResultApplicationError) as caught:
            apply_checkpointed_result_in_transaction(
                object(),
                store,
                "result-writer",
                _item(),
                effect,
            )

        assert caught.value.details == {"phase": "record_effect"}
        assert effect.returned_future.cancelled()
        assert store.events == ["load"]
    finally:
        effect.close()
