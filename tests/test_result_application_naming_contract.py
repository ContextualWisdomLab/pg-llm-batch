"""Naming-contract regressions for checkpointed result application."""

from dataclasses import fields
from inspect import signature

from pg_llm_batch import result_application as result_application


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
