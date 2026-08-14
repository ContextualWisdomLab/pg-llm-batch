# SPDX-License-Identifier: Apache-2.0
"""Regression tests for transactional provider-result application."""

from __future__ import annotations

import traceback
from typing import Any, Callable

import pytest

from pg_llm_batch.checkpoint_store import CheckpointConflictError
from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.result_application import (
    ResultApplicationError,
    ResultApplicationOutcome,
    apply_checkpointed_result_in_transaction,
)
from pg_llm_batch.result_streaming import (
    BatchResultCheckpoint,
    CheckpointedBatchResultRecord,
)


def _checkpoint(*, record_count: int = 1, digest: str = "a" * 64) -> BatchResultCheckpoint:
    """Build one valid checkpoint for the focused transaction tests."""
    return BatchResultCheckpoint(
        schema_version=1,
        batch_id="batch-123",
        endpoint_alias="openrouter",
        file_kind="result",
        file_id="file-123",
        file_line_number=record_count,
        batch_line_count=record_count,
        record_count=record_count,
        prefix_sha256=digest,
    )


def _item(checkpoint: BatchResultCheckpoint) -> CheckpointedBatchResultRecord:
    """Pair one decoded record with its exact checkpoint identity."""
    return CheckpointedBatchResultRecord(
        batch_id=checkpoint.batch_id,
        file_kind=checkpoint.file_kind,
        record={"custom_id": f"request-{checkpoint.record_count}"},
        checkpoint=checkpoint,
    )


class _Store:
    """Minimal caller-transaction checkpoint store recording operation order."""

    def __init__(self, previous: BatchResultCheckpoint | None = None) -> None:
        self.previous = previous
        self.events: list[tuple[Any, ...]] = []
        self.load_error: Exception | None = None
        self.save_error: Exception | None = None

    def load_in_transaction(
        self,
        cursor: Any,
        consumer_name: str,
        batch_id: str,
        endpoint_alias: str,
    ) -> BatchResultCheckpoint | None:
        """Return configured durable state or one injected failure."""
        self.events.append(("load", cursor, consumer_name, batch_id, endpoint_alias))
        if self.load_error is not None:
            raise self.load_error
        return self.previous

    def save_in_transaction(
        self,
        cursor: Any,
        consumer_name: str,
        checkpoint: BatchResultCheckpoint,
        *,
        expected_previous: BatchResultCheckpoint | None = None,
    ) -> BatchResultCheckpoint:
        """Record compare-and-swap inputs or one injected failure."""
        self.events.append(
            ("save", cursor, consumer_name, checkpoint, expected_previous)
        )
        if self.save_error is not None:
            raise self.save_error
        self.previous = checkpoint
        return checkpoint


def test_applies_local_effect_before_checkpoint_in_same_caller_transaction() -> None:
    """Fresh work must execute its local effect then advance the exact checkpoint."""
    cursor = object()
    checkpoint = _checkpoint()
    item = _item(checkpoint)
    store = _Store()

    def effect(seen_cursor: Any, record: dict[str, Any]) -> None:
        store.events.append(("effect", seen_cursor, record.copy()))

    outcome = apply_checkpointed_result_in_transaction(
        cursor,
        store,
        "result-writer",
        item,
        effect,
    )

    assert outcome == ResultApplicationOutcome(applied=True, checkpoint=checkpoint)
    assert [event[0] for event in store.events] == ["load", "effect", "save"]
    assert store.events[1] == ("effect", cursor, item.record)
    assert store.events[2][-1] is None


def test_existing_checkpoint_is_supplied_as_compare_and_swap_predecessor() -> None:
    """Advancement must bind the exact previously loaded durable checkpoint."""
    previous = _checkpoint(record_count=1, digest="a" * 64)
    checkpoint = _checkpoint(record_count=2, digest="b" * 64)
    store = _Store(previous)

    outcome = apply_checkpointed_result_in_transaction(
        object(),
        store,
        "result-writer",
        _item(checkpoint),
        lambda _cursor, _record: None,
    )

    assert outcome.applied is True
    assert store.events[-1][-1] == previous


def test_exact_checkpoint_replay_is_idempotent_without_reapplying_effect() -> None:
    """An already acknowledged record must not repeat its local business effect."""
    checkpoint = _checkpoint()
    store = _Store(checkpoint)
    called = False

    def effect(_cursor: Any, _record: dict[str, Any]) -> None:
        nonlocal called
        called = True

    outcome = apply_checkpointed_result_in_transaction(
        object(),
        store,
        "result-writer",
        _item(checkpoint),
        effect,
    )

    assert outcome == ResultApplicationOutcome(applied=False, checkpoint=checkpoint)
    assert called is False
    assert [event[0] for event in store.events] == ["load"]


