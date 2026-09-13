# SPDX-License-Identifier: Apache-2.0
"""Regressions for asynchronous result-effect boundaries."""

from __future__ import annotations

import asyncio
import threading
from concurrent.futures import Future as ConcurrentFuture
from concurrent.futures import ThreadPoolExecutor
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


class _SuccessfulStore(_RecordingStore):
    """Confirm the requested checkpoint after one successful local effect."""

    def save_in_transaction(
        self,
        _cursor: object,
        _consumer_name: str,
        checkpoint: BatchResultCheckpoint,
        **_kwargs: object,
    ) -> BatchResultCheckpoint:
        """Record checkpoint persistence and return exact confirmation."""
        self.events.append("save")
        return checkpoint


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


class _ConcurrentFutureReturningEffect:
    """Return a thread-pool-style future from a synchronous callable."""

    def __init__(self) -> None:
        self.returned_future: ConcurrentFuture[None] = ConcurrentFuture()

    def __call__(self, _cursor: Any, _record: dict[str, Any]) -> ConcurrentFuture[None]:
        """Return pending concurrent work that must receive cancellation."""
        return self.returned_future


class _ExecutableCursor:
    """Record raw database operations performed through the scoped facade."""

    def __init__(self) -> None:
        self.calls: list[tuple[Any, ...]] = []

    def execute(self, *args: Any, **kwargs: Any) -> _ExecutableCursor:
        """Record one statement execution and mimic Psycopg's cursor return."""
        self.calls.append(("execute", args, kwargs))
        return self

    def executemany(self, *args: Any, **kwargs: Any) -> _ExecutableCursor:
        """Record one many-parameter execution and mimic cursor return."""
        self.calls.append(("executemany", args, kwargs))
        return self

    def fetchone(self) -> tuple[str]:
        """Return one deterministic row."""
        self.calls.append(("fetchone",))
        return ("one",)

    def fetchmany(self, size: int) -> list[tuple[str]]:
        """Return one deterministic bounded page."""
        self.calls.append(("fetchmany", size))
        return [("many",)]

    def fetchall(self) -> list[tuple[str]]:
        """Return one deterministic remainder."""
        self.calls.append(("fetchall",))
        return [("all",)]


class _RunningConcurrentFutureReturningEffect:
    """Keep one future running until the application seam has rejected it."""

    def __init__(self) -> None:
        self.executor = ThreadPoolExecutor(max_workers=1)
        self.started = threading.Event()
        self.release = threading.Event()
        self.returned_future: ConcurrentFuture[None] | None = None

    def __call__(self, cursor: Any, _record: dict[str, Any]) -> ConcurrentFuture[None]:
        """Return already-running work that attempts cursor use after rejection."""

        def _deferred_work() -> None:
            self.started.set()
            self.release.wait(timeout=2)
            cursor.execute("SELECT 1")

        self.returned_future = self.executor.submit(_deferred_work)
        assert self.started.wait(timeout=1)
        return self.returned_future

    def close(self) -> None:
        """Release and join the worker even when the regression assertion fails."""
        self.release.set()
        self.executor.shutdown(wait=True)


class _CrossThreadCursorEffect:
    """Attempt cursor use from another thread before the callback returns."""

    def __init__(self) -> None:
        self.worker_failure: Exception | None = None

    def __call__(self, cursor: Any, _record: dict[str, Any]) -> None:
        """Prove the live capability remains restricted to its owner thread."""

        def _worker() -> None:
            try:
                cursor.execute("SELECT cross_thread")
            except Exception as exc:
                self.worker_failure = exc

        worker = threading.Thread(target=_worker)
        worker.start()
        worker.join(timeout=1)
        assert not worker.is_alive()


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


def test_scoped_cursor_supports_sync_subset_then_revokes_on_return() -> None:
    """Synchronous DB-API work must succeed without leaking raw cursor authority."""
    store = _SuccessfulStore()
    raw_cursor = _ExecutableCursor()
    observed: dict[str, Any] = {}

    def effect(cursor: Any, _record: dict[str, Any]) -> None:
        observed["cursor"] = cursor
        assert cursor is not raw_cursor
        assert cursor.execute("SELECT 1", answer=42) is cursor
        assert cursor.executemany("SELECT %s", [(1,), (2,)]) is cursor
        assert cursor.fetchone() == ("one",)
        assert cursor.fetchmany(1) == [("many",)]
        assert cursor.fetchall() == [("all",)]

    outcome = apply_checkpointed_result_in_transaction(
        raw_cursor,
        store,
        "result-writer",
        _item(),
        effect,
    )

    assert outcome.applied is True
    assert store.events == ["load", "save"]
    assert [call[0] for call in raw_cursor.calls] == [
        "execute",
        "executemany",
        "fetchone",
        "fetchmany",
        "fetchall",
    ]
    with pytest.raises(ResultApplicationError) as revoked:
        observed["cursor"].execute("SELECT after_return")
    assert revoked.value.details == {"phase": "record_effect"}
    assert len(raw_cursor.calls) == 5


def test_scoped_cursor_rejects_cross_thread_use_while_callback_is_active() -> None:
    """A live scoped cursor must reject worker-thread use before raw I/O."""
    store = _SuccessfulStore()
    raw_cursor = _ExecutableCursor()
    effect = _CrossThreadCursorEffect()

    outcome = apply_checkpointed_result_in_transaction(
        raw_cursor,
        store,
        "result-writer",
        _item(),
        effect,
    )

    assert outcome.applied is True
    assert isinstance(effect.worker_failure, ResultApplicationError)
    assert effect.worker_failure.details == {"phase": "record_effect"}
    assert raw_cursor.calls == []
    assert store.events == ["load", "save"]


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
    """Rejected pending asyncio futures must not remain live after the call."""
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


def test_returned_concurrent_future_receives_cancellation_before_failure() -> None:
    """Rejected concurrent futures must receive cancellation before returning."""
    store = _RecordingStore()
    effect = _ConcurrentFutureReturningEffect()

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


def test_running_future_cannot_reuse_transaction_cursor_after_rejection() -> None:
    """Already-running deferred work must lose package-supplied cursor authority."""
    store = _RecordingStore()
    cursor = _ExecutableCursor()
    effect = _RunningConcurrentFutureReturningEffect()
    try:
        with pytest.raises(ResultApplicationError) as caught:
            apply_checkpointed_result_in_transaction(
                cursor,
                store,
                "result-writer",
                _item(),
                effect,
            )

        assert caught.value.details == {"phase": "record_effect"}
        assert effect.returned_future is not None
        effect.release.set()
        with pytest.raises(ResultApplicationError) as worker_failure:
            effect.returned_future.result(timeout=2)
        assert worker_failure.value.details == {"phase": "record_effect"}
        assert cursor.calls == []
        assert store.events == ["load"]
    finally:
        effect.close()
