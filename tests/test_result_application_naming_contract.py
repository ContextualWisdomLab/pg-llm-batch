"""Naming-contract regressions for checkpointed result application."""

from dataclasses import asdict, fields
from inspect import signature

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


def test_public_outcome_preserves_released_dataclass_contract() -> None:
    """The released dataclass shape remains stable at the compatibility boundary."""
    result_checkpoint = _checkpoint()
    application_outcome = result_application.ResultApplicationOutcome(
        applied=True,
        checkpoint=result_checkpoint,
    )

    assert {field.name for field in fields(result_application.ResultApplicationOutcome)} == {
        "applied",
        "checkpoint",
    }
    assert asdict(application_outcome) == {
        "applied": True,
        "checkpoint": asdict(result_checkpoint),
    }
    assert application_outcome.record_applied is True
    assert application_outcome.result_checkpoint is result_checkpoint


def test_internal_outcome_owns_semantic_fields() -> None:
    """Package-owned execution state uses semantic names behind the public adapter."""
    result_checkpoint = _checkpoint()
    semantic_outcome = result_application._SemanticResultApplicationOutcome(
        record_applied=False,
        result_checkpoint=result_checkpoint,
    )

    assert {
        field.name
        for field in fields(result_application._SemanticResultApplicationOutcome)
    } == {"record_applied", "result_checkpoint"}
    assert semantic_outcome.record_applied is False
    assert semantic_outcome.result_checkpoint is result_checkpoint


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
