# SPDX-License-Identifier: Apache-2.0
"""Unit tests for stable, reason-bearing domain errors."""

from pg_llm_batch.exceptions import (
    ConfigError,
    GatewayError,
    PgLlmBatchError,
    TokenLimitExceededError,
    ValidationError,
)


def test_base_error_rendering_and_default_details():
    plain = PgLlmBatchError("plain")
    coded = PgLlmBatchError("coded", "E_CODE", {"reason": "specific"})
    assert str(plain) == "plain"
    assert plain.details == {}
    assert str(coded) == "[E_CODE] coded"
    assert coded.details == {"reason": "specific"}


def test_error_detail_mappings_snapshot_constructor_inputs():
    """Structured error evidence snapshots only caller-owned outer mappings."""
    nested_details = {"attempts": []}
    details = {"phase": "prepare", "nested": nested_details}
    error = PgLlmBatchError("failed", details=details)
    details["phase"] = "mutated"
    details["new"] = "late"
    nested_details["attempts"].append("late")

    assert error.details == {
        "phase": "prepare",
        "nested": {"attempts": ["late"]},
    }
    error.details["phase"] = "package-owned"
    assert error.details["phase"] == "package-owned"

    nested_response = {"attempts": []}
    response_data = {
        "retry": True,
        "provider": "bounded",
        "nested": nested_response,
    }
    gateway = GatewayError("unavailable", 503, response_data)
    response_data["retry"] = False
    response_data["late"] = "mutation"
    nested_response["attempts"].append("late")

    assert gateway.response_data == {
        "retry": True,
        "provider": "bounded",
        "nested": {"attempts": ["late"]},
    }
    assert gateway.details["response_data"] == gateway.response_data
    assert gateway.response_data is gateway.details["response_data"]
    gateway.response_data["retry"] = False
    assert gateway.details["response_data"]["retry"] is False


def test_gateway_error_preserves_absent_response_data():
    """The snapshot boundary must preserve the existing optional-data contract."""
    gateway = GatewayError("offline")

    assert gateway.status_code is None
    assert gateway.response_data is None
    assert gateway.details == {"status_code": None, "response_data": None}


def test_token_limit_error_preserves_counts_without_batch_identity():
    batch_id = "tenant-a/customer-17/private-batch-20260913"
    error = TokenLimitExceededError(1200, 1000, batch_id=batch_id)

    assert "1,200 > 1,000" in str(error)
    assert error.details == {
        "current_tokens": 1200,
        "limit_tokens": 1000,
        "excess_tokens": 200,
    }
    for diagnostic_surface in (
        str(error),
        repr(error),
        repr(error.args),
        repr(error.details),
    ):
        assert batch_id not in diagnostic_surface

    without_batch_id = TokenLimitExceededError(2, 1)
    assert str(without_batch_id) == (
        "[TOKEN_LIMIT_EXCEEDED] Token limit exceeded: 2 > 1"
    )
    assert without_batch_id.details == {
        "current_tokens": 2,
        "limit_tokens": 1,
        "excess_tokens": 1,
    }


def test_token_limit_error_does_not_execute_batch_identity_behavior():
    class HostileBatchIdentity:
        def __bool__(self):
            raise AssertionError("batch identity truthiness must not execute")

        def __str__(self):
            raise AssertionError("batch identity rendering must not execute")

        def __repr__(self):
            raise AssertionError("batch identity repr must not execute")

        def __format__(self, format_spec):
            raise AssertionError("batch identity formatting must not execute")

    error = TokenLimitExceededError(5, 3, batch_id=HostileBatchIdentity())  # type: ignore[arg-type]

    assert str(error) == "[TOKEN_LIMIT_EXCEEDED] Token limit exceeded: 5 > 3"
    assert error.details == {
        "current_tokens": 5,
        "limit_tokens": 3,
        "excess_tokens": 2,
    }


def test_validation_gateway_and_config_errors_are_structured():
    validation = ValidationError("model", None, "required")
    assert validation.error_code == "VALIDATION_ERROR"
    assert validation.details["field"] == "model"
    assert str(ValidationError(message="custom validation")) == (
        "[VALIDATION_ERROR] custom validation"
    )

    gateway = GatewayError("unavailable", 503, {"retry": True})
    assert str(gateway) == "[GATEWAY_ERROR] Gateway error: unavailable"
    assert gateway.status_code == 503
    assert gateway.response_data == {"retry": True}

    config = ConfigError("missing")
    assert config.error_code == "CONFIG_ERROR"
