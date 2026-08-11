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
        """Initialize a structured domain error with a caller-independent detail map."""
        super().__init__(message)
        self.message = message
        self.error_code = error_code
        self.details = dict(details) if details is not None else {}

    def __str__(self) -> str:
        """Render the message with its stable error code when present."""
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
        """Describe an observed token count that exceeded its limit."""
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
        *,
        expose_value: bool = False,
    ) -> None:
        """Describe invalid input without retaining its rejected value by default.

        ``expose_value=True`` is an explicit diagnostic-authority opt-in for a
        reviewed non-sensitive value. The default neither renders nor retains
        the caller object, so confidential content and hostile ``__repr__``
        implementations cannot become package-owned exception evidence.
        """
        if not isinstance(expose_value, bool):
            raise TypeError("expose_value must be a bool")
        evidence_value = value if expose_value else "<redacted>"
        if message is not None:
            rendered = message
        elif expose_value:
            rendered = f"Invalid value for '{field}': {value!r} ({reason})"
        else:
            rendered = f"Invalid value for '{field}' ({reason})"
        super().__init__(
            message=rendered,
            error_code="VALIDATION_ERROR",
            details={"field": field, "value": evidence_value, "reason": reason},
        )


class GatewayError(PgLlmBatchError):
    """Raised when the OpenAI-compatible Batch API returns an error."""

    def __init__(
        self,
        message: str,
        status_code: Optional[int] = None,
        response_data: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Describe a failed gateway operation using a response-map snapshot."""
        response_snapshot = dict(response_data) if response_data is not None else None
        super().__init__(
            message=f"Gateway error: {message}",
            error_code="GATEWAY_ERROR",
            details={"status_code": status_code, "response_data": response_snapshot},
        )
        self.status_code = status_code
        self.response_data = response_snapshot


class ConfigError(PgLlmBatchError):
    """Raised when required configuration or secrets are missing from the store."""

    def __init__(self, message: str) -> None:
        """Initialize a configuration error with its stable code."""
        super().__init__(message=message, error_code="CONFIG_ERROR")
