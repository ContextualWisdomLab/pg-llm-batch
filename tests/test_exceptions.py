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


def test_token_limit_error_preserves_counts_and_optional_batch():
    error = TokenLimitExceededError(1200, 1000, batch_id="batch-1")
    assert "1,200 > 1,000" in str(error)
    assert "batch_id=batch-1" in str(error)
    assert error.details["excess_tokens"] == 200
    assert "batch_id=" not in str(TokenLimitExceededError(2, 1))


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
