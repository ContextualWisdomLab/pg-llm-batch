# SPDX-License-Identifier: Apache-2.0
"""Defensive-branch coverage for result-application authority snapshots."""

from __future__ import annotations

from typing import Any

import pytest

import pg_llm_batch.result_application as result_application
from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.result_streaming import (
    BatchResultCheckpoint,
    CheckpointedBatchResultRecord,
)


class _TextSubclass(str):
    """Represent behavior-capable text rejected by exact-type validation."""


class _DictSubclass(dict[str, Any]):
    """Represent behavior-capable mapping rejected by exact-type validation."""


def _checkpoint() -> BatchResultCheckpoint:
    """Build one valid checkpoint for defensive validation tests."""
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


def _item(checkpoint: BatchResultCheckpoint | object) -> CheckpointedBatchResultRecord:
    """Build one result item, permitting post-construction authority mutation."""
    valid_checkpoint = checkpoint if isinstance(checkpoint, BatchResultCheckpoint) else _checkpoint()
    item = CheckpointedBatchResultRecord(
        batch_id="batch-123",
        file_kind="result",
        record={"custom_id": "request-1"},
        checkpoint=valid_checkpoint,
    )
    if checkpoint is not valid_checkpoint:
        object.__setattr__(item, "checkpoint", checkpoint)
    return item


def _assert_validation_field(item: Any, field: str) -> None:
    """Require one defensive helper rejection to stay redacted and bounded."""
    with pytest.raises(ValidationError) as caught:
        result_application._validate_item_and_effect(item, lambda *_args: None)
    assert caught.value.details["field"] == field
    assert caught.value.details["value"] == "<redacted>"


def test_post_snapshot_validator_rejects_non_package_item() -> None:
    """The internal validator remains fail-closed if its package-type precondition breaks."""
    _assert_validation_field(object(), "item")


def test_post_snapshot_validator_rejects_non_package_checkpoint() -> None:
    """The internal validator rejects a replaced checkpoint before reading its fields."""
    _assert_validation_field(_item(object()), "item.checkpoint")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("batch_id", _TextSubclass("batch-123")),
        ("schema_version", True),
    ],
)
def test_post_snapshot_validator_rejects_checkpoint_primitive_subclasses(
    field: str,
    value: object,
) -> None:
    """String and integer checkpoint slots retain exact built-in type enforcement."""
    checkpoint = _checkpoint()
    object.__setattr__(checkpoint, field, value)
    _assert_validation_field(_item(checkpoint), f"item.checkpoint.{field}")


@pytest.mark.parametrize("field", ["batch_id", "file_kind"])
def test_post_snapshot_validator_rejects_item_identity_subclasses(field: str) -> None:
    """Result identity slots remain exact strings at the defensive validation seam."""
    item = _item(_checkpoint())
    object.__setattr__(item, field, _TextSubclass(getattr(item, field)))
    _assert_validation_field(item, f"item.{field}")


def test_post_snapshot_validator_rejects_non_exact_record_mapping() -> None:
    """A behavior-capable mapping cannot cross the final record-validation seam."""
    item = _item(_checkpoint())
    object.__setattr__(item, "record", _DictSubclass({"custom_id": "request-1"}))
    _assert_validation_field(item, "item.record")


def test_json_snapshot_rejects_list_depth_at_the_exact_ceiling() -> None:
    """Nested arrays are bounded independently from the existing object-depth regression."""
    nested: Any = None
    for _ in range(result_application._MAX_RECORD_JSON_DEPTH):
        nested = [nested]

    with pytest.raises(ValidationError) as caught:
        result_application._snapshot_json_record({"value": nested})

    assert caught.value.details["field"] == "item.record"
    assert caught.value.details["value"] == "<redacted>"
