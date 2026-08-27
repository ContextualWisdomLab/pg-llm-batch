# SPDX-License-Identifier: Apache-2.0
"""Tests for deterministic, provenance-distinct usage evidence."""

from __future__ import annotations

import hashlib
import json

import pytest

from pg_llm_batch.usage_evidence import (
    UsageAuthority,
    UsageEvidenceError,
    build_usage_evidence,
)


def _valid_arguments() -> dict[str, object]:
    return {
        "authority": UsageAuthority.LOCAL_MEASURED,
        "tenant_scope_id": "tenant-7f3a",
        "source_id": "local-token-count-v1",
        "request_count": 3,
        "input_token_count": 120,
        "output_token_count": 45,
        "provider_alias": "openai-direct",
        "endpoint_alias": "batch-v1",
        "remote_batch_id": "batch_123",
    }


def test_usage_authority_vocabulary_is_closed() -> None:
    assert [authority.value for authority in UsageAuthority] == [
        "LOCAL_MEASURED",
        "PROVIDER_REPORTED",
        "HOST_RATE_ESTIMATE",
        "RECONCILED",
    ]


def test_build_usage_evidence_is_canonical_and_deterministic() -> None:
    arguments = _valid_arguments()

    first_json, first_digest = build_usage_evidence(**arguments)
    second_json, second_digest = build_usage_evidence(**arguments)

    assert first_json == second_json
    assert first_digest == second_digest
    assert first_digest == hashlib.sha256(first_json.encode("utf-8")).hexdigest()
    assert first_json == json.dumps(
        {
            "authority": "LOCAL_MEASURED",
            "endpoint_alias": "batch-v1",
            "input_token_count": 120,
            "output_token_count": 45,
            "provider_alias": "openai-direct",
            "remote_batch_id": "batch_123",
            "request_count": 3,
            "source_id": "local-token-count-v1",
            "tenant_scope_id": "tenant-7f3a",
        },
        sort_keys=True,
        separators=(",", ":"),
    )


def test_optional_usage_dimensions_are_explicit_nulls() -> None:
    canonical_json, _digest = build_usage_evidence(
        authority=UsageAuthority.PROVIDER_REPORTED,
        tenant_scope_id="tenant-7f3a",
        source_id="provider-response-9",
        request_count=1,
    )

    assert json.loads(canonical_json) == {
        "authority": "PROVIDER_REPORTED",
        "endpoint_alias": None,
        "input_token_count": None,
        "output_token_count": None,
        "provider_alias": None,
        "remote_batch_id": None,
        "request_count": 1,
        "source_id": "provider-response-9",
        "tenant_scope_id": "tenant-7f3a",
    }


def test_authority_and_source_identity_change_the_evidence_digest() -> None:
    arguments = _valid_arguments()
    _base_json, base_digest = build_usage_evidence(**arguments)

    authority_arguments = dict(arguments)
    authority_arguments["authority"] = UsageAuthority.RECONCILED
    _authority_json, authority_digest = build_usage_evidence(**authority_arguments)

    source_arguments = dict(arguments)
    source_arguments["source_id"] = "reconciliation-export-2"
    _source_json, source_digest = build_usage_evidence(**source_arguments)

    assert len({base_digest, authority_digest, source_digest}) == 3


@pytest.mark.parametrize("authority", ["LOCAL_MEASURED", None, object()])
def test_authority_requires_the_closed_enum(authority: object) -> None:
    arguments = _valid_arguments()
    arguments["authority"] = authority

    with pytest.raises(UsageEvidenceError, match="^invalid usage evidence authority$"):
        build_usage_evidence(**arguments)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("tenant_scope_id", ""),
        ("tenant_scope_id", "tenant scope"),
        ("tenant_scope_id", "t" * 129),
        ("tenant_scope_id", object()),
        ("source_id", "source\ncontent"),
        ("provider_alias", "provider?query"),
        ("endpoint_alias", b"batch-v1"),
        ("remote_batch_id", {}),
    ],
)
def test_identifiers_reject_unbounded_or_content_bearing_values(
    field_name: str,
    value: object,
) -> None:
    arguments = _valid_arguments()
    arguments[field_name] = value

    with pytest.raises(UsageEvidenceError, match="^invalid usage evidence identifier$"):
        build_usage_evidence(**arguments)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("request_count", True),
        ("request_count", -1),
        ("request_count", 2**63),
        ("input_token_count", 1.5),
        ("input_token_count", float("inf")),
        ("output_token_count", object()),
    ],
)
def test_counts_reject_invalid_or_unbounded_values(field_name: str, value: object) -> None:
    arguments = _valid_arguments()
    arguments[field_name] = value

    with pytest.raises(UsageEvidenceError, match="^invalid usage evidence count$"):
        build_usage_evidence(**arguments)


def test_count_boundary_accepts_zero_and_signed_bigint_maximum() -> None:
    canonical_json, _digest = build_usage_evidence(
        authority=UsageAuthority.HOST_RATE_ESTIMATE,
        tenant_scope_id="tenant-7f3a",
        source_id="rate-card-2026-08-27",
        request_count=0,
        input_token_count=2**63 - 1,
        output_token_count=0,
    )

    evidence = json.loads(canonical_json)
    assert evidence["request_count"] == 0
    assert evidence["input_token_count"] == 2**63 - 1
    assert evidence["output_token_count"] == 0
