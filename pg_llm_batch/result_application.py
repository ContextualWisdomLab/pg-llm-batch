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


def _validate_item_and_effect(
    item: Any,
    apply_record: Any,
) -> CheckpointedBatchResultRecord:
    """Validate the local application boundary before store or callback work."""
    if not isinstance(item, CheckpointedBatchResultRecord) or not isinstance(
        getattr(item, "checkpoint", None), BatchResultCheckpoint
    ):
        raise _redacted_validation_error(
            "item", "must be a checkpointed batch result record"
        )
    if not callable(apply_record):
        raise _redacted_validation_error("apply_record", "must be callable")
    if item.batch_id != item.checkpoint.batch_id:
        raise _redacted_validation_error(
            "item.batch_id", "must match the checkpoint batch identity"
        )
    if item.file_kind != item.checkpoint.file_kind:
        raise _redacted_validation_error(
            "item.file_kind", "must match the checkpoint file kind"
        )
    if not isinstance(item.record, dict):
        raise _redacted_validation_error("item.record", "must be a JSON object")
    return item


def apply_checkpointed_result_in_transaction(
    cursor: Any,
    checkpoint_store: Any,
    consumer_name: str,
    item: CheckpointedBatchResultRecord,
    apply_record: Callable[[Any, Mapping[str, Any]], None],
) -> ResultApplicationOutcome:
    """Apply one result and advance its checkpoint in the caller's transaction.

    The durable predecessor is loaded before the local effect.  An exact replay
    returns without re-running the effect.  Fresh work invokes ``apply_record``
    using the supplied cursor and only then compares-and-swaps the checkpoint
    against the exact predecessor observed in this transaction.  The caller
    remains responsible for committing or rolling back the surrounding
    transaction.

    ``CheckpointConflictError`` is intentionally preserved as the stable retry
    signal from the checkpoint store.  All other store/callback failures are
    replaced with a fixed phase-only package error after their exception scope
    has ended, preventing implicit traceback context from retaining provider or
    database diagnostics.
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
    except Exception:
        load_failure = ResultApplicationError("checkpoint_load")
    if load_failure is not None:
        raise load_failure from None

    if previous == candidate.checkpoint:
        return ResultApplicationOutcome(applied=False, checkpoint=candidate.checkpoint)

    effect_failure: ResultApplicationError | None = None
    try:
        apply_record(cursor, candidate.record)
    except Exception:
        effect_failure = ResultApplicationError("record_effect")
    if effect_failure is not None:
        raise effect_failure from None

    save_failure: ResultApplicationError | None = None
    try:
        checkpoint_store.save_in_transaction(
            cursor,
            consumer_name,
            candidate.checkpoint,
            expected_previous=previous,
        )
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
