# SPDX-License-Identifier: Apache-2.0
"""Validate immutable identity pins for optional Context Fabric contracts.

This module deliberately validates only bounded release identity metadata. It does
not discover releases, trust mutable branches, fetch schemas, or grant model,
provider, routing, architecture, or publication authority to pg-llm-batch.
"""

from __future__ import annotations

from dataclasses import dataclass
import re


_NAME_PATTERN = re.compile(r"[A-Za-z0-9][A-Za-z0-9._+-]{0,127}\Z")
_SOURCE_COMMIT_PATTERN = re.compile(r"[0-9a-f]{40}\Z")
_SHA256_PATTERN = re.compile(r"[0-9a-f]{64}\Z")
_MUTABLE_RELEASE_ALIASES = frozenset(
    {"head", "latest", "main", "master", "develop", "snapshot", "nightly"}
)
_ERROR_MESSAGE = "invalid release pin"


class ContextContractReleasePinError(ValueError):
    """Report malformed immutable Context Fabric release identity evidence.

    The exception intentionally uses a fixed message so hostile release metadata
    cannot be reflected into logs or operator surfaces through validation errors.
    """


@dataclass(frozen=True, slots=True)
class ContextContractReleasePin:
    """Carry exact identities required to consume one released contract safely.

    These fields are evidence supplied by a trusted release-discovery boundary;
    constructing this value does not itself prove that the release exists or that
    any referenced provenance, conformance, or admission evidence is authentic.
    """

    distribution_name: str
    release_version: str
    source_commit: str
    distribution_sha256: str
    profile_name: str
    profile_sha256: str
    resource_name: str
    resource_sha256: str
    conformance_sha256: str
    admission_sha256: str
    provenance_sha256: str


@dataclass(frozen=True, slots=True)
class ContextContractReleaseVerification:
    """Bind release-readiness outcomes to the exact release identity they verify.

    A trusted discovery and verification boundary constructs this receipt only after
    checking one immutable publication. Keeping the release pin inside the same
    value prevents callers from accidentally combining gate outcomes for one release
    with the identity of another release at the pg-llm-batch admission boundary.
    Construction alone grants no authority; the receipt is revalidated before use.
    """

    release_pin: ContextContractReleasePin
    release_published: bool
    conformance_passed: bool
    admission_passed: bool
    provenance_verified: bool


def _invalid_release_pin() -> ContextContractReleasePinError:
    """Build the fixed non-reflecting error used for every invalid pin."""
    return ContextContractReleasePinError(_ERROR_MESSAGE)


def _validate_name(value: object) -> str:
    """Return one bounded path-free release identity component."""
    if type(value) is not str or _NAME_PATTERN.fullmatch(value) is None:
        raise _invalid_release_pin()
    return value


def _validate_release_version(value: object) -> str:
    """Return one immutable version label while rejecting branch-like aliases."""
    version = _validate_name(value)
    if version.lower() in _MUTABLE_RELEASE_ALIASES:
        raise _invalid_release_pin()
    return version


def _validate_source_commit(value: object) -> str:
    """Return one exact lowercase Git object identity for released source."""
    if type(value) is not str or _SOURCE_COMMIT_PATTERN.fullmatch(value) is None:
        raise _invalid_release_pin()
    return value


def _validate_sha256(value: object) -> str:
    """Return one exact lowercase SHA-256 identity without coercing input."""
    if type(value) is not str or _SHA256_PATTERN.fullmatch(value) is None:
        raise _invalid_release_pin()
    return value


def _require_verified_gate(value: object) -> None:
    """Reject absent, false, or shaped release-readiness gate evidence."""
    if type(value) is not bool or not value:
        raise _invalid_release_pin()


