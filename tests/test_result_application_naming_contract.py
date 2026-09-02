"""Naming-contract regressions for checkpointed result application."""

from dataclasses import fields
from inspect import signature

import pytest

from pg_llm_batch import result_application as result_application
from pg_llm_batch.result_streaming import BatchResultCheckpoint


def _checkpoint() -> BatchResultCheckpoint:
    """Build one valid checkpoint for semantic/legacy outcome compatibility tests."""
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


def test_result_application_internal_signatures_use_semantic_names() -> None:
    """Owned helpers describe checkpointed-result semantics instead of generic values."""
    assert tuple(signature(result_application.ResultApplicationError.__init__).parameters) == (
        "self",
        "application_phase",
    )
    assert tuple(signature(result_application._redacted_validation_error).parameters) == (
        "field_name",
        "validation_reason",
    )
    assert tuple(signature(result_application._validate_item_and_effect).parameters) == (
        "checkpointed_record",
        "record_effect",
    )
    assert tuple(
        signature(result_application._apply_checkpointed_record_in_transaction).parameters
    ) == (
        "transaction_cursor",
        "checkpoint_store",
        "consumer_name",
        "checkpointed_record",
        "record_effect",
    )


def test_result_application_outcome_uses_semantic_fields_with_legacy_accessors() -> None:
    """The domain result owns semantic fields while legacy attribute reads stay compatible."""
    assert {field.name for field in fields(result_application.ResultApplicationOutcome)} == {
        "record_applied",
        "result_checkpoint",
    }
    assert isinstance(result_application.ResultApplicationOutcome.applied, property)
    assert isinstance(result_application.ResultApplicationOutcome.checkpoint, property)


def test_semantic_outcome_construction_exposes_legacy_reads() -> None:
    """New semantic construction remains readable through released legacy properties."""
    result_checkpoint = _checkpoint()
    application_outcome = result_application.ResultApplicationOutcome(
        record_applied=True,
        result_checkpoint=result_checkpoint,
    )

    assert application_outcome.record_applied is True
    assert application_outcome.result_checkpoint is result_checkpoint
    assert application_outcome.applied is True
    assert application_outcome.checkpoint is result_checkpoint


def test_legacy_outcome_construction_populates_semantic_fields() -> None:
    """Released constructor keywords translate immediately into semantic fields."""
    result_checkpoint = _checkpoint()
    application_outcome = result_application.ResultApplicationOutcome(
        applied=False,
        checkpoint=result_checkpoint,
    )

    assert application_outcome.record_applied is False
    assert application_outcome.result_checkpoint is result_checkpoint


def test_outcome_rejects_duplicate_applied_vocabulary() -> None:
    """Callers cannot supply both semantic and legacy applied flags ambiguously."""
    with pytest.raises(TypeError, match="record_applied or legacy applied"):
        result_application.ResultApplicationOutcome(
            record_applied=True,
            applied=False,
            result_checkpoint=_checkpoint(),
        )


def test_outcome_rejects_duplicate_checkpoint_vocabulary() -> None:
    """Callers cannot supply both semantic and legacy checkpoint values ambiguously."""
    result_checkpoint = _checkpoint()
    with pytest.raises(TypeError, match="result_checkpoint or legacy checkpoint"):
        result_application.ResultApplicationOutcome(
            record_applied=True,
            result_checkpoint=result_checkpoint,
            checkpoint=result_checkpoint,
        )


def test_outcome_requires_applied_value() -> None:
    """Either semantic or legacy applied vocabulary is required explicitly."""
    with pytest.raises(TypeError, match="record_applied is required"):
        result_application.ResultApplicationOutcome(result_checkpoint=_checkpoint())


def test_outcome_requires_checkpoint_value() -> None:
    """Either semantic or legacy checkpoint vocabulary is required explicitly."""
    with pytest.raises(TypeError, match="result_checkpoint is required"):
        result_application.ResultApplicationOutcome(record_applied=True)


def test_legacy_public_function_remains_an_explicit_compatibility_adapter() -> None:
    """Existing keyword callers retain the released parameter contract at the ACL boundary."""
    assert tuple(
        signature(result_application.apply_checkpointed_result_in_transaction).parameters
    ) == (
        "cursor",
        "checkpoint_store",
        "consumer_name",
        "item",
        "apply_record",
    )
