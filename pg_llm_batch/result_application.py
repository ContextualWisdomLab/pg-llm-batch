# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Atomic local application of streamed provider results with checkpoints.

The helper in this module deliberately owns no PostgreSQL connection and no
transaction lifecycle.  A caller supplies a cursor that already belongs to the
transaction in which both the local business effect and durable checkpoint
advance must occur.  This permits atomicity only for effects executed through
that same PostgreSQL transaction; it does not create a distributed exactly-once
guarantee for external APIs, queues, object stores, or other databases.
"""

from __future__ import annotations

import asyncio
import inspect
from concurrent.futures import Future as ConcurrentFuture
from dataclasses import dataclass
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
    disclose diagnostics or forge durable confirmation.

    The durable predecessor is loaded and validated before the local effect. An
    exact replay returns without re-running the effect, while a count regression
    is rejected before caller-owned business logic. Fresh work invokes
    ``apply_record`` using the supplied cursor and advances the checkpoint only
    after that callback completes synchronously and returns ``None``. Statically
    visible asynchronous callables, including static-method and class-method
    descriptors, are rejected before checkpoint-store access. A raw coroutine
    returned by an otherwise synchronous callable is closed, and returned
    pending :class:`asyncio.Future` or :class:`concurrent.futures.Future` work is
    cancelled before the bounded failure is raised. Rejected deferred work
    therefore cannot keep the cursor or provider record live merely because the
    caller returned its asynchronous handle. The checkpoint store must then
    confirm the exact requested checkpoint before success is reported. The
    caller remains responsible for committing or rolling back the surrounding
    transaction.

    ``CheckpointConflictError`` is intentionally preserved as the stable retry
    signal from both checkpoint load and save operations. All other
    store/callback failures are replaced with a fixed phase-only package error
    after their exception scope has ended, preventing implicit traceback context
    from retaining provider or database diagnostics.
    """
    candidate = _validate_item_and_effect(item, apply_record)

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
    try:
        effect_result = apply_record(cursor, candidate.record)
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
        saved_checkpoint = checkpoint_store.save_in_transaction(
            cursor,
            consumer_name,
            candidate.checkpoint,
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
