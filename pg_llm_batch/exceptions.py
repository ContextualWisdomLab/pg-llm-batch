# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Exception hierarchy for pg_llm_batch.

Extracted and relicensed (Apache-2.0) from xtrmLLMBatchPython's batch core.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


class PgLlmBatchError(Exception):
    """Base error for all pg_llm_batch failures."""

    def __init__(
        self,
        message: str,
        error_code: Optional[str] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = details or {}

    def __str__(self) -> str:
        if self.error_code:
            return f"[{self.error_code}] {self.message}"
        return self.message


class TokenLimitExceededError(PgLlmBatchError):
    """Raised when a batch exceeds the effective per-batch token limit."""

    def __init__(
        self,
        current_tokens: int,
        limit_tokens: int,
        batch_id: Optional[str] = None,
    ) -> None:
        message = f"Token limit exceeded: {current_tokens:,} > {limit_tokens:,}"
        if batch_id:
            message += f" (batch_id={batch_id})"
        super().__init__(
            message=message,
            error_code="TOKEN_LIMIT_EXCEEDED",
            details={
                "current_tokens": current_tokens,
                "limit_tokens": limit_tokens,
                "batch_id": batch_id,
                "excess_tokens": current_tokens - limit_tokens,
            },
        )


class ValidationError(PgLlmBatchError):
    """Raised when a configuration or input value fails validation."""

    def __init__(
        self,
        field: str = "",
        value: Any = None,
        reason: str = "",
        message: Optional[str] = None,
    ) -> None:
        rendered = message or f"Invalid value for '{field}': {value!r} ({reason})"
        super().__init__(
            message=rendered,
            error_code="VALIDATION_ERROR",
            details={"field": field, "value": value, "reason": reason},
        )


class GatewayError(PgLlmBatchError):
    """Raised when the OpenAI-compatible Batch API returns an error."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        super().__init__(
            message=f"Gateway error: {message}",
            error_code="GATEWAY_ERROR",
            details={"status_code": status_code, "response_data": response_data},
        )
        self.status_code = status_code
        self.response_data = response_data


class ConfigError(PgLlmBatchError):
    """Raised when required configuration or secrets are missing from the store."""

    def __init__(self, message: str) -> None:
        super().__init__(message=message, error_code="CONFIG_ERROR")
