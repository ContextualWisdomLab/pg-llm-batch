# SPDX-License-Identifier: Apache-2.0
"""Contracts preventing universal provider-compatibility overclaims."""

from pg_llm_batch import batch_api_client


def test_batch_api_client_docstring_qualifies_provider_compatibility() -> None:
    """Public module docs must describe a verified target shape, not every extension."""
    doc = " ".join((batch_api_client.__doc__ or "").split())

    assert "Talks to any OpenAI-compatible" not in doc
    assert "targets the OpenAI-compatible ``/files`` + ``/batches`` API shape" in doc
    assert "provider-specific extensions require independent verification" in doc
