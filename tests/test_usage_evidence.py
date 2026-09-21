# SPDX-License-Identifier: Apache-2.0
"""Tests for deterministic, provenance-distinct usage evidence."""

from __future__ import annotations

import hashlib
import json

import pytest

from pg_llm_batch.usage_evidence import (
    UsageAuthority,
    UsageCompleteness,
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
        "input_token_completeness": UsageCompleteness.COMPLETE,
        "output_token_count": 45,
        "output_token_completeness": UsageCompleteness.COMPLETE,
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


def test_usage_completeness_vocabulary_is_closed() -> None:
    assert [completeness.value for completeness in UsageCompleteness] == [
        "COMPLETE",
        "PARTIAL",
        "UNAVAILABLE",
        "MIXED",
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
            "input_token_completeness": "COMPLETE",
            "input_token_count": 120,
            "output_token_completeness": "COMPLETE",
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


def test_unavailable_usage_dimensions_are_explicit_and_not_zero() -> None:
    canonical_json, _digest = build_usage_evidence(
        authority=UsageAuthority.PROVIDER_REPORTED,
        tenant_scope_id="tenant-7f3a",
        source_id="provider-response-9",
        request_count=1,
        input_token_completeness=UsageCompleteness.UNAVAILABLE,
        output_token_completeness=UsageCompleteness.UNAVAILABLE,
    )

    assert json.loads(canonical_json) == {
        "authority": "PROVIDER_REPORTED",
        "endpoint_alias": None,
        "input_token_completeness": "UNAVAILABLE",
        "input_token_count": None,
        "output_token_completeness": "UNAVAILABLE",
        "output_token_count": None,
        "provider_alias": None,
        "remote_batch_id": None,
        "request_count": 1,
        "source_id": "provider-response-9",
        "tenant_scope_id": "tenant-7f3a",
    }


def test_measured_zero_is_distinct_from_unavailable_usage() -> None:
    measured_json, measured_digest = build_usage_evidence(
        authority=UsageAuthority.PROVIDER_REPORTED,
        tenant_scope_id="tenant-7f3a",
        source_id="provider-response-10",
        request_count=1,
        input_token_count=0,
        input_token_completeness=UsageCompleteness.COMPLETE,
        output_token_count=0,
        output_token_completeness=UsageCompleteness.COMPLETE,
    )
    unavailable_json, unavailable_digest = build_usage_evidence(
        authority=UsageAuthority.PROVIDER_REPORTED,
        tenant_scope_id="tenant-7f3a",
        source_id="provider-response-10",
        request_count=1,
        input_token_completeness=UsageCompleteness.UNAVAILABLE,
        output_token_completeness=UsageCompleteness.UNAVAILABLE,
    )

    measured = json.loads(measured_json)
    unavailable = json.loads(unavailable_json)
    assert measured["input_token_count"] == 0
    assert measured["input_token_completeness"] == "COMPLETE"
    assert unavailable["input_token_count"] is None
    assert unavailable["input_token_completeness"] == "UNAVAILABLE"
    assert measured_digest != unavailable_digest


def test_reconciled_usage_can_preserve_mixed_and_partial_completeness() -> None:
    canonical_json, _digest = build_usage_evidence(
        authority=UsageAuthority.RECONCILED,
        tenant_scope_id="tenant-7f3a",
        source_id="reconciliation-export-3",
        request_count=4,
        input_token_count=200,
        input_token_completeness=UsageCompleteness.MIXED,
        output_token_count=55,
        output_token_completeness=UsageCompleteness.PARTIAL,
    )

    evidence = json.loads(canonical_json)
    assert evidence["input_token_count"] == 200
    assert evidence["input_token_completeness"] == "MIXED"
    assert evidence["output_token_count"] == 55
    assert evidence["output_token_completeness"] == "PARTIAL"


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


@pytest.mark.parametrize("completeness", ["COMPLETE", None, object()])
def test_completeness_requires_the_closed_enum(completeness: object) -> None:
    arguments = _valid_arguments()
    arguments["input_token_completeness"] = completeness

    with pytest.raises(UsageEvidenceError, match="^invalid usage evidence completeness$"):
        build_usage_evidence(**arguments)


@pytest.mark.parametrize(
    ("count_field", "completeness_field", "count", "completeness"),
    [
        (
            "input_token_count",
            "input_token_completeness",
            0,
            UsageCompleteness.UNAVAILABLE,
        ),
        (
            "output_token_count",
            "output_token_completeness",
            None,
            UsageCompleteness.COMPLETE,
        ),
        (
            "input_token_count",
            "input_token_completeness",
            None,
            UsageCompleteness.PARTIAL,
        ),
        (
            "output_token_count",
            "output_token_completeness",
            None,
            UsageCompleteness.MIXED,
        ),
    ],
)
def test_count_and_completeness_fail_closed_on_lossy_combinations(
    count_field: str,
    completeness_field: str,
    count: object,
    completeness: UsageCompleteness,
) -> None:
    arguments = _valid_arguments()
    arguments[count_field] = count
    arguments[completeness_field] = completeness

    with pytest.raises(UsageEvidenceError, match="^inconsistent usage evidence completeness$"):
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


def test_count_boundary_accepts_zero_and_json_interoperability_maximum() -> None:
    canonical_json, _digest = build_usage_evidence(
        authority=UsageAuthority.HOST_RATE_ESTIMATE,
        tenant_scope_id="tenant-7f3a",
        source_id="rate-card-2026-08-27",
        request_count=0,
        input_token_count=2**53 - 1,
        input_token_completeness=UsageCompleteness.COMPLETE,
        output_token_count=0,
        output_token_completeness=UsageCompleteness.COMPLETE,
    )

    evidence = json.loads(canonical_json)
    assert evidence["request_count"] == 0
    assert evidence["input_token_count"] == 2**53 - 1
    assert evidence["input_token_completeness"] == "COMPLETE"
    assert evidence["output_token_count"] == 0
    assert evidence["output_token_completeness"] == "COMPLETE"
