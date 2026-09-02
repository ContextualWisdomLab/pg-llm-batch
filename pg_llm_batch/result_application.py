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
_UTF8_BUDGET_CHUNK_CHARACTERS = 4096


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
    Package-owned execution uses :class:`_SemanticResultApplicationOutcome`.
    """

    applied: bool
    checkpoint: BatchResultCheckpoint

    @property
    def record_applied(self) -> bool:
        """Expose the semantic applied-state name without breaking old callers."""
        return self.applied

    @property
    def result_checkpoint(self) -> BatchResultCheckpoint:
        """Expose the semantic checkpoint name without breaking old callers."""
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
    """Return the first checkpoint field with a behavior-bearing primitive."""
    for checkpoint_field_name in _CHECKPOINT_STRING_FIELDS:
        if type(getattr(result_checkpoint, checkpoint_field_name)) is not str:
            return checkpoint_field_name
    for checkpoint_field_name in _CHECKPOINT_INTEGER_FIELDS:
        if type(getattr(result_checkpoint, checkpoint_field_name)) is not int:
            return checkpoint_field_name
    return None


def _utf8_text_bytes_within_budget(text_value: str, remaining_bytes: int) -> int | None:
    """Count UTF-8 payload bytes without allocating an unbounded encoded copy."""
    text_byte_count = 0
    for chunk_start in range(0, len(text_value), _UTF8_BUDGET_CHUNK_CHARACTERS):
        text_chunk = text_value[
            chunk_start : chunk_start + _UTF8_BUDGET_CHUNK_CHARACTERS
        ]
        text_byte_count += len(text_chunk.encode("utf-8", errors="surrogatepass"))
        if text_byte_count > remaining_bytes:
            return None
    return text_byte_count


def _snapshot_json_record(record_object: dict[str, Any]) -> dict[str, Any]:
    """Deep-copy one exact-JSON object under finite structural and text budgets."""
    record_node_count = 0
    record_text_byte_count = 0
    active_containers: set[int] = set()

    def reject_record() -> ValidationError:
        """Build the bounded redacted record validation error."""
        return _redacted_validation_error(
            "item.record",
            "must be bounded data made only of exact JSON primitives",
        )

    def snapshot_json_value(json_value: Any, json_depth: int) -> Any:
        """Copy one JSON value while enforcing structural and UTF-8 byte budgets."""
        nonlocal record_node_count, record_text_byte_count
        record_node_count += 1
        if record_node_count > _MAX_RECORD_JSON_NODES:
            raise reject_record()

        json_value_type = type(json_value)
        if json_value_type is str:
            remaining_text_bytes = _MAX_RECORD_JSON_TEXT_CHARS - record_text_byte_count
            text_byte_count = _utf8_text_bytes_within_budget(
                json_value,
                remaining_text_bytes,
            )
            if text_byte_count is None:
                raise reject_record()
            record_text_byte_count += text_byte_count
            return json_value
        if json_value_type is int:
            try:
                integer_text_byte_count = len(str(json_value))
            except ValueError:
                raise reject_record() from None
            if (
                record_text_byte_count + integer_text_byte_count
                > _MAX_RECORD_JSON_TEXT_CHARS
            ):
                raise reject_record()
            record_text_byte_count += integer_text_byte_count
            return json_value
        if json_value is None or json_value_type is bool:
            return json_value
        if json_value_type is float:
            if not isfinite(json_value):
                raise reject_record()
            return json_value
        if json_value_type is dict:
            if json_depth >= _MAX_RECORD_JSON_DEPTH:
                raise reject_record()
            container_identity = id(json_value)
            if container_identity in active_containers:
                raise reject_record()
            active_containers.add(container_identity)
            try:
                copied_object: dict[str, Any] = {}
                for object_key, nested_value in json_value.items():
                    if type(object_key) is not str:
                        raise reject_record()
                    copied_object[
                        snapshot_json_value(object_key, json_depth + 1)
                    ] = snapshot_json_value(nested_value, json_depth + 1)
                return copied_object
            finally:
                active_containers.remove(container_identity)
        if json_value_type is list:
            if json_depth >= _MAX_RECORD_JSON_DEPTH:
                raise reject_record()
            container_identity = id(json_value)
            if container_identity in active_containers:
                raise reject_record()
            active_containers.add(container_identity)
            try:
                return [
                    snapshot_json_value(list_element, json_depth + 1)
                    for list_element in json_value
                ]
            finally:
                active_containers.remove(container_identity)
        raise reject_record()

    return snapshot_json_value(record_object, 0)


def _validate_item_and_effect(
    checkpointed_record: Any,
    record_effect: Any,
) -> CheckpointedBatchResultRecord:
    """Validate package-owned application authority before store or callback work."""
    if type(checkpointed_record) is not CheckpointedBatchResultRecord:
        raise _redacted_validation_error(
            "item",
            "must be an exact checkpointed batch result record",
        )
    result_checkpoint = checkpointed_record.checkpoint
    if type(result_checkpoint) is not BatchResultCheckpoint:
        raise _redacted_validation_error(
            "item.checkpoint",
            "must be an exact batch result checkpoint",
        )
    checkpoint_field_name = _checkpoint_primitive_type_error(result_checkpoint)
    if checkpoint_field_name is not None:
        raise _redacted_validation_error(
            f"item.checkpoint.{checkpoint_field_name}",
            "must use an exact built-in primitive type",
        )
    if type(checkpointed_record.batch_id) is not str:
        raise _redacted_validation_error(
            "item.batch_id",
            "must be an exact built-in string",
        )
    if type(checkpointed_record.file_kind) is not str:
        raise _redacted_validation_error(
            "item.file_kind",
            "must be an exact built-in string",
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
            "apply_record",
            "must complete synchronously in the caller transaction",
        )
    if checkpointed_record.batch_id != result_checkpoint.batch_id:
        raise _redacted_validation_error(
            "item.batch_id",
            "must match the checkpoint batch identity",
        )
    if checkpointed_record.file_kind != result_checkpoint.file_kind:
        raise _redacted_validation_error(
            "item.file_kind",
            "must match the checkpoint file kind",
        )
    if type(checkpointed_record.record) is not dict:
        raise _redacted_validation_error(
            "item.record",
            "must be an exact JSON object",
        )
    return checkpointed_record


def _snapshot_checkpoint(
    result_checkpoint: Any,
    *,
    field_prefix: str,
) -> BatchResultCheckpoint:
    """Capture complete checkpoint authority into package-owned primitives."""
    if type(result_checkpoint) is not BatchResultCheckpoint:
        raise _redacted_validation_error(
            field_prefix,
            "must be an exact batch result checkpoint",
        )

    missing_authority = False
    try:
        checkpoint_values = {
            "schema_version": result_checkpoint.schema_version,
            "batch_id": result_checkpoint.batch_id,
            "endpoint_alias": result_checkpoint.endpoint_alias,
            "file_kind": result_checkpoint.file_kind,
            "file_id": result_checkpoint.file_id,
            "file_line_number": result_checkpoint.file_line_number,
            "batch_line_count": result_checkpoint.batch_line_count,
            "record_count": result_checkpoint.record_count,
            "prefix_sha256": result_checkpoint.prefix_sha256,
        }
    except AttributeError:
        missing_authority = True
    if missing_authority:
        raise _redacted_validation_error(
            field_prefix,
            "must contain complete checkpoint authority",
        ) from None

    for checkpoint_field_name in _CHECKPOINT_STRING_FIELDS:
        if type(checkpoint_values[checkpoint_field_name]) is not str:
            raise _redacted_validation_error(
                f"{field_prefix}.{checkpoint_field_name}",
                "must use an exact built-in primitive type",
            )
    for checkpoint_field_name in _CHECKPOINT_INTEGER_FIELDS:
        if type(checkpoint_values[checkpoint_field_name]) is not int:
            raise _redacted_validation_error(
                f"{field_prefix}.{checkpoint_field_name}",
                "must use an exact built-in primitive type",
            )

    validation_failed = False
    try:
        checkpoint_snapshot = BatchResultCheckpoint(**checkpoint_values)
    except ValidationError:
        validation_failed = True
    if validation_failed:
        raise _redacted_validation_error(
            field_prefix,
            "must satisfy the batch result checkpoint contract",
        ) from None
    return checkpoint_snapshot


def _snapshot_item_and_effect(
    checkpointed_record: Any,
    record_effect: Any,
) -> CheckpointedBatchResultRecord:
    """Detach caller-owned item authority before validating or invoking hooks."""
    if type(checkpointed_record) is not CheckpointedBatchResultRecord:
        raise _redacted_validation_error(
            "item",
            "must be an exact checkpointed batch result record",
        )

    missing_authority = False
    try:
        batch_id = checkpointed_record.batch_id
        file_kind = checkpointed_record.file_kind
        record_object = checkpointed_record.record
        result_checkpoint = checkpointed_record.checkpoint
    except AttributeError:
        missing_authority = True
    if missing_authority:
        raise _redacted_validation_error(
            "item",
            "must contain complete checkpointed result authority",
        ) from None
    if type(batch_id) is not str:
        raise _redacted_validation_error(
            "item.batch_id",
            "must be an exact built-in string",
        )
    if type(file_kind) is not str:
        raise _redacted_validation_error(
            "item.file_kind",
            "must be an exact built-in string",
        )
    if type(record_object) is not dict:
        raise _redacted_validation_error(
            "item.record",
            "must be an exact JSON object",
        )

    record_snapshot = CheckpointedBatchResultRecord(
        batch_id=batch_id,
        file_kind=file_kind,
        record=_snapshot_json_record(record_object),
        checkpoint=_snapshot_checkpoint(
            result_checkpoint,
            field_prefix="item.checkpoint",
        ),
    )
    return _validate_item_and_effect(record_snapshot, record_effect)


def _apply_checkpointed_record_in_transaction(
    transaction_cursor: Any,
    checkpoint_store: Any,
    consumer_name: str,
    checkpointed_record: CheckpointedBatchResultRecord,
    record_effect: Callable[[Any, Mapping[str, Any]], None],
) -> _SemanticResultApplicationOutcome:
    """Apply one snapshotted record and checkpoint in the caller transaction."""
    validated_record = _snapshot_item_and_effect(checkpointed_record, record_effect)

    checkpoint_load_failure: ResultApplicationError | None = None
    previous_checkpoint: BatchResultCheckpoint | None = None
    try:
        loaded_previous_checkpoint = checkpoint_store.load_in_transaction(
            transaction_cursor,
            consumer_name,
            validated_record.batch_id,
            validated_record.checkpoint.endpoint_alias,
        )
        if loaded_previous_checkpoint is not None:
            previous_checkpoint = _snapshot_checkpoint(
                loaded_previous_checkpoint,
                field_prefix="checkpoint",
            )
    except CheckpointConflictError:
        raise
    except Exception:
        checkpoint_load_failure = ResultApplicationError("checkpoint_load")
    if checkpoint_load_failure is not None:
        raise checkpoint_load_failure from None
    if previous_checkpoint is not None and (
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
        checkpoint_to_save = _snapshot_checkpoint(
            validated_record.checkpoint,
            field_prefix="checkpoint",
        )
        expected_previous_checkpoint = (
            None
            if previous_checkpoint is None
            else _snapshot_checkpoint(
                previous_checkpoint,
                field_prefix="expected_previous",
            )
        )
        saved_checkpoint = checkpoint_store.save_in_transaction(
            transaction_cursor,
            consumer_name,
            checkpoint_to_save,
            expected_previous=expected_previous_checkpoint,
        )
        saved_checkpoint_snapshot = _snapshot_checkpoint(
            saved_checkpoint,
            field_prefix="checkpoint",
        )
        if saved_checkpoint_snapshot != validated_record.checkpoint:
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

    ``cursor``, ``item``, and ``apply_record`` are historical public keyword
    names retained at this compatibility boundary. Internally they become
    ``transaction_cursor``, ``checkpointed_record``, and ``record_effect``.

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
