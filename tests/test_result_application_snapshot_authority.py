# SPDX-License-Identifier: Apache-2.0
"""Regression tests for stable result-application input authority."""

from __future__ import annotations

from typing import Any

import pytest

import pg_llm_batch.result_application as result_application
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


def _checkpoint() -> BatchResultCheckpoint:
    """Build one valid checkpoint for the mutation-race regression."""
    return BatchResultCheckpoint(
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


def _item(checkpoint: BatchResultCheckpoint) -> CheckpointedBatchResultRecord:
    """Pair one valid checkpoint with one exact decoded JSON object."""
    return CheckpointedBatchResultRecord(
        batch_id=checkpoint.batch_id,
        file_kind=checkpoint.file_kind,
        record={"custom_id": "request-1"},
        checkpoint=checkpoint,
    )


class _MutatingLoadStore:
    """Mutate caller-owned checkpoint slots after the package validates them."""

    def __init__(self, item: CheckpointedBatchResultRecord) -> None:
        self.item = item
        self.saved_checkpoint: BatchResultCheckpoint | None = None

    def load_in_transaction(
        self,
        _cursor: Any,
        _consumer_name: str,
        batch_id: str,
        endpoint_alias: str,
    ) -> None:
        """Prove load used validated identity, then mutate caller-owned state."""
        assert batch_id == "batch-123"
        assert endpoint_alias == "openrouter"
        object.__setattr__(self.item.checkpoint, "batch_id", "batch-mutated")
        return None

    def save_in_transaction(
        self,
        _cursor: Any,
        _consumer_name: str,
        checkpoint: BatchResultCheckpoint,
        *,
        expected_previous: BatchResultCheckpoint | None = None,
    ) -> BatchResultCheckpoint:
        """Record the checkpoint authority supplied after local application."""
        assert expected_previous is None
        self.saved_checkpoint = checkpoint
        return checkpoint


class _MutatingSaveStore:
    """Mutate package-supplied save authority before echoing confirmation."""

    def load_in_transaction(self, *_args: Any) -> None:
        """Report no durable predecessor for this fresh application."""
        return None

    def save_in_transaction(
        self,
        _cursor: Any,
        _consumer_name: str,
        checkpoint: BatchResultCheckpoint,
        *,
        expected_previous: BatchResultCheckpoint | None = None,
    ) -> BatchResultCheckpoint:
        """Forge the outbound checkpoint after the local effect has completed."""
        assert expected_previous is None
        object.__setattr__(checkpoint, "batch_id", "batch-mutated")
        return checkpoint


class _MutatingNestedRecordStore:
    """Mutate caller-owned nested JSON after the package snapshots the item."""

    def __init__(self, item: CheckpointedBatchResultRecord) -> None:
        self.item = item

    def load_in_transaction(self, *_args: Any) -> None:
        """Change a nested list/dict value before the business effect runs."""
        self.item.record["response"]["choices"][0]["text"] = "substituted"
        return None

    def save_in_transaction(
        self,
        _cursor: Any,
        _consumer_name: str,
        checkpoint: BatchResultCheckpoint,
        *,
        expected_previous: BatchResultCheckpoint | None = None,
    ) -> BatchResultCheckpoint:
        """Echo the candidate checkpoint after the effect completes."""
        assert expected_previous is None
        return checkpoint


class _DictSubclass(dict[str, Any]):
    """Represent a behavior-capable mapping that is not an exact JSON object."""


class _ListSubclass(list[Any]):
    """Represent a behavior-capable sequence that is not an exact JSON array."""


def _assert_record_rejected(record: dict[Any, Any]) -> None:
    """Require malformed manual JSON authority to fail before store access."""
    checkpoint = _checkpoint()
    item = CheckpointedBatchResultRecord(
        batch_id=checkpoint.batch_id,
        file_kind=checkpoint.file_kind,
        record=record,
        checkpoint=checkpoint,
    )

    with pytest.raises(ValidationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(), object(), "result-writer", item, lambda *_args: None
        )

    assert caught.value.details["field"] == "item.record"
    assert caught.value.details["value"] == "<redacted>"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_result_application_uses_validated_checkpoint_snapshot_after_load_hook() -> None:
    """A store hook cannot change the checkpoint applied after validation."""
    checkpoint = _checkpoint()
    item = _item(checkpoint)
    store = _MutatingLoadStore(item)
    seen_records: list[dict[str, Any]] = []

    outcome = apply_checkpointed_result_in_transaction(
        object(),
        store,
        "result-writer",
        item,
        lambda _cursor, record: seen_records.append(dict(record)),
    )

    assert checkpoint.batch_id == "batch-mutated"
    assert store.saved_checkpoint == _checkpoint()
    assert seen_records == [{"custom_id": "request-1"}]
    assert outcome == ResultApplicationOutcome(
        applied=True,
        checkpoint=_checkpoint(),
    )


def test_result_application_does_not_reread_caller_slots_after_validation(
    monkeypatch: Any,
) -> None:
    """Post-validation caller mutation cannot replace snapshotted authority."""
    checkpoint = _checkpoint()
    item = _item(checkpoint)
    store = _MutatingLoadStore(item)
    seen_records: list[dict[str, Any]] = []
    original_validator = result_application._validate_item_and_effect
    validation_calls = 0

    def validate_then_mutate(
        candidate: Any,
        apply_record: Any,
    ) -> CheckpointedBatchResultRecord:
        nonlocal validation_calls
        validated = original_validator(candidate, apply_record)
        validation_calls += 1
        if validation_calls == 1:
            object.__setattr__(checkpoint, "batch_id", "batch-mutated")
        return validated

    monkeypatch.setattr(
        result_application,
        "_validate_item_and_effect",
        validate_then_mutate,
    )

    outcome = apply_checkpointed_result_in_transaction(
        object(),
        store,
        "result-writer",
        item,
        lambda _cursor, record: seen_records.append(dict(record)),
    )

    assert validation_calls == 1
    assert checkpoint.batch_id == "batch-mutated"
    assert store.saved_checkpoint == _checkpoint()
    assert seen_records == [{"custom_id": "request-1"}]
    assert outcome == ResultApplicationOutcome(
        applied=True,
        checkpoint=_checkpoint(),
    )


def test_result_application_detaches_nested_json_before_load_hook() -> None:
    """A retained caller record cannot rewrite nested business-effect content."""
    checkpoint = _checkpoint()
    record = {
        "custom_id": "request-1",
        "response": {"choices": [{"text": "approved"}]},
    }
    item = CheckpointedBatchResultRecord(
        batch_id=checkpoint.batch_id,
        file_kind=checkpoint.file_kind,
        record=record,
        checkpoint=checkpoint,
    )
    seen_text: list[str] = []

    outcome = apply_checkpointed_result_in_transaction(
        object(),
        _MutatingNestedRecordStore(item),
        "result-writer",
        item,
        lambda _cursor, applied_record: seen_text.append(
            applied_record["response"]["choices"][0]["text"]
        ),
    )

    assert record["response"]["choices"][0]["text"] == "substituted"
    assert seen_text == ["approved"]
    assert outcome == ResultApplicationOutcome(applied=True, checkpoint=_checkpoint())


def test_json_snapshot_preserves_exact_scalar_meaning_and_detaches_containers() -> None:
    """Exact JSON scalars survive while nested list/dict containers are detached."""
    original = {
        "none": None,
        "boolean": True,
        "integer": 7,
        "float": 1.5,
        "nested": [{"text": "approved"}],
    }

    copied = result_application._snapshot_json_record(original)

    assert copied == original
    assert copied is not original
    assert copied["nested"] is not original["nested"]
    assert copied["nested"][0] is not original["nested"][0]


@pytest.mark.parametrize(
    "record",
    [
        {"value": ("not", "json")},
        {"value": float("nan")},
        {"value": _DictSubclass({"nested": "value"})},
        {"value": _ListSubclass(["value"])},
        {1: "non-string-key"},
    ],
)
def test_json_snapshot_rejects_non_exact_or_non_json_values(record: dict[Any, Any]) -> None:
    """Manual records cannot introduce behavior-bearing or non-JSON values."""
    _assert_record_rejected(record)


def test_json_snapshot_rejects_recursive_dict_and_list_cycles() -> None:
    """Cyclic manual containers fail before recursive traversal can run forever."""
    dict_cycle: dict[str, Any] = {}
    dict_cycle["self"] = dict_cycle
    _assert_record_rejected(dict_cycle)

    list_cycle: list[Any] = []
    list_cycle.append(list_cycle)
    _assert_record_rejected({"cycle": list_cycle})


def test_json_snapshot_enforces_depth_node_and_text_budgets(monkeypatch: Any) -> None:
    """Manual JSON authority remains finite across all package-owned work budgets."""
    too_deep: dict[str, Any] = {}
    cursor = too_deep
    for _ in range(result_application._MAX_RECORD_JSON_DEPTH):
        child: dict[str, Any] = {}
        cursor["next"] = child
        cursor = child
    _assert_record_rejected(too_deep)

    monkeypatch.setattr(result_application, "_MAX_RECORD_JSON_NODES", 2)
    _assert_record_rejected({"key": 1})

    monkeypatch.setattr(result_application, "_MAX_RECORD_JSON_NODES", 100)
    monkeypatch.setattr(result_application, "_MAX_RECORD_JSON_TEXT_CHARS", 3)
    _assert_record_rejected({"ab": "cd"})


def test_json_snapshot_rejects_huge_integer_before_decimal_materialization(
    monkeypatch: Any,
) -> None:
    """The package byte budget must reject a huge int before allocating decimal text."""
    oversized_integer = 1 << (4 * result_application._MAX_RECORD_JSON_TEXT_CHARS)

    def fail_if_decimal_text_is_materialized(_value: object) -> str:
        raise AssertionError("huge integer decimal text was materialized before rejection")

    monkeypatch.setattr(
        result_application,
        "str",
        fail_if_decimal_text_is_materialized,
        raising=False,
    )

    _assert_record_rejected({"value": oversized_integer})


def test_mutated_checkpoint_semantics_are_redacted_before_store_access() -> None:
    """Exact primitive mutation cannot leak its value through checkpoint validation."""
    checkpoint = _checkpoint()
    item = _item(checkpoint)
    object.__setattr__(checkpoint, "batch_id", "SECRET/SENTINEL")

    with pytest.raises(ValidationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(), object(), "result-writer", item, lambda *_args: None
        )

    assert caught.value.details["field"] == "item.checkpoint"
    assert caught.value.details["value"] == "<redacted>"
    assert "SECRET/SENTINEL" not in str(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_deleted_checkpoint_slot_is_redacted_before_store_access() -> None:
    """A removed checkpoint slot fails closed at the package validation boundary."""
    checkpoint = _checkpoint()
    item = _item(checkpoint)
    object.__delattr__(checkpoint, "batch_id")

    with pytest.raises(ValidationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(), object(), "result-writer", item, lambda *_args: None
        )

    assert caught.value.details["field"] == "item.checkpoint"
    assert caught.value.details["value"] == "<redacted>"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_deleted_item_slot_is_redacted_before_store_access() -> None:
    """A removed result-record slot cannot leak raw attribute diagnostics."""
    item = _item(_checkpoint())
    object.__delattr__(item, "checkpoint")

    with pytest.raises(ValidationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(), object(), "result-writer", item, lambda *_args: None
        )

    assert caught.value.details["field"] == "item"
    assert caught.value.details["value"] == "<redacted>"
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None


def test_mutating_save_confirmation_fails_closed() -> None:
    """A save hook cannot mutate outbound authority into application success."""
    checkpoint = _checkpoint()
    item = _item(checkpoint)

    with pytest.raises(ResultApplicationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(),
            _MutatingSaveStore(),
            "result-writer",
            item,
            lambda *_args: None,
        )

    assert caught.value.details == {"phase": "checkpoint_save"}
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
