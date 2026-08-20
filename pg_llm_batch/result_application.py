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
from math import isfinite
from threading import get_ident
from typing import Any, Callable, Mapping

from .checkpoint_store import CheckpointConflictError
from .exceptions import PgLlmBatchError, ValidationError
from .result_streaming import (
    DEFAULT_MAX_JSONL_LINE_BYTES,
    DEFAULT_MAX_JSONL_RECORDS,
    BatchResultCheckpoint,
    CheckpointedBatchResultRecord,
)


_CHECKPOINT_STRING_FIELDS = (
    "batch_id",
    "endpoint_alias",
    "file_kind",
    "file_id",
    "prefix_sha256",
)
_CHECKPOINT_INTEGER_FIELDS = (
    "schema_version",
    "file_line_number",
    "batch_line_count",
    "record_count",
)
_MAX_RECORD_JSON_DEPTH = 64
_MAX_RECORD_JSON_NODES = DEFAULT_MAX_JSONL_RECORDS
_MAX_RECORD_JSON_TEXT_CHARS = DEFAULT_MAX_JSONL_LINE_BYTES


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
    for field in _CHECKPOINT_STRING_FIELDS:
        if type(getattr(checkpoint, field)) is not str:
            return field
    for field in _CHECKPOINT_INTEGER_FIELDS:
        if type(getattr(checkpoint, field)) is not int:
            return field
    return None


