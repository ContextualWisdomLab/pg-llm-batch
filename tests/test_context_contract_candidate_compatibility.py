# SPDX-License-Identifier: Apache-2.0
"""Candidate-only compatibility contracts for unreleased Context Fabric heads."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pg_llm_batch.context_contract_candidate import (
    ContextContractCandidateError,
    ContextContractCandidatePin,
    ContextContractCandidateVerification,
    require_context_contract_candidate_compatibility,
    require_context_contract_candidate_release_identity,
    validate_context_contract_candidate_pin,
    validate_context_contract_candidate_verification,
)
from pg_llm_batch.context_contract_release import (
    ContextContractReleasePin,
    ContextContractReleasePinError,
    validate_context_contract_release_pin,
)


VALID_CANDIDATE = ContextContractCandidatePin(
    source_commit="a" * 40,
    candidate_artifact_sha256="b" * 64,
    profile_name="context-assertion-event-semantics.v1.json",
    profile_sha256="c" * 64,
    resource_name="context-assertion.schema.json",
    resource_sha256="d" * 64,
    conformance_sha256="e" * 64,
    admission_sha256="f" * 64,
    provenance_sha256="1" * 64,
)
VALID_CANDIDATE_VERIFICATION = ContextContractCandidateVerification(
    candidate_pin=VALID_CANDIDATE,
    artifact_verified=True,
    conformance_passed=True,
    admission_passed=True,
    provenance_verified=True,
)
VALID_RELEASE = ContextContractReleasePin(
    distribution_name="cwl-context-contracts",
    release_version="0.1.0",
    source_commit=VALID_CANDIDATE.source_commit,
    distribution_sha256=VALID_CANDIDATE.candidate_artifact_sha256,
    profile_name=VALID_CANDIDATE.profile_name,
    profile_sha256=VALID_CANDIDATE.profile_sha256,
    resource_name=VALID_CANDIDATE.resource_name,
    resource_sha256=VALID_CANDIDATE.resource_sha256,
    conformance_sha256=VALID_CANDIDATE.conformance_sha256,
    admission_sha256=VALID_CANDIDATE.admission_sha256,
    provenance_sha256=VALID_CANDIDATE.provenance_sha256,
)


def test_candidate_verification_accepts_exact_test_only_identity() -> None:
    validated = validate_context_contract_candidate_verification(
        VALID_CANDIDATE_VERIFICATION
    )

    assert validated == VALID_CANDIDATE_VERIFICATION
    assert validated is not VALID_CANDIDATE_VERIFICATION
    assert validated.candidate_pin is not VALID_CANDIDATE


def test_candidate_compatibility_accepts_exact_expected_identity() -> None:
    admitted = require_context_contract_candidate_compatibility(
        verification=VALID_CANDIDATE_VERIFICATION,
        expected=replace(VALID_CANDIDATE),
    )

    assert admitted == VALID_CANDIDATE
    assert admitted is not VALID_CANDIDATE


def test_candidate_release_identity_accepts_byte_identical_publication() -> None:
    matched = require_context_contract_candidate_release_identity(
        verification=VALID_CANDIDATE_VERIFICATION,
        release=VALID_RELEASE,
    )

    assert matched == VALID_CANDIDATE
    assert matched is not VALID_CANDIDATE


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_commit", "2" * 40),
        ("distribution_sha256", "2" * 64),
        ("profile_name", "different-profile.json"),
        ("profile_sha256", "3" * 64),
        ("resource_name", "different-resource.json"),
        ("resource_sha256", "4" * 64),
        ("conformance_sha256", "5" * 64),
        ("admission_sha256", "6" * 64),
        ("provenance_sha256", "7" * 64),
    ],
)
def test_candidate_release_identity_rejects_publication_drift(
    field: str,
    value: str,
) -> None:
    release = replace(VALID_RELEASE, **{field: value})

    with pytest.raises(ContextContractCandidateError) as raised:
        require_context_contract_candidate_release_identity(
            verification=VALID_CANDIDATE_VERIFICATION,
            release=release,
        )

    assert str(raised.value) == "invalid contract candidate"
    assert value not in str(raised.value)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("source_commit", "main"),
        ("source_commit", "A" * 40),
        ("candidate_artifact_sha256", "b" * 63),
        ("profile_name", "../profile.json"),
        ("profile_sha256", "C" * 64),
        ("resource_name", "resource/schema.json"),
        ("resource_sha256", None),
        ("conformance_sha256", True),
        ("admission_sha256", "f" * 65),
        ("provenance_sha256", "1" * 63),
    ],
)
def test_candidate_pin_rejects_mutable_or_malformed_identity(
    field: str,
    value: object,
) -> None:
    candidate = replace(VALID_CANDIDATE, **{field: value})  # type: ignore[arg-type]

    with pytest.raises(ContextContractCandidateError, match="invalid contract candidate"):
        validate_context_contract_candidate_pin(candidate)


def test_candidate_pin_rejects_deleted_member() -> None:
    candidate = replace(VALID_CANDIDATE)
    object.__delattr__(candidate, "resource_sha256")

    with pytest.raises(ContextContractCandidateError, match="invalid contract candidate"):
        validate_context_contract_candidate_pin(candidate)


@pytest.mark.parametrize(
    "failed_gate",
    [
        "artifact_verified",
        "conformance_passed",
        "admission_passed",
        "provenance_verified",
    ],
)
def test_candidate_verification_rejects_missing_evidence(failed_gate: str) -> None:
    verification = replace(
        VALID_CANDIDATE_VERIFICATION,
        **{failed_gate: False},
    )

    with pytest.raises(ContextContractCandidateError, match="invalid contract candidate"):
        validate_context_contract_candidate_verification(verification)


@pytest.mark.parametrize("invalid_gate", [1, 0, "true", None])
def test_candidate_verification_rejects_non_boolean_evidence(
    invalid_gate: object,
) -> None:
    verification = replace(
        VALID_CANDIDATE_VERIFICATION,
        artifact_verified=invalid_gate,  # type: ignore[arg-type]
    )

    with pytest.raises(ContextContractCandidateError, match="invalid contract candidate"):
        validate_context_contract_candidate_verification(verification)


def test_candidate_verification_rejects_deleted_member() -> None:
    verification = replace(VALID_CANDIDATE_VERIFICATION)
    object.__delattr__(verification, "provenance_verified")

    with pytest.raises(ContextContractCandidateError, match="invalid contract candidate"):
        validate_context_contract_candidate_verification(verification)


def test_candidate_verification_rejects_shaped_object_before_member_access() -> None:
    class HostileVerification:
        @property
        def candidate_pin(self) -> ContextContractCandidatePin:
            raise AssertionError("untrusted verification member accessed")

    with pytest.raises(ContextContractCandidateError, match="invalid contract candidate"):
        validate_context_contract_candidate_verification(
            HostileVerification()  # type: ignore[arg-type]
        )


def test_candidate_compatibility_rejects_exact_identity_drift() -> None:
    expected = replace(VALID_CANDIDATE, source_commit="2" * 40)

    with pytest.raises(ContextContractCandidateError) as raised:
        require_context_contract_candidate_compatibility(
            verification=VALID_CANDIDATE_VERIFICATION,
            expected=expected,
        )

    assert str(raised.value) == "invalid contract candidate"
    assert "2" * 40 not in str(raised.value)


def test_candidate_verification_revalidates_mutated_frozen_input() -> None:
    verification = replace(VALID_CANDIDATE_VERIFICATION)
    object.__setattr__(verification, "artifact_verified", "operator-secret")

    with pytest.raises(ContextContractCandidateError) as raised:
        validate_context_contract_candidate_verification(verification)

    assert str(raised.value) == "invalid contract candidate"
    assert "operator-secret" not in str(raised.value)


def test_candidate_pin_rejects_shaped_object_before_member_access() -> None:
    class HostileCandidate:
        @property
        def source_commit(self) -> str:
            raise AssertionError("untrusted candidate member accessed")

    with pytest.raises(ContextContractCandidateError, match="invalid contract candidate"):
        validate_context_contract_candidate_pin(HostileCandidate())  # type: ignore[arg-type]


def test_candidate_pin_cannot_be_promoted_to_released_identity() -> None:
    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        validate_context_contract_release_pin(VALID_CANDIDATE)  # type: ignore[arg-type]
