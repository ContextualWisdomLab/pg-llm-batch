# SPDX-License-Identifier: Apache-2.0
"""Regression tests for interoperable integer authority in JSON usage evidence."""

from __future__ import annotations

import json

import pytest

from pg_llm_batch.usage_evidence import (
    UsageAuthority,
    UsageCompleteness,
    UsageEvidenceError,
    build_usage_evidence,
)


_MAX_INTEROPERABLE_JSON_INTEGER = 2**53 - 1


def _valid_arguments() -> dict[str, object]:
    """Return one complete bounded usage-evidence input set."""
    return {
        "authority": UsageAuthority.LOCAL_MEASURED,
        "tenant_scope_id": "tenant-7f3a",
        "source_id": "local-token-count-v1",
        "request_count": 3,
        "input_token_count": 120,
        "input_token_completeness": UsageCompleteness.COMPLETE,
        "output_token_count": 45,
        "output_token_completeness": UsageCompleteness.COMPLETE,
        "provider_alias": "openai-direct",
        "endpoint_alias": "batch-v1",
        "remote_batch_id": "batch_123",
    }


@pytest.mark.parametrize(
    "field_name",
    ["request_count", "input_token_count", "output_token_count"],
)
def test_usage_counts_reject_values_above_json_interoperability_range(
    field_name: str,
) -> None:
    arguments = _valid_arguments()
    arguments[field_name] = _MAX_INTEROPERABLE_JSON_INTEGER + 1

    with pytest.raises(UsageEvidenceError, match="^invalid usage evidence count$"):
        build_usage_evidence(**arguments)


@pytest.mark.parametrize(
    "field_name",
    ["request_count", "input_token_count", "output_token_count"],
)
def test_usage_counts_accept_json_interoperability_boundary(field_name: str) -> None:
    arguments = _valid_arguments()
    arguments[field_name] = _MAX_INTEROPERABLE_JSON_INTEGER

    canonical_json, _digest = build_usage_evidence(**arguments)

    evidence = json.loads(canonical_json)
    assert evidence[field_name] == _MAX_INTEROPERABLE_JSON_INTEGER
