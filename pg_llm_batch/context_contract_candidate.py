# SPDX-License-Identifier: Apache-2.0
"""Validate test-only Context Fabric candidate compatibility evidence.

This module exists so pg-llm-batch can exercise an exact unreleased upstream
candidate without converting that candidate into production authority. Candidate
identity is bound to an immutable distribution name, source commit, and content
digests, but it carries no release version, publication gate, deployment approval,
or authority to satisfy the production release-admission functions in
:mod:`context_contract_release`.
"""

from __future__ import annotations

from dataclasses import dataclass
import re

from .context_contract_release import (
    ContextContractReleasePin,
    _canonical_distribution_name,
    validate_context_contract_release_pin,
)


_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}\Z")
_DISTRIBUTION_NAME_PATTERN = re.compile(
    r"[A-Za-z0-9](?:[A-Za-z0-9._-]{0,126}[A-Za-z0-9])?\Z"
)
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

    The candidate is intentionally identified by an immutable distribution name,
    source commit, and content digests rather than a branch or tag name. It has no
    release version or publication state, so this value cannot be confused with
    ``ContextContractReleasePin`` at the production admission boundary.
    """

    distribution_name: str
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


def _validate_distribution_name(value: object) -> str:
    """Return one bounded Python distribution name accepted by packaging specs."""
    if type(value) is not str or _DISTRIBUTION_NAME_PATTERN.fullmatch(value) is None:
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
    Every field is then snapshotted once and validated as a distribution, immutable
    commit, or content identity. Mutable branch aliases cannot pass because no
    ref-name field exists and ``source_commit`` accepts only a lowercase forty-hex
    commit identity.

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
        distribution_name = candidate.distribution_name
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
        distribution_name=_validate_distribution_name(distribution_name),
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
    """Accept only a positively verified candidate matching one test expectation.

    This helper lets pg-llm-batch preflight a specific upstream PR-head artifact while
    Context Fabric has no immutable release. ``expected`` is test configuration, not
    production authority. Python packaging-equivalent distribution spellings identify
    the same project; source, artifact, profile, resource, conformance, admission, and
    provenance identities remain exact. The returned candidate type cannot satisfy
    the distinct production release-admission API.

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
    candidate = validated_verification.candidate_pin
    if (
        _canonical_distribution_name(candidate.distribution_name)
        != _canonical_distribution_name(validated_expected.distribution_name)
        or candidate.source_commit != validated_expected.source_commit
        or candidate.candidate_artifact_sha256
        != validated_expected.candidate_artifact_sha256
        or candidate.profile_name != validated_expected.profile_name
        or candidate.profile_sha256 != validated_expected.profile_sha256
        or candidate.resource_name != validated_expected.resource_name
        or candidate.resource_sha256 != validated_expected.resource_sha256
        or candidate.conformance_sha256 != validated_expected.conformance_sha256
        or candidate.admission_sha256 != validated_expected.admission_sha256
        or candidate.provenance_sha256 != validated_expected.provenance_sha256
    ):
        raise _invalid_candidate()
    return candidate


def require_context_contract_candidate_release_identity(
    *,
    verification: ContextContractCandidateVerification,
    release: ContextContractReleasePin,
) -> ContextContractCandidatePin:
    """Require a later immutable publication to match the tested candidate identity.

    This is a continuity check, not release admission. It proves only that the
    normalized Python distribution identity plus exact source, distribution bytes,
    semantic profile, resource, conformance, admission, and provenance identities in
    a syntactically valid release pin match the candidate that previously passed
    pre-release verification. Publication status, deployment-policy approval, and
    production readiness still belong to the separate release-admission boundary.

    Args:
        verification: Positive pre-release verification for the tested candidate.
        release: Immutable released identity observed after publication appears.

    Returns:
        A fresh candidate-only pin when the release preserves the tested identities.

    Raises:
        ContextContractCandidateError: If the release drifts from the tested candidate.
        ContextContractReleasePinError: If the supplied release identity is malformed.
    """
    validated_verification = validate_context_contract_candidate_verification(
        verification
    )
    validated_release = validate_context_contract_release_pin(release)
    candidate = validated_verification.candidate_pin
    if (
        _canonical_distribution_name(candidate.distribution_name)
        != _canonical_distribution_name(validated_release.distribution_name)
        or candidate.source_commit != validated_release.source_commit
        or candidate.candidate_artifact_sha256
        != validated_release.distribution_sha256
        or candidate.profile_name != validated_release.profile_name
        or candidate.profile_sha256 != validated_release.profile_sha256
        or candidate.resource_name != validated_release.resource_name
        or candidate.resource_sha256 != validated_release.resource_sha256
        or candidate.conformance_sha256 != validated_release.conformance_sha256
        or candidate.admission_sha256 != validated_release.admission_sha256
        or candidate.provenance_sha256 != validated_release.provenance_sha256
    ):
        raise _invalid_candidate()
    return candidate
