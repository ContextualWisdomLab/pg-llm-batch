# SPDX-License-Identifier: Apache-2.0
"""Regression tests for BatchRequest runtime field types."""

import pytest

from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.models import BatchRequest


def test_batch_request_rejects_false_valued_non_string_prompt():
    with pytest.raises(ValidationError) as captured:
        BatchRequest(user_prompt=0, model="gpt-4o")
    assert captured.value.details["field"] == "user_prompt"


def test_batch_request_rejects_non_string_model():
    with pytest.raises(ValidationError) as captured:
        BatchRequest(user_prompt="hello", model=0)
    assert captured.value.details["field"] == "model"


def test_batch_request_rejects_non_string_optional_and_identifier_fields():
    with pytest.raises(ValidationError) as captured:
        BatchRequest(user_prompt="hello", model="gpt-4o", system_prompt=0)
    assert captured.value.details["field"] == "system_prompt"

    with pytest.raises(ValidationError) as captured:
        BatchRequest(user_prompt="hello", model="gpt-4o", id=0)
    assert captured.value.details["field"] == "id"


def test_batch_request_validation_does_not_export_rejected_values():
    secret = "confidential prompt payload"

    for field in ("user_prompt", "system_prompt", "model", "id"):
        kwargs = {
            "user_prompt": "hello",
            "model": "gpt-4o",
            "system_prompt": None,
            "id": "request-1",
        }
        kwargs[field] = [secret]

        with pytest.raises(ValidationError) as captured:
            BatchRequest(**kwargs)

        error = captured.value
        assert secret not in str(error)
        assert error.details["field"] == field
        assert error.details["value"] == "<redacted>"
        assert secret not in repr(error.details)


def test_batch_request_preserves_string_compatibility():
    request = BatchRequest(user_prompt="", model="", system_prompt="", id="")
    assert (request.user_prompt, request.model, request.system_prompt, request.id) == (
        "",
        "",
        "",
        "",
    )