def validate_context_contract_release_pin(
    pin: ContextContractReleasePin,
) -> ContextContractReleasePin:
    """Snapshot and validate one immutable Context Fabric release identity pin.

    The validator accepts only the exact package-owned value type, snapshots every
    member once, validates immutable source and artifact identities, and returns a
    fresh value. It does not prove release existence, signature validity, trusted
    provenance, schema compatibility, or conformance success; callers must obtain
    those facts from the released Context Fabric authority before interoperability
    is enabled.

    Args:
        pin: Candidate release identity supplied by a trusted discovery boundary.

    Returns:
        A fresh validated snapshot suitable for later release-evidence checks.

    Raises:
        ContextContractReleasePinError: If any identity is mutable or malformed.
    """
    if type(pin) is not ContextContractReleasePin:
        raise _invalid_release_pin()

    try:
        distribution_name = pin.distribution_name
        release_version = pin.release_version
        source_commit = pin.source_commit
        distribution_sha256 = pin.distribution_sha256
        profile_name = pin.profile_name
        profile_sha256 = pin.profile_sha256
        resource_name = pin.resource_name
        resource_sha256 = pin.resource_sha256
        conformance_sha256 = pin.conformance_sha256
        admission_sha256 = pin.admission_sha256
        provenance_sha256 = pin.provenance_sha256
    except AttributeError:
        raise _invalid_release_pin() from None

    return ContextContractReleasePin(
        distribution_name=_validate_name(distribution_name),
        release_version=_validate_release_version(release_version),
        source_commit=_validate_source_commit(source_commit),
        distribution_sha256=_validate_sha256(distribution_sha256),
        profile_name=_validate_name(profile_name),
        profile_sha256=_validate_sha256(profile_sha256),
        resource_name=_validate_name(resource_name),
        resource_sha256=_validate_sha256(resource_sha256),
        conformance_sha256=_validate_sha256(conformance_sha256),
        admission_sha256=_validate_sha256(admission_sha256),
        provenance_sha256=_validate_sha256(provenance_sha256),
    )


def validate_context_contract_release_verification(
    verification: ContextContractReleaseVerification,
) -> ContextContractReleaseVerification:
    """Snapshot and validate subject-bound Context Fabric release verification.

    The package-owned receipt type is checked before any member is read. The release
    identity and all four gate outcomes are then snapshotted and independently
    validated so shaped objects, mutable aliases, non-boolean truthy values, or a
    mutated frozen receipt fail through the same non-reflecting error boundary.

    Args:
        verification: Release-scoped evidence from a trusted verification boundary.

    Returns:
        A fresh receipt whose pin and required gate outcomes are valid.

    Raises:
        ContextContractReleasePinError: If the receipt or any member is invalid.
    """
    if type(verification) is not ContextContractReleaseVerification:
        raise _invalid_release_pin()

    try:
        release_pin = verification.release_pin
        release_published = verification.release_published
        conformance_passed = verification.conformance_passed
        admission_passed = verification.admission_passed
        provenance_verified = verification.provenance_verified
    except AttributeError:
        raise _invalid_release_pin() from None

    validated_pin = validate_context_contract_release_pin(release_pin)
    _require_verified_gate(release_published)
    _require_verified_gate(conformance_passed)
    _require_verified_gate(admission_passed)
    _require_verified_gate(provenance_verified)

    return ContextContractReleaseVerification(
        release_pin=validated_pin,
        release_published=release_published,
        conformance_passed=conformance_passed,
        admission_passed=admission_passed,
        provenance_verified=provenance_verified,
    )


def require_context_contract_release_compatibility(
    *,
    candidate: ContextContractReleasePin,
    approved: ContextContractReleasePin,
) -> ContextContractReleasePin:
    """Admit only a release pin identical to the approved immutable identity.

    Both values are independently snapshotted and validated before comparison. The
    approved value must come from a trusted operator or release-policy boundary;
    this function does not discover or authenticate releases. Exact equality binds
    distribution/version/source plus profile, resource, conformance, admission,
    and provenance evidence so syntactically valid drift fails closed before a
    future Context Fabric adapter can emit interoperable evidence.

    Args:
        candidate: Release identity observed by the consumer discovery boundary.
        approved: Exact immutable release identity approved for this deployment.

    Returns:
        A fresh validated copy of the admitted candidate identity.

    Raises:
        ContextContractReleasePinError: If either pin is invalid or identities differ.
    """
    validated_candidate = validate_context_contract_release_pin(candidate)
    validated_approved = validate_context_contract_release_pin(approved)
    if validated_candidate != validated_approved:
        raise _invalid_release_pin()
    return validated_candidate


def require_context_contract_release_ready(
    *,
    verification: ContextContractReleaseVerification,
    approved: ContextContractReleasePin,
) -> ContextContractReleasePin:
    """Admit only subject-bound verification for the approved immutable release.

    Release publication, executable conformance, admission, and provenance outcomes
    travel with the exact release pin they verify. This prevents independent boolean
    evidence from one release being accidentally paired with another release identity
    at the consumer boundary. The approved pin must still come from trusted operator
    or deployment policy; this function does not discover or authenticate releases.

    Args:
        verification: Subject-bound release identity and positive gate outcomes.
        approved: Exact immutable release identity approved for this deployment.

    Returns:
        A fresh validated identity for the fully admitted released contract.

    Raises:
        ContextContractReleasePinError: If evidence or approved identity is invalid.
    """
    validated_verification = validate_context_contract_release_verification(
        verification
    )
    return require_context_contract_release_compatibility(
        candidate=validated_verification.release_pin,
        approved=approved,
    )
