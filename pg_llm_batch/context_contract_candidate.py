# SPDX-License-Identifier: Apache-2.0
"""Validate test-only Context Fabric candidate compatibility evidence.

This module exists so pg-llm-batch can exercise an exact unreleased upstream
candidate without converting that candidate into production authority. Candidate
identity is bound to an immutable source commit and content digests, but it carries
no release version, publication gate, deployment approval, or authority to satisfy
the production release-admission functions in :mod:`context_contract_release`.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}\Z")
_SOURCE_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_ERROR_MESSAGE = "invalid contract candidate"


class ContextContractCandidateError(ValueError):
    """Report malformed candidate-only compatibility evidence without reflection.

    Candidate metadata may originate from an untrusted build or handoff surface.
    The fixed error text therefore never includes source refs, paths, digests, or
    other supplied values that could leak into logs or operator messages.
    """


@dataclass(frozen=True, slots=True)
class ContextContractCandidatePin:
    """Identify one exact unreleased Context Fabric candidate for test-only use.

    The candidate is intentionally identified by an immutable source commit and
    content digests rather than a branch or tag name. It has no release version or
    publication state, so this value cannot be confused with
    ``ContextContractReleasePin`` at the production admission boundary.
    """

    source_commit: str
    candidate_artifact_sha256: str
    profile_name: str
    profile_sha256: str
    resource_name: str
    resource_sha256: str
    conformance_sha256: str
    admission_sha256: str
    provenance_sha256: str


@dataclass(frozen=True, slots=True)
class ContextContractCandidateVerification:
    """Bind candidate test evidence to one exact candidate identity.

    A test or integration-verification boundary constructs this receipt only after
    hashing the candidate artifact and exercising its conformance, admission, and
    provenance checks. Positive candidate verification remains pre-release evidence;
    it does not imply publication, deployment approval, or production admission.
    """

    candidate_pin: ContextContractCandidatePin
    artifact_verified: bool
    conformance_passed: bool
    admission_passed: bool
    provenance_verified: bool


def _invalid_candidate() -> ContextContractCandidateError:
    """Build the fixed non-reflecting error for invalid candidate evidence."""
    return ContextContractCandidateError(_ERROR_MESSAGE)


def _validate_name(value: object) -> str:
    """Return one bounded path-free candidate identity component."""
    if type(value) is not str or _NAME_PATTERN.fullmatch(value) is None:
        raise _invalid_candidate()
    return value


def _validate_source_commit(value: object) -> str:
    """Return one exact lowercase Git commit identity for candidate source."""
    if type(value) is not str or _SOURCE_COMMIT_PATTERN.fullmatch(value) is None:
        raise _invalid_candidate()
    return value


def _validate_sha256(value: object) -> str:
    """Return one exact lowercase SHA-256 identity without coercing input."""
    if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
        raise _invalid_candidate()
    return value


def _require_verified_gate(value: object) -> None:
    """Require an exact built-in ``True`` candidate verification outcome."""
    if type(value) is not bool or not value:
        raise _invalid_candidate()


def validate_context_contract_candidate_pin(
    candidate: ContextContractCandidatePin,
) -> ContextContractCandidatePin:
    """Snapshot one immutable candidate identity without granting release authority.

    The exact package-owned candidate type is required before any member is read.
    Every field is then snapshotted once and validated as an immutable commit or
    content identity. Mutable branch aliases cannot pass because no ref-name field
    exists and ``source_commit`` accepts only a lowercase forty-hex commit identity.

    Args:
        candidate: Candidate-only identity supplied by a test discovery boundary.

    Returns:
        A fresh validated candidate snapshot suitable for compatibility testing.

    Raises:
        ContextContractCandidateError: If the candidate type or identity is invalid.
    """
    if type(candidate) is not ContextContractCandidatePin:
        raise _invalid_candidate()

    try:
        source_commit = candidate.source_commit
        candidate_artifact_sha256 = candidate.candidate_artifact_sha256
        profile_name = candidate.profile_name
        profile_sha256 = candidate.profile_sha256
        resource_name = candidate.resource_name
        resource_sha256 = candidate.resource_sha256
        conformance_sha256 = candidate.conformance_sha256
        admission_sha256 = candidate.admission_sha256
        provenance_sha256 = candidate.provenance_sha256
    except AttributeError:
        raise _invalid_candidate() from None

    return ContextContractCandidatePin(
        source_commit=_validate_source_commit(source_commit),
        candidate_artifact_sha256=_validate_sha256(candidate_artifact_sha256),
        profile_name=_validate_name(profile_name),
        profile_sha256=_validate_sha256(profile_sha256),
        resource_name=_validate_name(resource_name),
        resource_sha256=_validate_sha256(resource_sha256),
        conformance_sha256=_validate_sha256(conformance_sha256),
        admission_sha256=_validate_sha256(admission_sha256),
        provenance_sha256=_validate_sha256(provenance_sha256),
    )


def validate_context_contract_candidate_verification(
    verification: ContextContractCandidateVerification,
) -> ContextContractCandidateVerification:
    """Validate positive test evidence bound to one exact unreleased candidate.

    Candidate artifact integrity, executable conformance, admission, and provenance
    must each be exact built-in ``True`` values. The function returns a fresh receipt
    so later mutation of a nominally frozen input cannot silently alter the accepted
    test evidence. The result remains candidate-only and is not a release receipt.

    Args:
        verification: Candidate-scoped evidence from a test verification boundary.

    Returns:
        A fresh verification receipt bound to a fresh candidate identity snapshot.

    Raises:
        ContextContractCandidateError: If identity or verification evidence is invalid.
    """
    if type(verification) is not ContextContractCandidateVerification:
        raise _invalid_candidate()

    try:
        candidate_pin = verification.candidate_pin
        artifact_verified = verification.artifact_verified
        conformance_passed = verification.conformance_passed
        admission_passed = verification.admission_passed
        provenance_verified = verification.provenance_verified
    except AttributeError:
        raise _invalid_candidate() from None

    validated_pin = validate_context_contract_candidate_pin(candidate_pin)
    _require_verified_gate(artifact_verified)
    _require_verified_gate(conformance_passed)
    _require_verified_gate(admission_passed)
    _require_verified_gate(provenance_verified)

    return ContextContractCandidateVerification(
        candidate_pin=validated_pin,
        artifact_verified=artifact_verified,
        conformance_passed=conformance_passed,
        admission_passed=admission_passed,
        provenance_verified=provenance_verified,
    )


def require_context_contract_candidate_compatibility(
    *,
    verification: ContextContractCandidateVerification,
    expected: ContextContractCandidatePin,
) -> ContextContractCandidatePin:
    """Accept only a positively verified candidate matching an exact test expectation.

    This helper lets pg-llm-batch preflight a specific upstream PR-head artifact while
    Context Fabric has no immutable release. ``expected`` is test configuration, not
    production authority. Exact equality binds source, artifact, profile, resource,
    conformance, admission, and provenance identities. The returned candidate type
    cannot satisfy the distinct production release-admission API.

    Args:
        verification: Positive evidence for the observed unreleased candidate.
        expected: Exact candidate identity intentionally selected for this test run.

    Returns:
        A fresh candidate-only pin when observed and expected identities agree.

    Raises:
        ContextContractCandidateError: If evidence is invalid or identities differ.
    """
    validated_verification = validate_context_contract_candidate_verification(
        verification
    )
    validated_expected = validate_context_contract_candidate_pin(expected)
    if validated_verification.candidate_pin != validated_expected:
        raise _invalid_candidate()
    return validated_verification.candidate_pin
