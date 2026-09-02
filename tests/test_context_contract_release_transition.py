# SPDX-License-Identifier: Apache-2.0
"""Migration and rollback guards for optional Context Fabric release changes."""

from __future__ import annotations

from dataclasses import replace

import pytest

from pg_llm_batch.context_contract_release import (
    ContextContractReleaseApproval,
    ContextContractReleasePin,
    ContextContractReleasePinError,
    ContextContractReleaseTransitionVerification,
    ContextContractReleaseVerification,
    require_context_contract_release_transition_ready,
    validate_context_contract_release_transition_verification,
)


CURRENT_PIN = ContextContractReleasePin(
    distribution_name="future-context-contract-package",
    release_version="0.1.0",
    source_commit="a" * 40,
    distribution_sha256="b" * 64,
    profile_name="context-assertion-event-semantics.v1.json",
    profile_sha256="c" * 64,
    resource_name="context-assertion.schema.json",
    resource_sha256="d" * 64,
    conformance_sha256="e" * 64,
    admission_sha256="f" * 64,
    provenance_sha256="1" * 64,
)
TARGET_PIN = replace(
    CURRENT_PIN,
    release_version="0.2.0",
    source_commit="2" * 40,
    distribution_sha256="3" * 64,
    profile_sha256="4" * 64,
    resource_sha256="5" * 64,
    conformance_sha256="6" * 64,
    admission_sha256="7" * 64,
    provenance_sha256="8" * 64,
)
TARGET_VERIFICATION = ContextContractReleaseVerification(
    release_pin=TARGET_PIN,
    release_published=True,
    conformance_passed=True,
    admission_passed=True,
    provenance_verified=True,
)
TARGET_APPROVAL = ContextContractReleaseApproval(
    verification=TARGET_VERIFICATION,
    approval_policy_sha256="9" * 64,
)
REQUIRED_POLICY_SHA256 = "9" * 64
TRANSITION = ContextContractReleaseTransitionVerification(
    source_release_pin=CURRENT_PIN,
    target_release_pin=TARGET_PIN,
    migration_evidence_sha256="a" * 64,
    rollback_evidence_sha256="b" * 64,
    migration_verified=True,
    rollback_verified=True,
)


def _admit(
    transition: ContextContractReleaseTransitionVerification = TRANSITION,
    *,
    current_release: ContextContractReleasePin = CURRENT_PIN,
    verification: ContextContractReleaseVerification = TARGET_VERIFICATION,
) -> ContextContractReleasePin:
    """Exercise the complete release-transition admission boundary."""
    approval = replace(TARGET_APPROVAL, verification=verification)
    return require_context_contract_release_transition_ready(
        current_release=current_release,
        verification=verification,
        approved=approval,
        required_approval_policy_sha256=REQUIRED_POLICY_SHA256,
        transition=transition,
    )


def test_release_transition_requires_migration_and_rollback_evidence() -> None:
    """A policy-approved target is admitted only with both transition proofs."""
    admitted = _admit()

    assert admitted == TARGET_PIN
    assert admitted is not TARGET_PIN


@pytest.mark.parametrize("field", ["migration_verified", "rollback_verified"])
def test_release_transition_rejects_missing_transition_gate(field: str) -> None:
    """Neither forward migration nor rollback verification may be omitted."""
    transition = replace(TRANSITION, **{field: False})

    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        _admit(transition)


def test_release_transition_rejects_truthy_shaped_gate() -> None:
    """Integer truthiness cannot impersonate verified rollback evidence."""
    transition = replace(TRANSITION, rollback_verified=1)  # type: ignore[arg-type]

    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        _admit(transition)


def test_release_transition_rejects_non_transition_receipt() -> None:
    """Another package-owned receipt type cannot impersonate transition evidence."""
    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        validate_context_contract_release_transition_verification(
            TARGET_VERIFICATION  # type: ignore[arg-type]
        )


def test_release_transition_binds_the_observed_current_release() -> None:
    """Transition evidence for another deployed source release cannot be replayed."""
    other_current = replace(CURRENT_PIN, release_version="0.1.1")

    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        _admit(current_release=other_current)


def test_release_transition_binds_the_policy_approved_target_release() -> None:
    """Transition evidence for one target cannot authorize another target release."""
    other_target = replace(TARGET_PIN, release_version="0.2.1")
    other_verification = replace(TARGET_VERIFICATION, release_pin=other_target)

    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        _admit(verification=other_verification)


def test_release_transition_rejects_noop_release_identity() -> None:
    """Migration evidence cannot manufacture a release change when source equals target."""
    noop_verification = replace(TARGET_VERIFICATION, release_pin=CURRENT_PIN)
    noop_transition = replace(TRANSITION, target_release_pin=CURRENT_PIN)

    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        _admit(noop_transition, verification=noop_verification)


def test_release_transition_rejects_malformed_evidence_identity_without_reflection() -> None:
    """Migration evidence identities remain bounded and content-free on failure."""
    transition = replace(TRANSITION, migration_evidence_sha256="migration-secret")

    with pytest.raises(ContextContractReleasePinError) as raised:
        _admit(transition)

    assert str(raised.value) == "invalid release pin"
    assert "migration-secret" not in str(raised.value)


def test_release_transition_rejects_deleted_rollback_evidence_identity() -> None:
    """Deleted rollback evidence fails through the fixed release-pin boundary."""
    transition = replace(TRANSITION)
    object.__delattr__(transition, "rollback_evidence_sha256")

    with pytest.raises(ContextContractReleasePinError, match="invalid release pin"):
        _admit(transition)
