# SPDX-License-Identifier: Apache-2.0
"""Regression tests for BatchRequest runtime field types."""

import pytest

from pg_llm_batch.exceptions import ValidationError
from pg_llm_batch.models import BatchRequest


class StringSubclass(str):
    """A deliberately non-exact string type for runtime-boundary tests."""


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


@pytest.mark.parametrize("field", ("user_prompt", "model", "system_prompt", "id"))
def test_batch_request_rejects_string_subclasses(field):
    """Every exact-string boundary must reject ``str`` subclasses."""
    kwargs = {
        "user_prompt": "hello",
        "model": "gpt-4o",
        "system_prompt": None,
        "id": "request-1",
    }
    kwargs[field] = StringSubclass("value")

    with pytest.raises(ValidationError) as captured:
        BatchRequest(**kwargs)

    assert captured.value.details["field"] == field
    assert captured.value.details["value"] == "<redacted>"


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


def test_batch_request_representation_excludes_content_and_identifier_values():
    """Generic object rendering must not disclose prompt or caller identifier content."""
    request = BatchRequest(
        user_prompt="user-secret-sentinel",
        model="gpt-4o",
        system_prompt="system-secret-sentinel",
        id="identifier-secret-sentinel",
    )

    for rendered in (repr(request), str(request)):
        assert "user-secret-sentinel" not in rendered
        assert "system-secret-sentinel" not in rendered
        assert "identifier-secret-sentinel" not in rendered
        assert "gpt-4o" in rendered


def test_batch_request_preserves_string_compatibility():
    request = BatchRequest(user_prompt="", model="", system_prompt="", id="")
    assert (request.user_prompt, request.model, request.system_prompt, request.id) == (
        "",
        "",
        "",
        "",
    )


@pytest.mark.parametrize(
    ("field", "invalid_value", "original_value"),
    (
        ("user_prompt", ["assignment-secret-sentinel"], "hello"),
        ("model", StringSubclass("assignment-secret-sentinel"), "gpt-4o"),
        ("system_prompt", ["assignment-secret-sentinel"], "system"),
        ("id", ["assignment-secret-sentinel"], "request-1"),
    ),
)
def test_batch_request_rejects_invalid_post_construction_assignment(
    field, invalid_value, original_value
):
    """Validated fields must not become invalid after construction."""
    request = BatchRequest(
        user_prompt="hello",
        model="gpt-4o",
        system_prompt="system",
        id="request-1",
    )

    with pytest.raises(ValidationError) as captured:
        setattr(request, field, invalid_value)

    error = captured.value
    assert error.details["field"] == field
    assert error.details["value"] == "<redacted>"
    assert "assignment-secret-sentinel" not in str(error)
    assert "assignment-secret-sentinel" not in repr(error.details)
    assert getattr(request, field) == original_value


def test_batch_request_preserves_valid_post_construction_assignment():
    """Exact strings and an optional None remain mutable for compatibility."""
    request = BatchRequest(
        user_prompt="hello",
        model="gpt-4o",
        system_prompt="system",
        id="request-1",
    )

    request.user_prompt = "updated-user"
    request.model = "updated-model"
    request.system_prompt = None
    request.system_prompt = "updated-system"
    request.id = "updated-id"

    assert (request.user_prompt, request.model, request.system_prompt, request.id) == (
        "updated-user",
        "updated-model",
        "updated-system",
        "updated-id",
    )


def test_batch_request_preserves_unrelated_dynamic_attribute_assignment():
    """The guard must not freeze normal dataclass instance extensibility."""
    request = BatchRequest(user_prompt="hello", model="gpt-4o")
    marker = object()

    setattr(request, "runtime_marker", marker)

    assert request.runtime_marker is marker
