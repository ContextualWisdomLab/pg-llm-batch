# SPDX-License-Identifier: Apache-2.0
"""Coverage regressions for fail-closed transactional result application edges."""

from __future__ import annotations

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


class _IntegerSubclass(int):
    """Represent a behavior-capable integer subtype accepted by checkpoint construction."""


class _CheckpointSubclass(BatchResultCheckpoint):
    """Represent a behavior-capable checkpoint subtype rejected at the apply boundary."""


class _Store:
    """Record checkpoint-store operations and return configured exact evidence."""

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
        """Record one load and return the configured predecessor."""
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
        """Record one save and return the configured confirmation."""
        self.events.append("save")
        assert expected_previous is self.previous
        return checkpoint if self.saved is None else self.saved


def _checkpoint(
    *,
    checkpoint_type: type[BatchResultCheckpoint] = BatchResultCheckpoint,
    schema_version: int = 1,
    batch_id: str = "batch-123",
    endpoint_alias: str = "openrouter",
    file_kind: str = "result",
    file_id: str = "file-123",
    record_count: int = 1,
    digest: str = "a" * 64,
) -> BatchResultCheckpoint:
    """Build one valid checkpoint while allowing one deliberate boundary variant."""
    return checkpoint_type(
        schema_version=schema_version,
        batch_id=batch_id,
        endpoint_alias=endpoint_alias,
        file_kind=file_kind,
        file_id=file_id,
        file_line_number=record_count,
        batch_line_count=record_count,
        record_count=record_count,
        prefix_sha256=digest,
    )


def _item(checkpoint: BatchResultCheckpoint) -> CheckpointedBatchResultRecord:
    """Pair a checkpoint with one exact JSON-object result record."""
    return CheckpointedBatchResultRecord(
        batch_id="batch-123",
        file_kind="result",
        record={"custom_id": "request-1"},
        checkpoint=checkpoint,
    )


def test_checkpoint_integer_subclass_is_rejected_before_store_access() -> None:
    """Exact primitive checks must reject integer subclasses before persistence."""
    checkpoint = _checkpoint(schema_version=_IntegerSubclass(1))
    store = _Store()

    with pytest.raises(ValidationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(), store, "result-writer", _item(checkpoint), lambda *_args: None
        )

    assert caught.value.details["field"] == "item.checkpoint.schema_version"
    assert caught.value.details["value"] == "<redacted>"
    assert store.events == []


def test_checkpoint_subclass_is_rejected_before_store_access() -> None:
    """The candidate checkpoint itself must be an exact package checkpoint type."""
    checkpoint = _checkpoint(checkpoint_type=_CheckpointSubclass)
    store = _Store()

    with pytest.raises(ValidationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(), store, "result-writer", _item(checkpoint), lambda *_args: None
        )

    assert caught.value.details["field"] == "item.checkpoint"
    assert caught.value.details["value"] == "<redacted>"
    assert store.events == []


@pytest.mark.parametrize(
    ("previous_batch_id", "previous_endpoint_alias"),
    [
        ("batch-other", "openrouter"),
        ("batch-123", "secondary"),
    ],
)
def test_loaded_checkpoint_identity_mismatch_fails_before_effect(
    previous_batch_id: str,
    previous_endpoint_alias: str,
) -> None:
    """Loaded exact checkpoints with a different identity must fail before effects."""
    candidate = _checkpoint(record_count=2, digest="b" * 64)
    previous = _checkpoint(
        batch_id=previous_batch_id,
        endpoint_alias=previous_endpoint_alias,
        record_count=1,
    )
    store = _Store(previous=previous)
    effects: list[str] = []

    with pytest.raises(ResultApplicationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(),
            store,
            "result-writer",
            _item(candidate),
            lambda *_args: effects.append("effect"),
        )

    assert caught.value.details == {"phase": "checkpoint_load"}
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert store.events == ["load"]
    assert effects == []


@pytest.mark.parametrize(
    ("previous_file_kind", "previous_file_id"),
    [
        ("error", "file-123"),
        ("result", "file-other"),
    ],
)
def test_loaded_checkpoint_file_identity_mismatch_fails_before_effect(
    previous_file_kind: str,
    previous_file_id: str,
) -> None:
    """A predecessor for another provider file must never authorize an effect."""
    candidate = _checkpoint(record_count=2, digest="b" * 64)
    previous = _checkpoint(
        file_kind=previous_file_kind,
        file_id=previous_file_id,
        record_count=1,
    )
    store = _Store(previous=previous)
    effects: list[str] = []

    with pytest.raises(ResultApplicationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(),
            store,
            "result-writer",
            _item(candidate),
            lambda *_args: effects.append("effect"),
        )

    assert caught.value.details == {"phase": "checkpoint_load"}
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert store.events == ["load"]
    assert effects == []


def test_exact_mismatched_save_confirmation_is_rejected() -> None:
    """An exact but different saved checkpoint must not forge application success."""
    candidate = _checkpoint(record_count=1, digest="a" * 64)
    saved = _checkpoint(record_count=2, digest="b" * 64)
    store = _Store(saved=saved)
    effects: list[str] = []

    with pytest.raises(ResultApplicationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(),
            store,
            "result-writer",
            _item(candidate),
            lambda *_args: effects.append("effect"),
        )

    assert caught.value.details == {"phase": "checkpoint_save"}
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert store.events == ["load", "save"]
    assert effects == ["effect"]


def test_loaded_checkpoint_integer_subclass_is_rejected_before_effect() -> None:
    """Loaded exact checkpoints must also enforce exact primitive evidence."""
    candidate = _checkpoint(record_count=2, digest="b" * 64)
    previous = _checkpoint(
        schema_version=_IntegerSubclass(1),
        record_count=1,
        digest="a" * 64,
    )
    store = _Store(previous=previous)
    effects: list[str] = []

    with pytest.raises(ResultApplicationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(),
            store,
            "result-writer",
            _item(candidate),
            lambda *_args: effects.append("effect"),
        )

    assert caught.value.details == {"phase": "checkpoint_load"}
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert store.events == ["load"]
    assert effects == []


def test_saved_checkpoint_integer_subclass_is_rejected_after_effect() -> None:
    """Save confirmation must enforce exact primitive evidence before success."""
    candidate = _checkpoint(record_count=1, digest="a" * 64)
    saved = _checkpoint(
        schema_version=_IntegerSubclass(1),
        record_count=1,
        digest="a" * 64,
    )
    store = _Store(saved=saved)
    effects: list[str] = []

    with pytest.raises(ResultApplicationError) as caught:
        apply_checkpointed_result_in_transaction(
            object(),
            store,
            "result-writer",
            _item(candidate),
            lambda *_args: effects.append("effect"),
        )

    assert caught.value.details == {"phase": "checkpoint_save"}
    assert caught.value.__cause__ is None
    assert caught.value.__context__ is None
    assert store.events == ["load", "save"]
    assert effects == ["effect"]