def _snapshot_json_record(record: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy one exact-JSON object under finite structural and text budgets."""
    node_count = 0
    text_char_count = 0
    active_containers: set[int] = set()

    def reject() -> ValidationError:
        return _redacted_validation_error(
            "item.record", "must be bounded data made only of exact JSON primitives"
        )

    def snapshot(value: Any, depth: int) -> Any:
        nonlocal node_count, text_char_count
        node_count += 1
        if node_count > _MAX_RECORD_JSON_NODES:
            raise reject()

        value_type = type(value)
        if value_type is str:
            text_char_count += len(value)
            if text_char_count > _MAX_RECORD_JSON_TEXT_CHARS:
                raise reject()
            return value
        if value is None or value_type is bool or value_type is int:
            return value
        if value_type is float:
            if not isfinite(value):
                raise reject()
            return value
        if value_type is dict:
            if depth >= _MAX_RECORD_JSON_DEPTH:
                raise reject()
            identity = id(value)
            if identity in active_containers:
                raise reject()
            active_containers.add(identity)
            try:
                copied: dict[str, Any] = {}
                for key, nested_value in value.items():
                    if type(key) is not str:
                        raise reject()
                    copied[snapshot(key, depth + 1)] = snapshot(
                        nested_value, depth + 1
                    )
                return copied
            finally:
                active_containers.remove(identity)
        if value_type is list:
            if depth >= _MAX_RECORD_JSON_DEPTH:
                raise reject()
            identity = id(value)
            if identity in active_containers:
                raise reject()
            active_containers.add(identity)
            try:
                return [snapshot(element, depth + 1) for element in value]
            finally:
                active_containers.remove(identity)
        raise reject()

    copied_record = snapshot(record, 0)
    if type(copied_record) is not dict:
        raise reject()
    return copied_record


def _validate_item_and_effect(
    item: Any,
    apply_record: Any,
) -> CheckpointedBatchResultRecord:
    """Validate package-owned application authority before store or callback work."""
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


def _snapshot_checkpoint(
    checkpoint: Any,
    *,
    field_prefix: str,
) -> BatchResultCheckpoint:
    """Capture one complete checkpoint once, then validate package-owned primitives."""
    if type(checkpoint) is not BatchResultCheckpoint:
        raise _redacted_validation_error(
            field_prefix, "must be an exact batch result checkpoint"
        )

    missing_authority = False
    try:
        values = {
            "schema_version": checkpoint.schema_version,
            "batch_id": checkpoint.batch_id,
            "endpoint_alias": checkpoint.endpoint_alias,
            "file_kind": checkpoint.file_kind,
            "file_id": checkpoint.file_id,
            "file_line_number": checkpoint.file_line_number,
            "batch_line_count": checkpoint.batch_line_count,
            "record_count": checkpoint.record_count,
            "prefix_sha256": checkpoint.prefix_sha256,
        }
    except AttributeError:
        missing_authority = True
    if missing_authority:
        raise _redacted_validation_error(
            field_prefix, "must contain complete checkpoint authority"
        ) from None

    for field in _CHECKPOINT_STRING_FIELDS:
        if type(values[field]) is not str:
            raise _redacted_validation_error(
                f"{field_prefix}.{field}",
                "must use an exact built-in primitive type",
            )
    for field in _CHECKPOINT_INTEGER_FIELDS:
        if type(values[field]) is not int:
            raise _redacted_validation_error(
                f"{field_prefix}.{field}",
                "must use an exact built-in primitive type",
            )

    validation_failed = False
    try:
        snapshot = BatchResultCheckpoint(**values)
    except ValidationError:
        validation_failed = True
    if validation_failed:
        raise _redacted_validation_error(
            field_prefix, "must satisfy the batch result checkpoint contract"
        ) from None
    return snapshot


def _snapshot_item_and_effect(
    item: Any,
    apply_record: Any,
) -> CheckpointedBatchResultRecord:
    """Detach caller-owned item authority before validating or invoking hooks."""
    if type(item) is not CheckpointedBatchResultRecord:
        raise _redacted_validation_error(
            "item", "must be an exact checkpointed batch result record"
        )

    missing_authority = False
    try:
        batch_id = item.batch_id
        file_kind = item.file_kind
        record = item.record
        checkpoint = item.checkpoint
    except AttributeError:
        missing_authority = True
    if missing_authority:
        raise _redacted_validation_error(
            "item", "must contain complete checkpointed result authority"
        ) from None
    if type(batch_id) is not str:
        raise _redacted_validation_error(
            "item.batch_id", "must be an exact built-in string"
        )
    if type(file_kind) is not str:
        raise _redacted_validation_error(
            "item.file_kind", "must be an exact built-in string"
        )
    if type(record) is not dict:
        raise _redacted_validation_error("item.record", "must be an exact JSON object")

    snapshot = CheckpointedBatchResultRecord(
        batch_id=batch_id,
        file_kind=file_kind,
        record=_snapshot_json_record(record),
        checkpoint=_snapshot_checkpoint(checkpoint, field_prefix="item.checkpoint"),
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

    The caller-owned item is snapshotted before semantic validation or any store
    or callback hook. Checkpoint slots are captured once into exact built-in
    primitives, reconstructed as package-owned checkpoints, and only those
    snapshots participate in load/replay/regression decisions, record effects,
    save confirmation, or the returned outcome. The record tree is recursively
    copied before hooks using only exact JSON primitives under finite depth,
    node-count, and text-size budgets. Missing, behavior-bearing, cyclic,
    non-finite, or post-construction-mutated authority fails through bounded
    redacted package diagnostics.

    The durable predecessor is likewise copied immediately after the load hook;
    save receives separate copies of both the candidate and predecessor so a
    caller-owned adapter cannot mutate the package's comparison authority. A
    returned save confirmation is independently snapshotted before comparison.
    Exact checkpoint and primitive types are required before behavior-bearing
    comparisons can execute.

    Fresh work invokes ``apply_record`` with a package-scoped cursor facade on
    the supplied transaction and advances the checkpoint only after that
    callback completes synchronously and returns ``None``. The facade permits
    ordinary synchronous ``execute``/``executemany`` and ``fetch*`` operations
    only on the callback's original thread. It is revoked on every callback exit,
    so deferred work cannot retain package-supplied transaction cursor authority
    after return. This is an authority boundary, not a claim that Python can
    forcibly terminate arbitrary already-running Futures, Tasks, threads, or
    other caller-retained resources.

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
    from retaining provider or database diagnostics. Local transaction atomicity
    is not distributed exactly-once delivery for external systems.
    """
    candidate = _snapshot_item_and_effect(item, apply_record)

    load_failure: ResultApplicationError | None = None
    previous: BatchResultCheckpoint | None = None
    try:
        loaded_previous = checkpoint_store.load_in_transaction(
            cursor,
            consumer_name,
            candidate.batch_id,
            candidate.checkpoint.endpoint_alias,
        )
        if loaded_previous is not None:
            previous = _snapshot_checkpoint(
                loaded_previous,
                field_prefix="checkpoint",
            )
    except CheckpointConflictError:
        raise
    except Exception:
        load_failure = ResultApplicationError("checkpoint_load")
    if load_failure is not None:
        raise load_failure from None
    if previous is not None and (
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
        checkpoint_to_save = _snapshot_checkpoint(
            candidate.checkpoint,
            field_prefix="checkpoint",
        )
        expected_previous_to_save = (
            None
            if previous is None
            else _snapshot_checkpoint(previous, field_prefix="expected_previous")
        )
        saved_checkpoint = checkpoint_store.save_in_transaction(
            cursor,
            consumer_name,
            checkpoint_to_save,
            expected_previous=expected_previous_to_save,
        )
        saved_snapshot = _snapshot_checkpoint(
            saved_checkpoint,
            field_prefix="checkpoint",
        )
        if saved_snapshot != candidate.checkpoint:
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
