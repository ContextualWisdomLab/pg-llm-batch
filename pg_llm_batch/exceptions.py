# SPDX-License-Identifier: Apache-2.0
# Copyright (c) ContextualWisdomLab.
"""Exception hierarchy for pg_llm_batch.

Extracted and relicensed (Apache-2.0) from xtrmLLMBatchPython's batch core.
"""

from __future__ import annotations

from typing import Any, Dict, Optional


_VALIDATION_REDACTED_VALUE = "<redacted>"
_MAX_SAFE_VALIDATION_VALUE_CHARS = 128


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
        safe_value: Optional[str] = None,
    ) -> None:
        """Describe invalid input without exporting rejected content by default.

        ``value`` is retained only for call compatibility and is deliberately never
        rendered, copied into details, or otherwise inspected. A caller may instead
        provide ``safe_value`` after explicitly determining that the diagnostic is
        non-sensitive. That evidence must be a bounded printable ASCII string so an
        exception cannot become an unbounded or control-character-bearing log sink.
        """
        if safe_value is not None:
            if type(safe_value) is not str:
                raise TypeError("safe_value must be a string or None")
            if (
                not safe_value
                or len(safe_value) > _MAX_SAFE_VALIDATION_VALUE_CHARS
                or any(ord(character) < 32 or ord(character) > 126 for character in safe_value)
            ):
                raise ValueError(
                    "safe_value must contain 1-128 printable ASCII characters"
                )
            evidence_value = safe_value
        else:
            evidence_value = _VALIDATION_REDACTED_VALUE

        if message is not None:
            rendered = message
        elif safe_value is not None:
            rendered = f"Invalid value for '{field}': {safe_value} ({reason})"
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
