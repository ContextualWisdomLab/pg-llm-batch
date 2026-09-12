# SPDX-License-Identifier: Apache-2.0
"""Hostile-subclass regressions for transactional result application."""

from __future__ import annotations

import traceback
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

_SECRET_SENTINEL = "SECRET-SENTINEL hostile subclass diagnostic"


def _checkpoint(*, record_count: int = 1, digest: str = "a" * 64) -> BatchResultCheckpoint:
    """Build one valid checkpoint for exact-type boundary tests."""
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
    """Pair one ordinary JSON object with its checkpoint."""
    return CheckpointedBatchResultRecord(
        batch_id=checkpoint.batch_id,
        file_kind=checkpoint.file_kind,
        record={"custom_id": "request-1"},
        checkpoint=checkpoint,
    )


class _RecordingStore:
    """Record transaction-store access and return configured evidence."""

    def __init__(
        self,
        *,
        previous: BatchResultCheckpoint | None = None,
        saved: BatchResultCheckpoint | None = None,
    ) -> None:
        self.previous = previous
        self.saved = saved
        self.events: list[str] = []

    def load_in_transaction(self, *_args: object) -> BatchResultCheckpoint | None:
        """Record and return the configured durable predecessor."""
        self.events.append("load")
        return self.previous

    def save_in_transaction(
        self,
        _cursor: Any,
        _consumer_name: str,
        checkpoint: BatchResultCheckpoint,
        *,
        expected_previous: BatchResultCheckpoint | None = None,
    ) -> BatchResultCheckpoint:
        """Record and return configured save confirmation evidence."""
        self.events.append("save")
        assert expected_previous is self.previous
        return checkpoint if self.saved is None else self.saved


class _HostileItem(CheckpointedBatchResultRecord):
    """Expose secret-bearing code if subclass attributes are trusted."""

    def __getattribute__(self, name: str) -> Any:
        """Raise before a caller can read the forged checkpoint attribute."""
        if name == "checkpoint":
            raise RuntimeError(_SECRET_SENTINEL)
        return super().__getattribute__(name)


class _HostileCheckpoint(BatchResultCheckpoint):
    """Expose secret-bearing code if loaded checkpoint subclasses are trusted."""

    def __post_init__(self) -> None:
        """Keep fixture construction inert so product access is the first hostile read."""

    def __getattribute__(self, name: str) -> Any:
        """Raise before forged durable identity can be inspected."""
        if name == "batch_id":
            raise RuntimeError(_SECRET_SENTINEL)
        return super().__getattribute__(name)


class _AlwaysEqualCheckpoint(BatchResultCheckpoint):
    """Forge equality so a mismatched save confirmation appears exact."""

    def __eq__(self, _other: object) -> bool:
        """Pretend every checkpoint equals this forged subclass instance."""
        return True


class _HostileIdentityText(str):
    """Raise if an exact object trusts behavior-bearing string subclasses."""

    def __ne__(self, _other: object) -> bool:
        """Expose the sentinel if product code compares this forged identity."""
        raise RuntimeError(_SECRET_SENTINEL)


def _rendered_exception(error: BaseException) -> str:
    """Render one traceback for confidentiality assertions."""
    return "".join(traceback.format_exception(type(error), error, error.__traceback__))


def test_hostile_item_subclass_is_rejected_before_attribute_access() -> None:
    """Item validation must not execute caller-controlled subclass code."""
    checkpoint = _checkpoint()
    item = _HostileItem(
        batch_id=checkpoint.batch_id,
        file_kind=checkpoint.file_kind,
        record={"custom_id": "request-1"},
        checkpoint=checkpoint,
    )
    store = _RecordingStore()

    with pytest.raises(ValidationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(), store, "result-writer", item, lambda _cursor, _record: None
        )

    assert caught.value.details["field"] == "item"
    assert caught.value.details["value"] == "<redacted>"
    assert _SECRET_SENTINEL not in _rendered_exception(caught.value)
    assert store.events == []


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("batch_id", _HostileIdentityText("batch-123")),
        ("file_kind", _HostileIdentityText("result")),
    ],
)
def test_hostile_item_identity_text_is_rejected_before_comparison(
    field: str,
    value: str,
) -> None:
    """Identity fields must be exact strings before equality can execute."""
    checkpoint = _checkpoint()
    item = CheckpointedBatchResultRecord(
        batch_id=value if field == "batch_id" else checkpoint.batch_id,
        file_kind=value if field == "file_kind" else checkpoint.file_kind,
        record={"custom_id": "request-1"},
        checkpoint=checkpoint,
    )
    store = _RecordingStore()

    with pytest.raises(ValidationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(), store, "result-writer", item, lambda _cursor, _record: None
        )

    assert caught.value.details["field"] == f"item.{field}"
    assert caught.value.details["value"] == "<redacted>"
    assert _SECRET_SENTINEL not in _rendered_exception(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert store.events == []


def test_hostile_checkpoint_identity_text_is_rejected_before_comparison() -> None:
    """Checkpoint identity fields must be exact strings before equality can execute."""
    checkpoint = BatchResultCheckpoint(
        schema_version=1,
        batch_id=_HostileIdentityText("batch-123"),
        endpoint_alias="openrouter",
        file_kind="result",
        file_id="file-123",
        file_line_number=1,
        batch_line_count=1,
        record_count=1,
        prefix_sha256="a" * 64,
    )
    item = CheckpointedBatchResultRecord(
        batch_id="batch-123",
        file_kind="result",
        record={"custom_id": "request-1"},
        checkpoint=checkpoint,
    )
    store = _RecordingStore()

    with pytest.raises(ValidationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(), store, "result-writer", item, lambda _cursor, _record: None
        )

    assert caught.value.details["field"] == "item.checkpoint.batch_id"
    assert caught.value.details["value"] == "<redacted>"
    assert _SECRET_SENTINEL not in _rendered_exception(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert store.events == []


def test_hostile_loaded_checkpoint_subclass_is_rejected_before_identity_access() -> None:
    """Loaded evidence validation must not execute forged checkpoint attributes."""
    candidate = _checkpoint(record_count=2, digest="b" * 64)
    previous = _HostileCheckpoint(
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
    store = _RecordingStore(previous=previous)

    with pytest.raises(ResultApplicationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(),
            store,
            "result-writer",
            _item(candidate),
            lambda _cursor, _record: None,
        )

    assert caught.value.details == {"phase": "checkpoint_load"}
    assert _SECRET_SENTINEL not in _rendered_exception(caught.value)
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert store.events == ["load"]


def test_forged_save_confirmation_subclass_cannot_claim_exact_success() -> None:
    """Save success must require an exact built-in checkpoint instance."""
    candidate = _checkpoint(record_count=1, digest="a" * 64)
    forged = _AlwaysEqualCheckpoint(
        schema_version=1,
        batch_id="different-batch",
        endpoint_alias="openrouter",
        file_kind="result",
        file_id="different-file",
        file_line_number=2,
        batch_line_count=2,
        record_count=2,
        prefix_sha256="b" * 64,
    )
    store = _RecordingStore(saved=forged)

    with pytest.raises(ResultApplicationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(),
            store,
            "result-writer",
            _item(candidate),
            lambda _cursor, _record: None,
        )

    assert caught.value.details == {"phase": "checkpoint_save"}
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert store.events == ["load", "save"]