@pytest.mark.parametrize(
    ("mutation", "field"),
    [
        (
            lambda item: CheckpointedBatchResultRecord(
                batch_id="other-batch",
                file_kind=item.file_kind,
                record=item.record,
                checkpoint=item.checkpoint,
            ),
            "item.batch_id",
        ),
        (
            lambda item: CheckpointedBatchResultRecord(
                batch_id=item.batch_id,
                file_kind="error",
                record=item.record,
                checkpoint=item.checkpoint,
            ),
            "item.file_kind",
        ),
        (
            lambda item: CheckpointedBatchResultRecord(
                batch_id=item.batch_id,
                file_kind=item.file_kind,
                record=[] ,  # type: ignore[arg-type]
                checkpoint=item.checkpoint,
            ),
            "item.record",
        ),
    ],
)
def test_record_identity_is_validated_before_store_or_effect(
    mutation: Callable[[CheckpointedBatchResultRecord], CheckpointedBatchResultRecord],
    field: str,
) -> None:
    """Decoded payload identity must agree with its checkpoint before side effects."""
    store = _Store()
    item = mutation(_item(_checkpoint()))

    with pytest.raises(ValidationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(), store, "result-writer", item, lambda _cursor, _record: None
        )

    assert caught.value.details["field"] == field
    assert caught.value.details["value"] == "<redacted>"
    assert store.events == []


def test_argument_types_fail_closed_before_store_access() -> None:
    """The helper must reject unsupported records and non-callable effect hooks."""
    store = _Store()
    with pytest.raises(ValidationError) as bad_item:
        apply_checkpointed_result_in_transaction(
            object(), store, "result-writer", object(), lambda _cursor, _record: None
        )
    assert bad_item.value.details["field"] == "item"

    with pytest.raises(ValidationError) as bad_effect:
        apply_checkpointed_result_in_transaction(
            object(), store, "result-writer", _item(_checkpoint()), None  # type: ignore[arg-type]
        )
    assert bad_effect.value.details["field"] == "apply_record"
    assert store.events == []


def test_effect_failure_is_bounded_and_never_advances_checkpoint() -> None:
    """Sensitive callback diagnostics must not replace the stable package error."""
    store = _Store()

    def effect(_cursor: Any, _record: dict[str, Any]) -> None:
        raise RuntimeError("SECRET-SENTINEL provider payload diagnostic")

    with pytest.raises(ResultApplicationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(), store, "result-writer", _item(_checkpoint()), effect
        )

    rendered = "".join(
        traceback.format_exception(type(caught.value), caught.value, caught.value.__traceback__)
    )
    assert caught.value.details == {"phase": "record_effect"}
    assert "SECRET-SENTINEL" not in rendered
    assert [event[0] for event in store.events] == ["load"]
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


@pytest.mark.parametrize("phase", ["checkpoint_load", "checkpoint_save"])
def test_unexpected_store_failure_is_bounded_without_database_diagnostics(
    phase: str,
) -> None:
    """Unexpected store diagnostics must be replaced by finite phase evidence."""
    store = _Store()
    error = RuntimeError("SECRET-SENTINEL database diagnostic")
    if phase == "checkpoint_load":
        store.load_error = error
    else:
        store.save_error = error

    with pytest.raises(ResultApplicationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(), store, "result-writer", _item(_checkpoint()), lambda _c, _r: None
        )

    rendered = "".join(
        traceback.format_exception(type(caught.value), caught.value, caught.value.__traceback__)
    )
    assert caught.value.details == {"phase": phase}
    assert "SECRET-SENTINEL" not in rendered
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_checkpoint_conflict_remains_a_stable_retry_signal() -> None:
    """Known compare-and-swap conflicts must retain their package-owned contract."""
    store = _Store()
    store.save_error = CheckpointConflictError(
        "result-writer", "batch-123", "expected_previous_stale"
    )

    with pytest.raises(CheckpointConflictError) as caught:
        apply_checkpointed_result_in_transaction(
            object(), store, "result-writer", _item(_checkpoint()), lambda _c, _r: None
        )

    assert caught.value.reason == "expected_previous_stale"
