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
        """Create fixed diagnostic evidence for one public application phase."""
        super().__init__(
            message="Checkpointed result application failed",
            error_code="RESULT_APPLICATION_ERROR",
            details={"phase": phase},
        )


@dataclass(frozen=True)
class ResultApplicationOutcome:
    """Preserve the released result-application outcome contract.

    ``applied`` and ``checkpoint`` are historical public dataclass fields. They
    remain at this compatibility boundary because changing dataclass field names
    would alter construction, introspection, and ``dataclasses.asdict`` output.
    New package-owned implementation code uses the semantic
    :class:`_SemanticResultApplicationOutcome` instead.
    """

    applied: bool
    checkpoint: BatchResultCheckpoint

    @property
    def record_applied(self) -> bool:
        """Expose the semantic applied-state name to new callers."""
        return self.applied

    @property
    def result_checkpoint(self) -> BatchResultCheckpoint:
        """Expose the semantic checkpoint name to new callers."""
        return self.checkpoint


@dataclass(frozen=True)
class _SemanticResultApplicationOutcome:
    """Represent package-owned result-application state with semantic names."""

    record_applied: bool
    result_checkpoint: BatchResultCheckpoint


class _ResultApplicationCursor:
    """Expose a revocable same-thread subset of caller transaction authority.

    The facade intentionally does not expose the underlying connection, commit,
    rollback, copy, streaming, or arbitrary attribute access. Synchronous record
    effects may execute statements and consume ordinary cursor results while the
    callback is active. The capability is revoked as soon as the callback
    returns or raises, and use from any other thread fails before the raw cursor
    is touched.
    """

    __slots__ = (
        "__capability_active",
        "__transaction_cursor",
        "__owner_thread_id",
    )

    def __init__(self, transaction_cursor: Any) -> None:
        """Bind one raw cursor to the constructing thread for one callback."""
        self.__transaction_cursor = transaction_cursor
        self.__owner_thread_id = get_ident()
        self.__capability_active = True

    def _revoke_cursor_capability(self) -> None:
        """Remove package-supplied cursor authority after callback completion."""
        self.__capability_active = False

    def _assert_usable(self) -> None:
        """Reject expired or cross-thread use with bounded package evidence."""
        if not self.__capability_active or get_ident() != self.__owner_thread_id:
            raise ResultApplicationError("record_effect") from None

    def execute(self, *args: Any, **kwargs: Any) -> _ResultApplicationCursor:
        """Execute one statement synchronously without returning the raw cursor."""
        self._assert_usable()
        self.__transaction_cursor.execute(*args, **kwargs)
        return self

    def executemany(self, *args: Any, **kwargs: Any) -> _ResultApplicationCursor:
        """Execute one parameter sequence without returning the raw cursor."""
        self._assert_usable()
        self.__transaction_cursor.executemany(*args, **kwargs)
        return self

    def fetchone(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch one result while this callback owns the scoped capability."""
        self._assert_usable()
        return self.__transaction_cursor.fetchone(*args, **kwargs)

    def fetchmany(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch a bounded result page while the scoped capability is active."""
        self._assert_usable()
        return self.__transaction_cursor.fetchmany(*args, **kwargs)

    def fetchall(self, *args: Any, **kwargs: Any) -> Any:
        """Fetch remaining results while the scoped capability is active."""
        self._assert_usable()
        return self.__transaction_cursor.fetchall(*args, **kwargs)


def _redacted_validation_error(
    field_name: str,
    validation_reason: str,
) -> ValidationError:
    """Build a validation error without retaining caller-controlled content."""
    return ValidationError(
        field=field_name,
        value="<redacted>",
        reason=validation_reason,
    )


def _checkpoint_primitive_type_error(
    result_checkpoint: BatchResultCheckpoint,
) -> str | None:
    """Return the first checkpoint field whose primitive type can execute behavior."""
    for checkpoint_field_name in (
        "batch_id",
        "endpoint_alias",
        "file_kind",
        "file_id",
        "prefix_sha256",
    ):
        if type(getattr(result_checkpoint, checkpoint_field_name)) is not str:
            return checkpoint_field_name
    for checkpoint_field_name in (
        "schema_version",
        "file_line_number",
        "batch_line_count",
        "record_count",
    ):
        if type(getattr(result_checkpoint, checkpoint_field_name)) is not int:
            return checkpoint_field_name
    return None


def _validate_item_and_effect(
    checkpointed_record: Any,
    record_effect: Any,
) -> CheckpointedBatchResultRecord:
    """Validate the local application boundary before store or callback work."""
    if type(checkpointed_record) is not CheckpointedBatchResultRecord:
        raise _redacted_validation_error(
            "item", "must be an exact checkpointed batch result record"
        )
    result_checkpoint = checkpointed_record.checkpoint
    if type(result_checkpoint) is not BatchResultCheckpoint:
        raise _redacted_validation_error(
            "item.checkpoint", "must be an exact batch result checkpoint"
        )
    checkpoint_field_name = _checkpoint_primitive_type_error(result_checkpoint)
    if checkpoint_field_name is not None:
        raise _redacted_validation_error(
            f"item.checkpoint.{checkpoint_field_name}",
            "must use an exact built-in primitive type",
        )
    if type(checkpointed_record.batch_id) is not str:
        raise _redacted_validation_error(
            "item.batch_id", "must be an exact built-in string"
        )
    if type(checkpointed_record.file_kind) is not str:
        raise _redacted_validation_error(
            "item.file_kind", "must be an exact built-in string"
        )
    if not callable(record_effect):
        raise _redacted_validation_error("apply_record", "must be callable")
    static_call = inspect.getattr_static(record_effect, "__call__", None)
    if isinstance(static_call, (staticmethod, classmethod)):
        static_call = static_call.__func__
    if inspect.iscoroutinefunction(record_effect) or inspect.iscoroutinefunction(
        static_call
    ):
        raise _redacted_validation_error(
            "apply_record", "must complete synchronously in the caller transaction"
        )
    if checkpointed_record.batch_id != result_checkpoint.batch_id:
        raise _redacted_validation_error(
            "item.batch_id", "must match the checkpoint batch identity"
        )
    if checkpointed_record.file_kind != result_checkpoint.file_kind:
        raise _redacted_validation_error(
            "item.file_kind", "must match the checkpoint file kind"
        )
    if type(checkpointed_record.record) is not dict:
        raise _redacted_validation_error("item.record", "must be an exact JSON object")
    return checkpointed_record


def _apply_checkpointed_record_in_transaction(
    transaction_cursor: Any,
    checkpoint_store: Any,
    consumer_name: str,
    checkpointed_record: CheckpointedBatchResultRecord,
    record_effect: Callable[[Any, Mapping[str, Any]], None],
) -> _SemanticResultApplicationOutcome:
    """Apply one semantic checkpointed record within the caller transaction."""
    validated_record = _validate_item_and_effect(checkpointed_record, record_effect)

    checkpoint_load_failure: ResultApplicationError | None = None
    previous_checkpoint: BatchResultCheckpoint | None = None
    try:
        previous_checkpoint = checkpoint_store.load_in_transaction(
            transaction_cursor,
            consumer_name,
            validated_record.batch_id,
            validated_record.checkpoint.endpoint_alias,
        )
    except CheckpointConflictError:
        raise
    except Exception:
        checkpoint_load_failure = ResultApplicationError("checkpoint_load")
    if checkpoint_load_failure is not None:
        raise checkpoint_load_failure from None
    if previous_checkpoint is not None:
        if type(previous_checkpoint) is not BatchResultCheckpoint:
            raise ResultApplicationError("checkpoint_load") from None
        if _checkpoint_primitive_type_error(previous_checkpoint) is not None:
            raise ResultApplicationError("checkpoint_load") from None
        if (
            previous_checkpoint.batch_id != validated_record.checkpoint.batch_id
            or previous_checkpoint.endpoint_alias
            != validated_record.checkpoint.endpoint_alias
            or previous_checkpoint.file_kind != validated_record.checkpoint.file_kind
            or previous_checkpoint.file_id != validated_record.checkpoint.file_id
        ):
            raise ResultApplicationError("checkpoint_load") from None

    if previous_checkpoint == validated_record.checkpoint:
        return _SemanticResultApplicationOutcome(
            record_applied=False,
            result_checkpoint=validated_record.checkpoint,
        )
    if previous_checkpoint is not None and (
        validated_record.checkpoint.record_count <= previous_checkpoint.record_count
        or validated_record.checkpoint.batch_line_count
        <= previous_checkpoint.batch_line_count
    ):
        raise CheckpointConflictError(
            consumer_name,
            validated_record.batch_id,
            "checkpoint_regression",
        ) from None

    record_effect_failure: ResultApplicationError | None = None
    record_effect_cursor = _ResultApplicationCursor(transaction_cursor)
    try:
        try:
            record_effect_result = record_effect(
                record_effect_cursor,
                validated_record.record,
            )
        finally:
            record_effect_cursor._revoke_cursor_capability()
        if inspect.iscoroutine(record_effect_result):
            record_effect_result.close()
        elif isinstance(record_effect_result, (asyncio.Future, ConcurrentFuture)):
            record_effect_result.cancel()
        if record_effect_result is not None:
            record_effect_failure = ResultApplicationError("record_effect")
    except Exception:
        record_effect_failure = ResultApplicationError("record_effect")
    if record_effect_failure is not None:
        raise record_effect_failure from None

    checkpoint_save_failure: ResultApplicationError | None = None
    try:
        saved_checkpoint = checkpoint_store.save_in_transaction(
            transaction_cursor,
            consumer_name,
            validated_record.checkpoint,
            expected_previous=previous_checkpoint,
        )
        if type(saved_checkpoint) is not BatchResultCheckpoint:
            checkpoint_save_failure = ResultApplicationError("checkpoint_save")
        elif _checkpoint_primitive_type_error(saved_checkpoint) is not None:
            checkpoint_save_failure = ResultApplicationError("checkpoint_save")
        elif saved_checkpoint != validated_record.checkpoint:
            checkpoint_save_failure = ResultApplicationError("checkpoint_save")
    except CheckpointConflictError:
        raise
    except Exception:
        checkpoint_save_failure = ResultApplicationError("checkpoint_save")
    if checkpoint_save_failure is not None:
        raise checkpoint_save_failure from None

    return _SemanticResultApplicationOutcome(
        record_applied=True,
        result_checkpoint=validated_record.checkpoint,
    )


def apply_checkpointed_result_in_transaction(
    cursor: Any,
    checkpoint_store: Any,
    consumer_name: str,
    item: CheckpointedBatchResultRecord,
    apply_record: Callable[[Any, Mapping[str, Any]], None],
) -> ResultApplicationOutcome:
    """Apply one result and advance its checkpoint in the caller's transaction.

    ``cursor``, ``item``, and ``apply_record`` are historical released keyword
    names retained only at this compatibility boundary. Internally they are
    translated immediately to ``transaction_cursor``, ``checkpointed_record``,
    and ``record_effect`` so package-owned implementation vocabulary remains
    semantically specific.

    The item, checkpoint, checkpoint primitive fields, JSON object, loaded
    predecessor, and save confirmation must use exact package-owned or built-in
    types. Subclasses are rejected before their behavior-bearing comparison or
    attribute hooks can execute, so caller-controlled subclass code cannot
    disclose diagnostics or forge durable confirmation.

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
    semantic_outcome = _apply_checkpointed_record_in_transaction(
        transaction_cursor=cursor,
        checkpoint_store=checkpoint_store,
        consumer_name=consumer_name,
        checkpointed_record=item,
        record_effect=apply_record,
    )
    return ResultApplicationOutcome(
        applied=semantic_outcome.record_applied,
        checkpoint=semantic_outcome.result_checkpoint,
    )


__all__ = [
    "ResultApplicationError",
    "ResultApplicationOutcome",
    "apply_checkpointed_result_in_transaction",
]
