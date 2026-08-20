# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Atomic local application of streamed provider results with checkpoints.

The helper in this module deliberately owns no PostgreSQL connection and no
transaction lifecycle. A caller supplies a cursor that already belongs to the
transaction in which both the local business effect and durable checkpoint
advance must occur. The business callback receives a package-scoped,
same-thread cursor capability rather than the raw cursor. This permits atomicity
only for effects executed synchronously through that capability; it does not
create a distributed exactly-once guarantee for external APIs, queues, object
stores, other databases, or independently retained caller resources.
"""

from __future__ import annotations

import asyncio
import inspect
from concurrent.futures import Future as ConcurrentFuture
from dataclasses import dataclass
from threading import get_ident
from typing import Any, Callable, Mapping

from .checkpoint_store import CheckpointConflictError
from .exceptions import PgLlmBatchError, ValidationError
from .result_streaming import BatchResultCheckpoint, CheckpointedBatchResultRecord


class ResultApplicationError(PgLlmBatchError):
    """Report one bounded failure while applying a checkpointed result."""

    def __init__(self, phase: str) -> None:
        """Create fixed diagnostic evidence for one application phase."""
        super().__init__(
            message="Checkpointed result application failed",
            error_code="RESULT_APPLICATION_ERROR",
            details={"phase": phase},
        )


@dataclass(frozen=True)
class ResultApplicationOutcome:
    """Describe whether one local record effect was newly applied."""

    applied: bool
    checkpoint: BatchResultCheckpoint


class _ResultApplicationCursor:
    """Expose a revocable same-thread subset of caller transaction authority.

    The facade intentionally does not expose the underlying connection, commit,
    rollback, copy, streaming, or arbitrary attribute access. Synchronous record
    effects may execute statements and consume ordinary cursor results while the
    callback is active. The capability is revoked as soon as the callback
    returns or raises, and use from any other thread fails before the raw cursor
    is touched.
    """

    __slots__ = ("__active", "__cursor", "__owner_thread_id")

    def __init__(self, cursor: Any) -> None:
        """Bind one raw cursor to the constructing thread for one callback."""
        self.__cursor = cursor
        self.__owner_thread_id = get_ident()
        self.__active = True

    def _revoke(self) -> None:
        """Remove package-supplied cursor authority after callback completion."""
        self.__active = False

    def _assert_usable(self) -> None:
        """Reject expired or cross-thread use with bounded package evidence."""
        if not self.__active or get_ident() != self.__owner_thread_id:
            raise ResultApplicationError("record_effect") from None

    def execute(self, *args: Any, **kwargs: Any) -> _ResultApplicationCursor:
        """Execute one statement synchronously without returning the raw cursor."""
        self._assert_usable()
        self.__cursor.execute(*args, **kwargs)
        return self

    def executemany(self, *args: Any, **kwargs: Any) -> _ResultApplicationCursor:
        """Execute one parameter sequence without returning the raw cursor."""
        self._assert_usable()
        self.__cursor.executemany(*args, **kwargs)
        return self

    def fetchone(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch one result while this callback owns the scoped capability."""
        self._assert_usable()
        return self.__cursor.fetchone(*args, **kwargs)

    def fetchmany(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch a bounded result page while the scoped capability is active."""
        self._assert_usable()
        return self.__cursor.fetchmany(*args, **kwargs)

    def fetchall(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch remaining results while the scoped capability is active."""
        self._assert_usable()
        return self.__cursor.fetchall(*args, **kwargs)


def _redacted_validation_error(field: str, reason: str) -> ValidationError:
    """Build a validation error without retaining caller-controlled content."""
    return ValidationError(field=field, value="<redacted>", reason=reason)


def _checkpoint_primitive_type_error(checkpoint: BatchResultCheckpoint) -> str | None:
    """Return the first checkpoint field whose primitive type can execute behavior."""
    for field in (
        "batch_id",
        "endpoint_alias",
        "file_kind",
        "file_id",
        "prefix_sha256",
    ):
        if type(getattr(checkpoint, field)) is not str:
            return field
    for field in (
        "schema_version",
        "file_line_number",
        "batch_line_count",
        "record_count",
    ):
        if type(getattr(checkpoint, field)) is not int:
            return field
    return None


def _validate_item_and_effect(
    item: Any,
    apply_record: Any,
) -> CheckpointedBatchResultRecord:
    """Validate the local application boundary before store or callback work."""
    if type(item) is not CheckpointedBatchResultRecord:
        raise _redacted_validation_error(
            "item", "must be an exact checkpointed batch result record"
        )
    checkpoint = item.checkpoint
    if type(checkpoint) is not BatchResultCheckpoint:
        raise _redacted_validation_error(
            "item.checkpoint", "must be an exact batch result checkpoint"
        )
    checkpoint_field = _checkpoint_primitive_type_error(checkpoint)
    if checkpoint_field is not None:
        raise _redacted_validation_error(
            f"item.checkpoint.{checkpoint_field}",
            "must use an exact built-in primitive type",
        )
    if type(item.batch_id) is not str:
        raise _redacted_validation_error(
            "item.batch_id", "must be an exact built-in string"
        )
    if type(item.file_kind) is not str:
        raise _redacted_validation_error(
            "item.file_kind", "must be an exact built-in string"
        )
    if not callable(apply_record):
        raise _redacted_validation_error("apply_record", "must be callable")
    static_call = inspect.getattr_static(apply_record, "__call__", None)
    if isinstance(static_call, (staticmethod, classmethod)):
        static_call = static_call.__func__
    if inspect.iscoroutinefunction(apply_record) or inspect.iscoroutinefunction(
        static_call
    ):
        raise _redacted_validation_error(
            "apply_record", "must complete synchronously in the caller transaction"
        )
    if item.batch_id != checkpoint.batch_id:
        raise _redacted_validation_error(
            "item.batch_id", "must match the checkpoint batch identity"
        )
    if item.file_kind != checkpoint.file_kind:
        raise _redacted_validation_error(
            "item.file_kind", "must match the checkpoint file kind"
        )
    if type(item.record) is not dict:
        raise _redacted_validation_error("item.record", "must be an exact JSON object")
    return item


def _snapshot_checkpoint(checkpoint: BatchResultCheckpoint) -> BatchResultCheckpoint:
    """Copy validated checkpoint primitives into package-owned authority."""
    return BatchResultCheckpoint(
        schema_version=checkpoint.schema_version,
        batch_id=checkpoint.batch_id,
        endpoint_alias=checkpoint.endpoint_alias,
        file_kind=checkpoint.file_kind,
        file_id=checkpoint.file_id,
        file_line_number=checkpoint.file_line_number,
        batch_line_count=checkpoint.batch_line_count,
        record_count=checkpoint.record_count,
        prefix_sha256=checkpoint.prefix_sha256,
    )


def _snapshot_item_and_effect(
    item: Any,
    apply_record: Any,
) -> CheckpointedBatchResultRecord:
    """Validate then detach application authority from caller-owned containers."""
    candidate = _validate_item_and_effect(item, apply_record)
    snapshot = CheckpointedBatchResultRecord(
        batch_id=candidate.batch_id,
        file_kind=candidate.file_kind,
        record=candidate.record.copy(),
        checkpoint=_snapshot_checkpoint(candidate.checkpoint),
    )
    return _validate_item_and_effect(snapshot, apply_record)


def apply_checkpointed_result_in_transaction(
    cursor: Any,
    checkpoint_store: Any,
    consumer_name: str,
    item: CheckpointedBatchResultRecord,
    apply_record: Callable[[Any, Mapping[str, Any]], None],
) -> ResultApplicationOutcome:
    """Apply one result and advance its checkpoint in the caller's transaction.

    The item, checkpoint, checkpoint primitive fields, JSON object, loaded
    predecessor, and save confirmation must use exact package-owned or built-in
    types. Subclasses are rejected before their behavior-bearing comparison or
    attribute hooks can execute, so caller-controlled subclass code cannot
    disclose diagnostics or forge durable confirmation. Validated item and
    checkpoint authority is copied before any store or callback work; a second
    checkpoint copy is handed to the save hook so hook-side mutation cannot
    change the package-owned comparison and outcome authority.

    The durable predecessor is loaded and validated before the local effect. An
    exact replay returns without re-running the effect, while a count regression
    is rejected before caller-owned business logic. Fresh work invokes
    ``apply_record`` with a package-scoped cursor facade on the supplied
    transaction and advances the checkpoint only after that callback completes
    synchronously and returns ``None``. The facade permits ordinary synchronous
    ``execute``/``executemany`` and ``fetch*`` operations only on the callback's
    original thread. It is revoked on every callback exit, so deferred work
    cannot retain package-supplied transaction cursor authority after return.
    This is an authority boundary, not a claim that Python can forcibly
    terminate arbitrary already-running Futures, Tasks, threads, or other
    caller-retained resources.

    Statically visible asynchronous callables, including static-method and
    class-method descriptors, are rejected before checkpoint-store access. A raw
    coroutine returned by an otherwise synchronous callable is closed, and
    returned pending :class:`asyncio.Future` or
    :class:`concurrent.futures.Future` work receives best-effort cancellation
    after the scoped cursor has already been revoked. Any non-``None`` return is
    rejected as a record-effect failure. The checkpoint store must then confirm
    the exact requested checkpoint before success is reported. The caller
    remains responsible for committing or rolling back the surrounding
    transaction.

    ``CheckpointConflictError`` is intentionally preserved as the stable retry
    signal from both checkpoint load and save operations. All other
    store/callback failures are replaced with a fixed phase-only package error
    after their exception scope has ended, preventing implicit traceback context
    from retaining provider or database diagnostics.
    """
    candidate = _snapshot_item_and_effect(item, apply_record)

    load_failure: ResultApplicationError | None = None
    previous: BatchResultCheckpoint | None = None
    try:
        previous = checkpoint_store.load_in_transaction(
            cursor,
            consumer_name,
            candidate.batch_id,
            candidate.checkpoint.endpoint_alias,
        )
    except CheckpointConflictError:
        raise
    except Exception:
        load_failure = ResultApplicationError("checkpoint_load")
    if load_failure is not None:
        raise load_failure from None
    if previous is not None:
        if type(previous) is not BatchResultCheckpoint:
            raise ResultApplicationError("checkpoint_load") from None
        if _checkpoint_primitive_type_error(previous) is not None:
            raise ResultApplicationError("checkpoint_load") from None
        if (
            previous.batch_id != candidate.checkpoint.batch_id
            or previous.endpoint_alias != candidate.checkpoint.endpoint_alias
            or previous.file_kind != candidate.checkpoint.file_kind
            or previous.file_id != candidate.checkpoint.file_id
        ):
            raise ResultApplicationError("checkpoint_load") from None

    if previous == candidate.checkpoint:
        return ResultApplicationOutcome(applied=False, checkpoint=candidate.checkpoint)
    if previous is not None and (
        candidate.checkpoint.record_count <= previous.record_count
        or candidate.checkpoint.batch_line_count <= previous.batch_line_count
    ):
        raise CheckpointConflictError(
            consumer_name,
            candidate.batch_id,
            "checkpoint_regression",
        ) from None

    effect_failure: ResultApplicationError | None = None
    effect_cursor = _ResultApplicationCursor(cursor)
    try:
        try:
            effect_result = apply_record(effect_cursor, candidate.record)
        finally:
            effect_cursor._revoke()
        if inspect.iscoroutine(effect_result):
            effect_result.close()
        elif isinstance(effect_result, (asyncio.Future, ConcurrentFuture)):
            effect_result.cancel()
        if effect_result is not None:
            effect_failure = ResultApplicationError("record_effect")
    except Exception:
        effect_failure = ResultApplicationError("record_effect")
    if effect_failure is not None:
        raise effect_failure from None

    save_failure: ResultApplicationError | None = None
    try:
        checkpoint_to_save = _snapshot_checkpoint(candidate.checkpoint)
        saved_checkpoint = checkpoint_store.save_in_transaction(
            cursor,
            consumer_name,
            checkpoint_to_save,
            expected_previous=previous,
        )
        if type(saved_checkpoint) is not BatchResultCheckpoint:
            save_failure = ResultApplicationError("checkpoint_save")
        elif _checkpoint_primitive_type_error(saved_checkpoint) is not None:
            save_failure = ResultApplicationError("checkpoint_save")
        elif saved_checkpoint != candidate.checkpoint:
            save_failure = ResultApplicationError("checkpoint_save")
    except CheckpointConflictError:
        raise
    except Exception:
        save_failure = ResultApplicationError("checkpoint_save")
    if save_failure is not None:
        raise save_failure from None

    return ResultApplicationOutcome(applied=True, checkpoint=candidate.checkpoint)


__all__ = [
    "ResultApplicationError",
    "ResultApplicationOutcome",
    "apply_checkpointed_result_in_transaction",
]
