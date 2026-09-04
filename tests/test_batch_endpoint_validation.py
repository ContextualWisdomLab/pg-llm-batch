# SPDX-License-Identifier: Apache-2.0
"""Validation tests for Batch API target endpoint paths."""

from __future__ import annotations

import pytest

from pg_llm_batch.batch_api_client import (
    BatchAPIClient,
    GatewayCredentials,
    _validate_batch_endpoint,
)
from pg_llm_batch.exceptions import ValidationError


@pytest.mark.parametrize(
    "endpoint",
    [
        "/v1/chat/completions",
        "/v1/embeddings",
        "/v1/responses",
        "/deployments/gpt-4o_2026/chat-completions",
        "/api/v2.1/batch_jobs",
    ],
)
def test_valid_batch_endpoints_are_preserved(endpoint):
    """Common OpenAI-compatible relative API paths remain unchanged."""
    assert _validate_batch_endpoint(endpoint) == endpoint


@pytest.mark.parametrize(
    "endpoint",
    [
        "",
        "v1/chat/completions",
        "//gateway.example/v1/chat/completions",
        "/v1/chat/completions/",
        "/v1//completions",
        "/v1/./completions",
        "/v1/../admin",
        "/v1/chat/completions?tenant=other",
        "/v1/chat/completions#fragment",
        "/v1/chat%2Fcompletions",
        "/v1/chat\\completions",
        "/v1/chat completions",
        "/v1/응답",
        "/" + "/".join(["segment"] * 17),
        "/" + "a" * 256,
        None,
        123,
        True,
    ],
)
def test_invalid_batch_endpoints_raise_structured_validation_errors(endpoint):
    """Absolute URLs, ambiguous paths, traversal, and invalid types fail closed."""
    with pytest.raises(ValidationError, match="endpoint") as exc_info:
        _validate_batch_endpoint(endpoint)

    assert exc_info.value.details["field"] == "endpoint"
    assert exc_info.value.details["value"] == "<redacted>"
    assert "queries" in exc_info.value.details["reason"]
    if isinstance(endpoint, str) and endpoint:
        assert endpoint not in str(exc_info.value)
        assert endpoint not in repr(exc_info.value.details)


class Credentials:
    """Record whether invalid batch input reached secret resolution."""

    def __init__(self) -> None:
        self.calls = []

    def __call__(self, alias: str) -> GatewayCredentials:
        self.calls.append(alias)
        return GatewayCredentials(url="https://gateway.example/v1", api_key="secret")


async def test_create_batch_rejects_endpoint_before_credentials_or_transport():
    """An invalid provider target consumes neither credentials nor HTTP work."""
    credentials = Credentials()
    client = BatchAPIClient("postgresql://x", credentials)

    with pytest.raises(ValidationError, match="endpoint"):
        await client.create_batch_job(
            "file-safe",
            "default",
            endpoint="https://evil.example/v1/chat/completions",
        )

    assert credentials.calls == []
    assert client._session is None
