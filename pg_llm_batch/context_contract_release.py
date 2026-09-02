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
_DISTRIBUTION_SEPARATOR_PATTERN = re.compile(r"[-_.]+")
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
    checking one immutable publication and the pinned distribution bytes. Keeping the
    release pin inside the same value prevents callers from accidentally combining
    gate outcomes for one release with the identity of another release at the
    pg-llm-batch admission boundary. Construction alone grants no deployment approval.
    """

    release_pin: ContextContractReleasePin
    release_published: bool
    artifact_verified: bool
    conformance_passed: bool
    admission_passed: bool
    provenance_verified: bool


@dataclass(frozen=True, slots=True)
class ContextContractReleaseApproval:
    """Bind deployment-policy provenance to one exact verified release receipt.

    Verification and policy approval are intentionally separate roles. The trusted
    deployment or release-policy boundary supplies this value only after approving
    the exact subject-bound verification receipt. ``approval_policy_sha256`` is a
    content-free identity for that reviewed policy/configuration, not a signature or
    substitute for upstream release provenance.
    """

    verification: ContextContractReleaseVerification
    approval_policy_sha256: str


@dataclass(frozen=True, slots=True)
class ContextContractReleaseTransitionVerification:
    """Bind forward-migration and rollback evidence to one exact release change.

    A trusted migration-verification boundary supplies this receipt after exercising
    the transition from one immutable released contract to another. The two SHA-256
    fields identify content-free migration and rollback evidence; they are not
    signatures and do not replace release provenance or deployment-policy approval.
    """

    source_release_pin: ContextContractReleasePin
    target_release_pin: ContextContractReleasePin
    migration_evidence_sha256: str
    rollback_evidence_sha256: str
    migration_verified: bool
    rollback_verified: bool


def _invalid_release_pin() -> ContextContractReleasePinError:
    """Build the fixed non-reflecting error used for every invalid pin."""
    return ContextContractReleasePinError(_ERROR_MESSAGE)


def _validate_name(value: object) -> str:
    """Return one bounded path-free release identity component."""
    if type(value) is not str or _NAME_PATTERN.fullmatch(value) is None:
        raise _invalid_release_pin()
    return value


def _canonical_distribution_name(value: str) -> str:
    """Return the normalized Python distribution identity used for comparison."""
    return _DISTRIBUTION_SEPARATOR_PATTERN.sub("-", value).lower()


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
    identity and all five gate outcomes are then snapshotted and independently
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
        artifact_verified = verification.artifact_verified
        conformance_passed = verification.conformance_passed
        admission_passed = verification.admission_passed
        provenance_verified = verification.provenance_verified
    except AttributeError:
        raise _invalid_release_pin() from None

    validated_pin = validate_context_contract_release_pin(release_pin)
    _require_verified_gate(release_published)
    _require_verified_gate(artifact_verified)
    _require_verified_gate(conformance_passed)
    _require_verified_gate(admission_passed)
    _require_verified_gate(provenance_verified)

    return ContextContractReleaseVerification(
        release_pin=validated_pin,
        release_published=release_published,
        artifact_verified=artifact_verified,
        conformance_passed=conformance_passed,
        admission_passed=admission_passed,
        provenance_verified=provenance_verified,
    )


def validate_context_contract_release_approval(
    approval: ContextContractReleaseApproval,
) -> ContextContractReleaseApproval:
    """Snapshot policy approval for one exact verified immutable release.

    The exact package-owned approval type is required before members are read. The
    nested verification is revalidated independently, and the policy identity must
    be an exact lowercase SHA-256 digest. This keeps observed release evidence and
    deployment approval as separate audit roles while exposing no policy content.

    Args:
        approval: Policy-scoped approval supplied by the trusted deployment boundary.

    Returns:
        A fresh validated policy approval bound to a fresh verification snapshot.

    Raises:
        ContextContractReleasePinError: If approval evidence is malformed.
    """
    if type(approval) is not ContextContractReleaseApproval:
        raise _invalid_release_pin()

    try:
        verification = approval.verification
        approval_policy_sha256 = approval.approval_policy_sha256
    except AttributeError:
        raise _invalid_release_pin() from None

    return ContextContractReleaseApproval(
        verification=validate_context_contract_release_verification(verification),
        approval_policy_sha256=_validate_sha256(approval_policy_sha256),
    )


def validate_context_contract_release_transition_verification(
    transition: ContextContractReleaseTransitionVerification,
) -> ContextContractReleaseTransitionVerification:
    """Snapshot migration and rollback evidence for one immutable release change.

    Exact package-owned evidence is required before any member is read. Source and
    target pins are independently snapshotted and must identify different immutable
    releases. One normalized Python distribution/version pair may identify only one
    immutable release, so byte or source drift under the same version label fails
    closed even when equivalent ``-``, ``_``, or ``.`` name spellings are supplied.
    Evidence identities are bounded to lowercase SHA-256 digests, and both forward-
    migration and rollback gates must be exact built-in ``True`` values.

    Args:
        transition: Transition evidence from a trusted migration verifier.

    Returns:
        A fresh verification receipt bound to exact source and target releases.

    Raises:
        ContextContractReleasePinError: If any transition evidence is invalid.
    """
    if type(transition) is not ContextContractReleaseTransitionVerification:
        raise _invalid_release_pin()

    try:
        source_release_pin = transition.source_release_pin
        target_release_pin = transition.target_release_pin
        migration_evidence_sha256 = transition.migration_evidence_sha256
        rollback_evidence_sha256 = transition.rollback_evidence_sha256
        migration_verified = transition.migration_verified
        rollback_verified = transition.rollback_verified
    except AttributeError:
        raise _invalid_release_pin() from None

    validated_source = validate_context_contract_release_pin(source_release_pin)
    validated_target = validate_context_contract_release_pin(target_release_pin)
    same_distribution = _canonical_distribution_name(
        validated_source.distribution_name
    ) == _canonical_distribution_name(validated_target.distribution_name)
    if validated_source == validated_target or (
        same_distribution
        and validated_source.release_version == validated_target.release_version
    ):
        raise _invalid_release_pin()
    validated_migration = _validate_sha256(migration_evidence_sha256)
    validated_rollback = _validate_sha256(rollback_evidence_sha256)
    _require_verified_gate(migration_verified)
    _require_verified_gate(rollback_verified)

    return ContextContractReleaseTransitionVerification(
        source_release_pin=validated_source,
        target_release_pin=validated_target,
        migration_evidence_sha256=validated_migration,
        rollback_evidence_sha256=validated_rollback,
        migration_verified=migration_verified,
        rollback_verified=rollback_verified,
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
    approved: ContextContractReleaseApproval,
    required_approval_policy_sha256: str,
) -> ContextContractReleasePin:
    """Admit only artifact-verified release evidence approved by deployment policy.

    Release identity alone is insufficient authority because it cannot prove that
    publication, pinned distribution integrity, executable conformance, admission,
    and provenance verification actually succeeded. An observed verification receipt
    therefore cannot double as policy approval. The trusted deployment/release-policy
    boundary must provide a separate approval containing the exact verification plus
    a content-free policy SHA-256 identity, and the deployment must independently
    require that exact policy identity. This function neither discovers a release nor
    authenticates the external policy boundary itself.

    Args:
        verification: Subject-bound release identity and positive gate outcomes.
        approved: Distinct policy approval for the exact verification receipt.
        required_approval_policy_sha256: Exact deployment-configured policy identity
            that must match the approval receipt before interoperability is enabled.

    Returns:
        A fresh validated identity for the fully admitted released contract.

    Raises:
        ContextContractReleasePinError: If evidence, policy identity, or binding is
            invalid or inconsistent.
    """
    validated_verification = validate_context_contract_release_verification(
        verification
    )
    validated_approval = validate_context_contract_release_approval(approved)
    required_policy = _validate_sha256(required_approval_policy_sha256)
    if (
        validated_verification != validated_approval.verification
        or validated_approval.approval_policy_sha256 != required_policy
    ):
        raise _invalid_release_pin()
    return require_context_contract_release_compatibility(
        candidate=validated_verification.release_pin,
        approved=validated_approval.verification.release_pin,
    )


def require_context_contract_release_transition_ready(
    *,
    current_release: ContextContractReleasePin,
    verification: ContextContractReleaseVerification,
    approved: ContextContractReleaseApproval,
    required_approval_policy_sha256: str,
    transition: ContextContractReleaseTransitionVerification,
) -> ContextContractReleasePin:
    """Admit a release change only with exact migration and rollback evidence.

    The target release must first pass the ordinary publication, artifact integrity,
    conformance, admission, provenance, and deployment-policy boundary. Transition
    evidence is then independently validated and must name both the exact currently
    deployed release and the exact admitted target. No semantic-version ordering is
    inferred: upgrade, downgrade, or lateral compatibility remains an explicit
    operator-owned migration and rollback decision represented by supplied evidence.

    Args:
        current_release: Exact immutable release identity currently in use.
        verification: Positive release-readiness evidence for the target release.
        approved: Deployment-policy approval for the target verification.
        required_approval_policy_sha256: Deployment-configured policy identity.
        transition: Migration and rollback verification for this exact release pair.

    Returns:
        A fresh validated target release pin after all boundaries agree.

    Raises:
        ContextContractReleasePinError: If target readiness or transition evidence
            is malformed, incomplete, or bound to another release pair.
    """
    validated_current = validate_context_contract_release_pin(current_release)
    admitted_target = require_context_contract_release_ready(
        verification=verification,
        approved=approved,
        required_approval_policy_sha256=required_approval_policy_sha256,
    )
    validated_transition = validate_context_contract_release_transition_verification(
        transition
    )
    if (
        validated_transition.source_release_pin != validated_current
        or validated_transition.target_release_pin != admitted_target
    ):
        raise _invalid_release_pin()
    return admitted_target
